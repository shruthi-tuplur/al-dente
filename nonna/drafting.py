"""Drafting from history: start a new SOW from what was already agreed with this vendor.

How a draft is built:
- The newest SOW on file is the starting point. Its standard wording is copied word for word.
- The attorney writes a short brief about the new project. Claude adapts only the deal parts
  (project overview, services, deliverables, fees, contacts, term) and leaves [blanks] for
  anything the brief doesn't say.
- Code, not Claude, sets the exact things: the SOW number, the payment terms (back to what was
  agreed in the MSA), and blank dates for the effective date and signatures.
- Code then checks Claude's work: any dollar amount, date, or count that isn't in the brief or
  the old SOW is flagged, and milestone fees are added up against the total.

Every section is labeled Verbatim (copied as is), Adapted (changed, with the old wording kept
for comparison), or New. Nothing is saved: the attorney reviews the draft, edits it, and
downloads it as a Word file.
"""

from __future__ import annotations

import io
import os
import re
import zipfile
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal
from xml.sax.saxutils import escape

import anthropic
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from nonna.extraction import SIGNATURE_START
from nonna.models import Clause, Contract, Counterparty, CounterpartyPosition

MODEL = os.getenv("NONNA_MODEL", "claude-sonnet-5-5")

Label = Literal["verbatim", "adapted", "new"]
Kind = Literal["title", "preamble", "article", "signatures"]


class DraftSection(BaseModel):
    kind: Kind
    number: str = ""  # "5" for an article; empty for the title, preamble, and signatures
    heading: str = ""
    text: str  # one paragraph per line; table rows use " | " between cells
    label: Label
    source: str  # where the wording came from
    original: str | None = None  # the old wording, when the section was adapted
    note: str | None = None  # why it changed, in plain English
    checks: list[str] = []  # things the attorney should double-check


class Draft(BaseModel):
    counterparty_id: int
    counterparty_name: str
    contract_type: str
    number: int  # SOW No. 3 -> 3
    brief: str
    template: str  # the contract the draft started from
    sections: list[DraftSection]
    blanks: int  # how many [blanks] are left to fill in


class DraftIn(BaseModel):
    brief: str = Field(min_length=10, max_length=4000)
    contract_type: Literal["SOW"] = "SOW"


class DraftUnavailable(Exception):
    """Nonna can't make this draft (nothing to start from, or Claude can't be reached)."""


# ---------------------------------------------------------------------------
# Reading the old SOW (pure functions, so they're easy to test)
# ---------------------------------------------------------------------------

MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
DATE = re.compile(rf"\b(?:{MONTHS})\s+\d{{1,2}},\s+\d{{4}}\b")
ARTICLE = re.compile(r"^(\d{1,2})\.\s+(\S.*)$")
PARAGRAPH_START = re.compile(r"^(?:\d{1,2}\.\d{1,2}\s|M\d+\s|Milestone\s+Deliverable)")
TABLE_ROW = re.compile(rf"^(M\d+)\s+(.+?)\s+((?:{MONTHS})\s+\d{{1,2}},\s+\d{{4}})$")
FOOTER = re.compile(r"^\s*(?:Confidential\s*·\s*)?Page \d+ of \d+\s*$", re.IGNORECASE)
DISCLAIMER = re.compile(r"^\s*Sample document created", re.IGNORECASE)
PAYMENT_PARAGRAPH = re.compile(r"^\d{1,2}\.\d{1,2}\s+Payment Terms\b|within\s+[\w\s()-]+\s+days\s+after", re.IGNORECASE)
DEAL_HEADINGS = ("overview", "scope", "service", "deliverable", "timeline", "milestone", "fee", "contact", "term of")


def clean_lines(text: str) -> list[str]:
    """Contract text as lines, without page footers or blank lines."""
    return [line.rstrip() for line in text.splitlines() if line.strip() and not FOOTER.match(line)]


