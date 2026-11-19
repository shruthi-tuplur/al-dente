"""Explain a highlighted phrase from a contract in plain English.

Code finds the contract's own definition of any defined term in the phrase and quotes it word
for word, because in a contract, its own definition controls. Claude then explains the phrase
in plain English, using that definition and the passage around it. Only the phrase, the nearby
passage, and any definitions found are sent to Claude, never the whole contract.

It explains what the words mean. It doesn't say whether a term is good or what to do about it.
"""

from __future__ import annotations

import os
import re

import anthropic
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from nonna.models import Contract

MODEL = os.getenv("NONNA_MODEL", "claude-sonnet-5-5")
MAX_DEFINITIONS = 3

QUOTE_OPEN = "[\"\u201c]"
QUOTE_CLOSE = "[\"\u201d]"
NOT_QUOTE = "[^\"\u201c\u201d]"
SECTION_NUMBER = re.compile(r"(\d{1,2}\.\d{1,2})\s+(?=\S)")
# Where a definition stops: the next numbered paragraph (1.7) or the next article heading (2. SERVICES)
NEXT_PARAGRAPH = re.compile(r"\s(?:\d{1,2}\.\d{1,2}\s+\S|\d{1,2}\.\s+[A-Z]{2,})")


class ExplainIn(BaseModel):
    phrase: str = Field(min_length=1, max_length=600)
    context: str = Field(default="", max_length=2500)  # the passage around the phrase
    contract_id: int | None = None


class Definition(BaseModel):
    term: str
    section: str | None  # like "1.6", when the definition is in a numbered paragraph
    text: str  # word for word from the contract


class Explanation(BaseModel):
    phrase: str
    explanation: str
    definitions: list[Definition]


class ExplainUnavailable(Exception):
    pass


# ---------------------------------------------------------------------------
# Finding the contract's own definitions (pure, so it's easy to test)
# ---------------------------------------------------------------------------