def join_paragraphs(lines: list[str]) -> list[str]:
    """Undo the line wrapping from the PDF: a new paragraph starts at 5.1, M1, or a table header."""
    paragraphs: list[str] = []
    for line in lines:
        line = line.strip()
        if paragraphs and not PARAGRAPH_START.match(line):
            paragraphs[-1] += " " + line
        else:
            paragraphs.append(line)
    out = []
    for paragraph in paragraphs:
        row = TABLE_ROW.match(paragraph)
        if row:
            paragraph = " | ".join(row.groups())
        elif re.match(r"^Milestone\s+Deliverable\s+Target date$", paragraph):
            paragraph = "Milestone | Deliverable | Target date"
        out.append(paragraph)
    return out


class Parsed(BaseModel):
    title_lines: list[str]
    preamble: str
    articles: list[tuple[str, str, list[str]]]  # (number, heading, paragraphs)
    signatures: list[str]


def parse_sow(text: str) -> Parsed:
    """Split an SOW into its title lines, opening paragraph, numbered articles, and signatures."""
    lines = clean_lines(text)
    first_article = next((i for i, line in enumerate(lines) if ARTICLE.match(line.strip())), None)
    if first_article is None:
        raise DraftUnavailable("Nonna couldn't find numbered sections in the old SOW to draft from.")

    header = lines[:first_article]
    opening = next((i for i, line in enumerate(header) if re.match(r"^\s*This\s", line)), len(header))
    title_lines = [line.strip() for line in header[:opening]]
    preamble = " ".join(line.strip() for line in header[opening:])

    body = "\n".join(lines[first_article:])
    signature = SIGNATURE_START.search(body)
    body_text, signature_text = (body[: signature.start()], body[signature.start():]) if signature else (body, "")

    articles: list[tuple[str, str, list[str]]] = []
    current: list[str] = []
    for line in body_text.splitlines():
        match = ARTICLE.match(line.strip())
        if match:
            if articles or current:
                articles[-1] = (articles[-1][0], articles[-1][1], join_paragraphs(current))
            articles.append((match.group(1), match.group(2).strip(), []))
            current = []
        else:
            current.append(line)
    if articles:
        articles[-1] = (articles[-1][0], articles[-1][1], join_paragraphs(current))

    signatures = []
    for line in signature_text.splitlines():
        if DISCLAIMER.match(line):
            break
        signatures.append(line.strip())
    return Parsed(title_lines=title_lines, preamble=preamble, articles=articles, signatures=signatures)


def is_deal_article(heading: str) -> bool:
    return any(word in heading.lower() for word in DEAL_HEADINGS)


# ---------------------------------------------------------------------------
# The parts code sets on its own
# ---------------------------------------------------------------------------

ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def number_words(n: int) -> str:
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + ("" if n % 10 == 0 else "-" + ONES[n % 10])
    if n < 1000:
        rest = n % 100
        return ONES[n // 100] + " hundred" + ("" if rest == 0 else " " + number_words(rest))
    return str(n)


def title_lines_for(old: list[str], number: int, amended: bool) -> list[str]:
    out = []
    for line in old:
        if re.fullmatch(r"(?i)execution version|final|executed", line):
            out.append("DRAFT")
            continue
        line = re.sub(r"(?i)(statement of work no\.\s*)\d+", lambda m: f"{m.group(1)}{number}", line)
        if amended and re.search(r"(?i)master services agreement dated", line) and "amended" not in line.lower():
            line += ", as amended"
        out.append(line)
    return out


def preamble_for(old: str, number: int, amended: bool) -> str:
    text = re.sub(r"(?i)(statement of work no\.\s*)\d+", lambda m: f"{m.group(1)}{number}", old)
    text = re.sub(rf"(as of )(?:{MONTHS})\s+\d{{1,2}},\s+\d{{4}}", r"\1[SOW Effective Date]", text, count=1)
    if amended and "as amended" not in text:
        text = re.sub(r"(Agreement between the Parties dated (?:" + MONTHS + r")\s+\d{1,2},\s+\d{4})", r"\1, as amended", text, count=1)
    return text


def payment_paragraph(old: str, net_days: int, msa_section: str | None) -> str:
    """The SOW's payment terms, set back to what was agreed in the MSA."""
    number = re.match(r"^(\d{1,2}\.\d{1,2})\s", old)
    prefix = f"{number.group(1)} Payment Terms. " if number else "Payment Terms. "
    reference = f", as provided in Section {msa_section} of the Agreement" if msa_section else ""
    return (
        f"{prefix}Client shall pay each undisputed milestone invoice within {number_words(net_days)} "
        f"({net_days}) days after Client's receipt of such invoice{reference}."
    )


def short_name(title: str) -> str:
    """"STATEMENT OF WORK NO. 1 - Process Development Services" -> "SOW No. 1"."""
    match = re.search(r"(?i)statement of work no\.?\s*(\d+)|\bSOW\s*(?:no\.?\s*)?(\d+)", title)
    return f"SOW No. {match.group(1) or match.group(2)}" if match else title


def drop_payment_exception(text: str, payment_number: str) -> str:
    """Remove "Except as expressly stated in Section 5.3 of this SOW, ..." once 5.3 follows the MSA."""
    pattern = rf"\s*Except as (?:expressly )?(?:stated|provided|set forth) in Section {re.escape(payment_number)}\b[^.]*\."
    return re.sub(pattern, "", text)


def signatures_for(old: list[str]) -> list[str]:
    return [re.sub(rf"^(Date:\s*)(?:{MONTHS})\s+\d{{1,2}},\s+\d{{4}}$", r"\1[date]", line) for line in old]


# ---------------------------------------------------------------------------
# Checking Claude's work
# ---------------------------------------------------------------------------

MONEY = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s*(million|m|mm|k|thousand)?\b", re.IGNORECASE)
COUNT = re.compile(r"\((\d+)\)")


def money_values(text: str) -> set[Decimal]:
    values = set()
    for amount, scale in MONEY.findall(text):
        try:
            value = Decimal(amount.replace(",", ""))
        except InvalidOperation:
            continue
        scale = scale.lower()
        if scale in ("million", "m", "mm"):
            value *= 1_000_000
        elif scale in ("k", "thousand"):
            value *= 1_000
        values.add(value.normalize())
    return values


def _money(value: Decimal) -> str:
    return f"${value:,.0f}"


def check_numbers(new_text: str, allowed_text: str) -> list[str]:
    """Flag dollar amounts, dates, and counts that aren't in the brief or the old SOW."""
    checks = []
    allowed_money = money_values(allowed_text)
    for value in sorted(money_values(new_text) - allowed_money):
        checks.append(f"{_money(value)} isn't in your brief or the old SOW. Check it.")
    allowed_dates = set(DATE.findall(allowed_text))
    for found in sorted(set(DATE.findall(new_text)) - allowed_dates):
        checks.append(f"{found} isn't in your brief or the old SOW. Check it.")
    allowed_counts = set(COUNT.findall(allowed_text)) | set(re.findall(r"\b\d+\b", allowed_text))
    for found in sorted(set(COUNT.findall(new_text)) - allowed_counts, key=int):
        checks.append(f"The count ({found}) isn't in your brief or the old SOW. Check it.")
    return checks


def check_fee_total(text: str) -> list[str]:
    """If the fees list milestone amounts and a total, make sure they add up."""
    total = re.search(r"total fees[^$]*\$\s?([\d,]+(?:\.\d+)?)", text, re.IGNORECASE)
    parts = re.findall(r"\bM\d+\s+\$\s?([\d,]+(?:\.\d+)?)", text)
    if not total or len(parts) < 2:
        return []
    stated = Decimal(total.group(1).replace(",", ""))
    added = sum(Decimal(p.replace(",", "")) for p in parts)
    if added != stated:
        return [f"The milestone fees add up to {_money(added)}, but the total says {_money(stated)}."]
    return []


def count_blanks(text: str) -> int:
    return len(re.findall(r"\[[^\]]+\]", text))


def same(a: str, b: str) -> bool:
    return re.sub(r"\s+", " ", a).strip() == re.sub(r"\s+", " ", b).strip()


# ---------------------------------------------------------------------------
# Asking Claude to adapt the deal parts
# ---------------------------------------------------------------------------

ADAPT_PROMPT = """\
You help an in-house attorney at Aurelia Therapeutics start a new Statement of Work with a vendor \
they've worked with before. You get the attorney's brief for the new project and the deal sections \
of the most recent SOW with this vendor. Rewrite only what the brief requires.

Rules:
- Keep the old SOW's wording, numbering, defined terms, and structure. Change facts, not style.
- If the brief doesn't say something the section needs (a date, an amount, a name, a quantity), \
put a short placeholder in square brackets, like [target date] or [M3 fee]. Never invent amounts, \
dates, names, or quantities.
- If a section doesn't need to change for the new project, return it exactly as it was.
- Write numbers the way the old SOW does, like "two (2)" and "$1,240,000".
- Put each numbered paragraph on its own line. Write table rows as cells separated by " | ", \
keeping the header row.
- Don't add legal terms, warranties, or obligations that weren't in the old SOW.
- Don't add payment-timing language. Payment terms are handled separately.
- Always answer by calling the adapted_sow tool, with every section you were given.
"""

ADAPT_TOOL = {
    "name": "adapted_sow",
    "description": "The adapted project title and deal sections for the new SOW.",
    "input_schema": {
        "type": "object",
        "properties": {
            "project_title": {"type": "string", "description": "The new project's title line, in the old SOW's style."},
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "number": {"type": "string"},
                        "text": {"type": "string", "description": "The section's paragraphs, one per line."},
                    },
                    "required": ["number", "text"],
                },
            },
        },
        "required": ["project_title", "sections"],
    },
}