def _flatten(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def candidate_terms(phrase: str) -> list[str]:
    """Terms in the phrase that the contract might define: the phrase itself if it's short,
    anything in quotes, and capitalized words or word groups (like "Confidential Information")."""
    clean = phrase.strip().strip(".,;:()[]\"'\u201c\u201d")
    found: list[str] = []
    if 0 < len(clean.split()) <= 6:
        found.append(clean)
    found += re.findall(rf"{QUOTE_OPEN}({NOT_QUOTE}{{2,60}}){QUOTE_CLOSE}", phrase)
    found += re.findall(r"\b[A-Z][A-Za-z]+(?:\s+(?:of\s+)?[A-Z][A-Za-z]+)*\b", phrase)
    out: list[str] = []
    for term in found:
        term = term.strip()
        for variant in (term, term[:-1] if term.endswith("s") else term + "s"):
            if len(variant) >= 2 and variant.lower() not in {t.lower() for t in out}:
                out.append(variant)
    return out


def _sentence_around(flat: str, start: int, end: int) -> str:
    left = max(flat.rfind(". ", 0, start), flat.rfind("; ", 0, start))
    left = left + 2 if left >= 0 else 0
    right_match = re.search(r"\.(?=\s|$)", flat[end:])
    right = end + right_match.end() if right_match else min(len(flat), end + 400)
    # A long opening paragraph: keep just the part around the definition
    if right - left > 450:
        left = max(left, flat.rfind(" ", 0, max(0, start - 220)) + 1)
        right = min(right, end + 120)
        cut = flat.rfind(" ", start, right)
        right = cut if cut > end else right
        return f"…{flat[left:right].strip()}…"
    return flat[left:right].strip()


def _defined_with_means(flat: str, quoted: str) -> re.Match[str] | None:
    """ "Deliverables" means ..., or "Statement of Work" or "SOW" means ...
    Prefers the real definition over a pointer like "has the meaning given in Section 7.1"."""
    for verb in (r"means|shall mean", r"has the meaning"):
        first_name = rf"{quoted}(?:\s+or\s+{QUOTE_OPEN}{NOT_QUOTE}+{QUOTE_CLOSE})?\s+(?:{verb})\b"
        second_name = rf"{QUOTE_OPEN}{NOT_QUOTE}+{QUOTE_CLOSE}\s+or\s+{quoted}\s+(?:{verb})\b"
        match = re.search(first_name, flat) or re.search(second_name, flat)
        if match:
            return match
    return None


def find_definitions(full_text: str, phrase: str) -> list[Definition]:
    """The contract's own definitions of terms in the phrase, quoted word for word."""
    flat = _flatten(full_text)
    results: list[Definition] = []
    seen: set[str] = set()

    def add(term: str, section: str | None, text: str) -> None:
        if text[:80] not in seen:
            seen.add(text[:80])
            results.append(Definition(term=term, section=section, text=text))

    for term in candidate_terms(phrase):
        if len(results) >= MAX_DEFINITIONS:
            break
        quoted = rf"{QUOTE_OPEN}{re.escape(term)}{QUOTE_CLOSE}"

        # Style 1: "Deliverables" means ... (often in a numbered definitions paragraph)
        match = _defined_with_means(flat, quoted)
        if match is not None:
            start = match.start()
            section = None
            window_start = max(0, start - 40)
            number = list(SECTION_NUMBER.finditer(flat[window_start : start + 1]))
            if number and window_start + number[-1].end() >= start - 25:
                section = number[-1].group(1)
                start = window_start + number[-1].end()
            # The definition runs to the next numbered paragraph or heading, up to ~700 characters
            rest = flat[match.end():]
            next_paragraph = NEXT_PARAGRAPH.search(rest)
            stop = min(next_paragraph.start() if next_paragraph else len(rest), 700)
            text = (flat[start:match.end()] + rest[:stop]).strip()
            if not text.endswith("."):
                cut = text.rfind(". ")
                text = text[: cut + 1] if cut > 40 else text + "…"
            add(term, section, text)
            continue

        # Style 2: defined in passing, like (the "Initial Term") or ("Provider")
        inline = re.search(rf"\((?:the\s+|each,?\s+an?\s+|each\s+a\s+)?{quoted}\)", flat)
        if inline is not None:
            add(term, None, _sentence_around(flat, inline.start(), inline.end()))
    return results


# ---------------------------------------------------------------------------
# Asking Claude for the plain-English version
# ---------------------------------------------------------------------------

EXPLAIN_PROMPT = """\
You explain contract language in plain English for someone who isn't a lawyer, like a business \
person or a new paralegal at Aurelia Therapeutics. You get a highlighted phrase (from a contract, \
or from Nonna's summary of one), the passage around it, and sometimes the contract's own \
definitions of terms in it.

Rules:
- Explain what the phrase means here, in 2 to 4 short sentences. Use everyday words.
- If the contract defines a term, explain it using that definition. The contract's own \
definition controls over the general meaning.
- If it's a legal term of art, say what it generally means, in plain words.
- Don't say whether the term is good or bad for Aurelia, and don't tell them what to do. \
Explain meaning only. If it's unclear or could be read more than one way, say so.
- Plain text only: no headings, bullet points, asterisks, or other markdown, and no preamble \
like "Great question". Just the explanation.
"""


def ask_claude(phrase: str, context: str, definitions: list[Definition]) -> str:
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key or key == "your-key-here":
        raise ExplainUnavailable("ANTHROPIC_API_KEY is not set. Add your key to the .env file.")
    parts = [f"<phrase>{phrase}</phrase>"]
    if context.strip():
        parts.append(f"<passage>{context}</passage>")
    for d in definitions:
        where = f" section=\"{d.section}\"" if d.section else ""
        parts.append(f"<definition term=\"{d.term}\"{where}>{d.text}</definition>")
    try:
        response = anthropic.Anthropic(api_key=key).messages.create(
            model=MODEL,
            max_tokens=800,
            system=EXPLAIN_PROMPT,
            messages=[{"role": "user", "content": "\n".join(parts)}],
        )
    except anthropic.APIError as error:
        raise ExplainUnavailable(f"Couldn't reach Claude: {error}") from error
    text = "".join(block.text for block in response.content if block.type == "text").strip()
    if not text:
        raise ExplainUnavailable("Claude didn't return an explanation. Try again.")
    return text


def explain(session: Session, request: ExplainIn) -> Explanation:
    phrase = _flatten(request.phrase)
    definitions: list[Definition] = []
    if request.contract_id is not None:
        contract = session.get(Contract, request.contract_id)
        if contract is not None and contract.full_text:
            definitions = find_definitions(contract.full_text, phrase)
    return Explanation(
        phrase=phrase,
        explanation=ask_claude(phrase, _flatten(request.context), definitions),
        definitions=definitions,
    )