def ask_claude(brief: str, number: int, project_title: str, deal: list[tuple[str, str, str]]) -> dict:
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key or key == "your-key-here":
        raise DraftUnavailable("ANTHROPIC_API_KEY is not set. Add your key to the .env file.")
    old = "\n\n".join(f'<section number="{n}" heading="{h}">\n{t}\n</section>' for n, h, t in deal)
    message = (
        f"<brief>\n{brief}\n</brief>\n\n"
        f"The new SOW will be Statement of Work No. {number}.\n"
        f"<old_project_title>{project_title}</old_project_title>\n\n{old}"
    )
    try:
        response = anthropic.Anthropic(api_key=key).messages.create(
            model=MODEL,
            max_tokens=4000,
            system=ADAPT_PROMPT,
            tools=[ADAPT_TOOL],
            messages=[{"role": "user", "content": message}],
        )
    except anthropic.APIError as error:
        raise DraftUnavailable(f"Couldn't reach Claude: {error}") from error
    answer = next((b.input for b in response.content if b.type == "tool_use"), None)
    if not answer:
        raise DraftUnavailable("Claude didn't return a draft. Try again.")
    return answer


# ---------------------------------------------------------------------------
# Putting the draft together
# ---------------------------------------------------------------------------

def build_draft(
    parsed: Parsed,
    *,
    brief: str,
    number: int,
    amended: bool,
    template_name: str,
    adapted: dict,
    net_days: int | None,
    msa_section: str | None,
    payment_history: str | None,
) -> list[DraftSection]:
    """Assemble the sections. Pure: Claude's answer comes in as `adapted`."""
    source = template_name
    allowed = brief + "\n" + "\n".join(parsed.title_lines) + "\n" + parsed.preamble + "\n" + "\n".join(
        "\n".join(p) for _, _, p in parsed.articles
    )
    sections: list[DraftSection] = []

    # Title: the SOW number is set by code, the project title by Claude
    old_title = "\n".join(parsed.title_lines)
    new_title_lines = title_lines_for(parsed.title_lines, number, amended)
    project_title = str(adapted.get("project_title") or "").strip()
    if project_title and len(new_title_lines) > 2:
        new_title_lines[2] = project_title
    sections.append(DraftSection(
        kind="title", text="\n".join(new_title_lines), label="adapted", source=source, original=old_title,
        note=f"Numbered No. {number} because there {'is' if number == 2 else 'are'} {number - 1} SOW"
             f"{'' if number == 2 else 's'} with this vendor on file.",
    ))

    # Opening paragraph: new number, blank effective date
    sections.append(DraftSection(
        kind="preamble", text=preamble_for(parsed.preamble, number, amended), label="adapted",
        source=source, original=parsed.preamble, note="New SOW number, and the effective date is left blank.",
    ))

    by_number = {str(s.get("number", "")).strip().rstrip("."): str(s.get("text", "")) for s in adapted.get("sections", [])}

    # Which paragraph holds the payment terms (like "5.3"), so other sections can stop pointing at it
    payment_number = next(
        (
            m.group(1)
            for _, heading, paragraphs in parsed.articles if is_deal_article(heading)
            for p in paragraphs if PAYMENT_PARAGRAPH.search(p)
            for m in [re.match(r"^(\d{1,2}\.\d{1,2})\s", p)] if m
        ),
        None,
    )

    for article_number, heading, paragraphs in parsed.articles:
        old_text = "\n".join(paragraphs)
        if not is_deal_article(heading):
            new_text = old_text
            if net_days is not None and payment_number:
                new_text = drop_payment_exception(old_text, payment_number)
            if same(new_text, old_text):
                sections.append(DraftSection(
                    kind="article", number=article_number, heading=heading, text=old_text,
                    label="verbatim", source=f"{source} §{article_number}",
                ))
            else:
                sections.append(DraftSection(
                    kind="article", number=article_number, heading=heading, text=new_text, label="adapted",
                    source=f"{source} §{article_number}", original=old_text,
                    note=f"Removed the exception for Section {payment_number}. In the old SOW, {payment_number} "
                         f"overrode the MSA's payment terms. In this draft it follows the MSA, so the exception "
                         f"would point at nothing.",
                ))
            continue

        payment_index = next((i for i, p in enumerate(paragraphs) if PAYMENT_PARAGRAPH.search(p)), None)
        new_text = by_number.get(article_number, old_text).strip() or old_text
        new_paragraphs = [p.strip() for p in new_text.splitlines() if p.strip()]
        notes = []
        if payment_index is not None:
            new_paragraphs = [p for p in new_paragraphs if not PAYMENT_PARAGRAPH.search(p)]
            if net_days is not None:
                fixed = payment_paragraph(paragraphs[payment_index], net_days, msa_section)
                notes.append(
                    f"Payment terms set by Nonna to the agreed net {net_days}"
                    + (f" from MSA §{msa_section}" if msa_section else "") + "."
                    + (f" {payment_history}" if payment_history else "")
                )
            else:
                fixed = paragraphs[payment_index]
                notes.append("No agreed payment terms on file, so the old SOW's wording was kept. Check it.")
            new_paragraphs.insert(min(payment_index, len(new_paragraphs)), fixed)
        new_text = "\n".join(new_paragraphs)

        # Nonna's own payment sentence isn't Claude's work, so it doesn't need checking
        written_by_nonna = fixed if payment_index is not None else ""
        checks = check_numbers(new_text, allowed + "\n" + written_by_nonna) + check_fee_total(new_text)
        if same(new_text, old_text):
            sections.append(DraftSection(
                kind="article", number=article_number, heading=heading, text=old_text,
                label="verbatim", source=f"{source} §{article_number}", checks=checks,
            ))
        else:
            sections.append(DraftSection(
                kind="article", number=article_number, heading=heading, text=new_text, label="adapted",
                source=f"{source} §{article_number}", original=old_text,
                note=" ".join(notes) or "Adapted from your brief.", checks=checks,
            ))

    # Signatures: same signers, blank dates
    new_signatures = signatures_for(parsed.signatures)
    sections.append(DraftSection(
        kind="signatures", text="\n".join(new_signatures),
        label="verbatim" if new_signatures == parsed.signatures else "adapted",
        source=source, original="\n".join(parsed.signatures),
        note="Same signers as last time with the dates left blank. Confirm they're still the right people.",
    ))
    return sections


def _agreed_payment(session: Session, counterparty_id: int) -> tuple[int | None, str | None]:
    """The agreed net days and the MSA section they come from."""
    position = session.scalars(
        select(CounterpartyPosition)
        .where(
            CounterpartyPosition.counterparty_id == counterparty_id,
            CounterpartyPosition.clause_type == "payment_terms",
            CounterpartyPosition.superseded_at.is_(None),
        )
        .options(selectinload(CounterpartyPosition.baseline_clause).selectinload(Clause.terms))
    ).all()
    master = next((p for p in position if "MSA" in p.contract_type_scope), None)
    if master is None:
        return None, None
    days = next((t.value for t in master.baseline_clause.terms if t.term_key == "net_days"), None)
    return (int(days) if days is not None else None), master.baseline_clause.section_number


def _payment_history(sows: list[Contract], net_days: int | None) -> str | None:
    """A sentence about earlier SOWs that set different payment terms."""
    if net_days is None:
        return None
    different = []
    for sow in sows:
        for clause in sow.clauses:
            if clause.clause_type != "payment_terms" or clause.presence != "present":
                continue
            days = next((t.value for t in clause.terms if t.term_key == "net_days"), None)
            if days is not None and int(days) != net_days:
                different.append(f"{short_name(sow.title)} said net {int(days)}")
    return ("Earlier SOWs drifted: " + "; ".join(different) + ".") if different else None


def make_draft(session: Session, counterparty_id: int, change: DraftIn) -> Draft:
    vendor = session.get(Counterparty, counterparty_id)
    if vendor is None:
        raise DraftUnavailable("Nonna doesn't have that vendor.")
    contracts = session.scalars(
        select(Contract).where(Contract.counterparty_id == counterparty_id)
        .options(selectinload(Contract.clauses).selectinload(Clause.terms))
    ).all()
    sows = sorted((c for c in contracts if c.contract_type == "SOW"), key=lambda c: c.effective_date)
    with_text = [c for c in sows if c.full_text and len(c.full_text) > 500]
    if not with_text:
        raise DraftUnavailable(f"Nonna needs at least one SOW with {vendor.name} on file, with its full text, to draft from.")
    template = with_text[-1]
    amended = any(c.contract_type == "amendment" for c in contracts)

    parsed = parse_sow(template.full_text)
    net_days, msa_section = _agreed_payment(session, counterparty_id)
    deal = [(n, h, "\n".join(p)) for n, h, p in parsed.articles if is_deal_article(h)]
    project_title = parsed.title_lines[2] if len(parsed.title_lines) > 2 else ""
    number = len(sows) + 1
    adapted = ask_claude(change.brief, number, project_title, deal)

    template_name = f"{short_name(template.title)} ({template.effective_date:%b %-d, %Y})"
    sections = build_draft(
        parsed, brief=change.brief, number=number, amended=amended, template_name=template_name,
        adapted=adapted, net_days=net_days, msa_section=msa_section,
        payment_history=_payment_history(sows, net_days),
    )
    return Draft(
        counterparty_id=vendor.id, counterparty_name=vendor.name, contract_type="SOW", number=number,
        brief=change.brief, template=template_name, sections=sections,
        blanks=sum(count_blanks(s.text) for s in sections),
    )


# ---------------------------------------------------------------------------
# Word file (built by hand: a .docx is a zip of XML files, so no extra library is needed)
# ---------------------------------------------------------------------------

def _runs(text: str, bold: bool = False) -> str:
    """Text as Word runs, with [blanks] highlighted yellow so they're easy to find."""
    out = []
    for piece in re.split(r"(\[[^\]]+\])", text):
        if not piece:
            continue
        props = ("<w:b/>" if bold else "") + ('<w:highlight w:val="yellow"/>' if piece.startswith("[") else "")
        out.append(f'<w:r><w:rPr>{props}</w:rPr><w:t xml:space="preserve">{escape(piece)}</w:t></w:r>')
    return "".join(out)


def _paragraph(text: str, *, bold: bool = False, align: str | None = None, space_after: int = 120) -> str:
    props = f'<w:spacing w:after="{space_after}"/>' + (f'<w:jc w:val="{align}"/>' if align else "")
    return f"<w:p><w:pPr>{props}</w:pPr>{_runs(text, bold)}</w:p>"


def _table(rows: list[list[str]]) -> str:
    border = '<w:{0} w:val="single" w:sz="4" w:space="0" w:color="555555"/>'
    borders = "".join(border.format(side) for side in ("top", "left", "bottom", "right", "insideH", "insideV"))
    xml = [f'<w:tbl><w:tblPr><w:tblW w:w="5000" w:type="pct"/><w:tblBorders>{borders}</w:tblBorders></w:tblPr>']
    for i, row in enumerate(rows):
        cells = "".join(f"<w:tc>{_paragraph(cell, bold=i == 0, space_after=0)}</w:tc>" for cell in row)
        xml.append(f"<w:tr>{cells}</w:tr>")
    xml.append("</w:tbl>")
    return "".join(xml) + _paragraph("", space_after=60)


def to_docx(draft: Draft) -> bytes:
    body: list[str] = []
    for section in draft.sections:
        lines = [line for line in section.text.splitlines() if line.strip()]
        if section.kind == "title":
            for i, line in enumerate(lines):
                body.append(_paragraph(line, bold=i == 1, align="right" if i == 0 else "center"))
        elif section.kind == "preamble":
            body.append(_paragraph(section.text, align="both", space_after=200))
        elif section.kind == "article":
            body.append(_paragraph(f"{section.number}. {section.heading}", bold=True, space_after=100))
            rows: list[list[str]] = []
            for line in lines + [""]:
                if " | " in line:
                    rows.append([cell.strip() for cell in line.split(" | ")])
                    continue
                if rows:
                    body.append(_table(rows))
                    rows = []
                if line:
                    body.append(_paragraph(line, align="both"))
        else:
            body.append(_paragraph("", space_after=200))
            for line in lines:
                body.append(_paragraph(line, bold=line.isupper(), space_after=60))
    body.append(_paragraph("", space_after=480))
    body.append(_paragraph(
        f"Draft started by Nonna from {draft.template}. Review every section before sending.",
        align="center", space_after=0,
    ))

    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
        + "".join(body)
        + '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720" w:gutter="0"/>'
        "</w:sectPr></w:body></w:document>"
    )
    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" '
        'w:cs="Times New Roman"/><w:sz w:val="23"/></w:rPr></w:rPrDefault></w:docDefaults></w:styles>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/></Relationships>'
    )
    document_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/></Relationships>'
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", content_types)
        docx.writestr("_rels/.rels", rels)
        docx.writestr("word/document.xml", document)
        docx.writestr("word/_rels/document.xml.rels", document_rels)
        docx.writestr("word/styles.xml", styles)
    return buffer.getvalue()


def docx_name(draft: Draft) -> str:
    return f"{draft.counterparty_name} SOW No. {draft.number} draft {date.today():%Y-%m-%d}.docx"