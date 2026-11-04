"""Index every section of a contract under a clause category, verbatim.

Nonna tracks four clause types with extracted values, review, and baselines.
Everything else is indexed here as written, so attorneys can browse every
clause with every counterparty. No values are extracted and nothing here is
reviewed, it's a catalog of exactly what each contract says.

Run this to index contracts that were uploaded before sections existed:
    uv run python -m nonna.sections
"""

import re

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from nonna.extraction import Section, split_sections
from nonna.models import Contract, ContractSection

# Checked in order, so more specific phrases come first
CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("Definitions", ("definition", "interpretation")),
    ("Limitation of liability", ("limitation of liability", "cap on liability", "exclusion of certain damages", "excluded claims", "liability")),
    ("Indemnification", ("indemnif",)),
    ("Fees and payment", ("fee", "invoic", "payment", "expense", "disputed amount", "late payment", "due date", "bank account")),
    ("Termination", ("terminat", "survival", "insolvency")),
    ("Term and renewal", ("term", "renewal")),
    ("Confidentiality", ("confidential", "compelled disclosure", "nondisclosure")),
    ("Intellectual property", ("intellectual property", "work product", "background ip", "license", "ownership")),
    ("Representations and warranties", ("representation", "warrant", "disclaimer")),
    ("Insurance", ("insurance",)),
    ("Quality and compliance", ("quality", "compliance", "audit", "inspection", "regulatory")),
    ("Governing law", ("governing law", "applicable law")),
    ("Disputes and venue", ("venue", "jurisdiction", "dispute", "arbitration")),
    ("Notices", ("notice",)),
    ("Assignment", ("assignment", "subcontract")),
    ("Force majeure", ("force majeure",)),
    ("Relationship of the parties", ("independent contractor", "relationship")),
    ("Boilerplate", ("entire agreement", "severab", "waiver", "counterpart")),
    ("Incorporation", ("incorporat",)),
    ("Services and statements of work", ("services", "statement of work", "statements of work", "change order", "order of precedence")),
    ("Materials", ("materials",)),
    ("Project contacts", ("contact",)),
    ("Scope, deliverables, and timeline", ("project", "deliverable", "milestone", "timeline", "overview")),
]

# Category order in the library, roughly the order they appear in a contract
# (anything not listed sorts after, alphabetically)
CATEGORY_ORDER = [
    "Definitions", "Services and statements of work", "Scope, deliverables, and timeline",
    "Fees and payment", "Term and renewal", "Termination", "Confidentiality",
    "Intellectual property", "Representations and warranties", "Indemnification",
    "Limitation of liability", "Insurance", "Quality and compliance", "Materials",
    "Governing law", "Disputes and venue", "Notices", "Assignment", "Force majeure",
    "Relationship of the parties", "Incorporation", "Project contacts", "Boilerplate",
]


def categorize(heading: str) -> str | None:
    lowered = heading.lower()
    for category, keywords in CATEGORY_RULES:
        if any(re.search(rf"\b{re.escape(k)}", lowered) for k in keywords):
            return category
    return None


ACRONYMS = {"sow": "SOW", "msa": "MSA", "nda": "NDA", "ip": "IP", "cgmp": "cGMP"}


def _title(heading: str) -> str:
    text = heading.strip(" .:")
    if not text.isupper():
        return text
    words = text.capitalize().split(" ")
    return " ".join(ACRONYMS.get(w.lower(), w) for w in words)


def _is_sentence(heading: str) -> bool:
    """True when the "heading" is really the start of a sentence, like '"Affiliate" means...'."""
    lowered = heading.lower()
    return len(heading.split()) > 6 or heading[:1] in "\"“'" or " means " in lowered or " shall " in lowered


def _is_compound(heading: str) -> bool:
    """True for headings that cover several topics, like 'Term and Termination' or 'General'."""
    return " and " in heading.lower() or "," in heading


def build_sections(text: str) -> list[dict]:
    """Split a contract into categorized entries. Subsections that share a category stay together."""
    sections = split_sections(text)
    top_level = {s.number: s for s in sections if "." not in s.number}
    entries: list[dict] = []

    current: list[Section] = []
    current_category = ""
    current_parent = ""

    def flush() -> None:
        if not current:
            return
        parent = top_level.get(current_parent)
        first = current[0]
        if parent is not None and (len(current) > 1 or _is_sentence(first.heading)):
            number, heading = parent.number, _title(parent.heading)
        else:
            number, heading = first.number, _title(first.heading)
        body = "\n".join(s.text for s in current).strip()
        if len(body) < 20:
            return
        entries.append({
            "category": current_category,
            "section_number": number,
            "heading": heading[:200],
            "full_text": body,
            "start_offset": first.start,
            "end_offset": current[-1].end,
        })

    for section in sections:
        is_top = "." not in section.number
        parent_number = section.number.split(".")[0]
        parent = None if is_top else top_level.get(parent_number)
        if is_top and any(s.number.startswith(section.number + ".") for s in sections):
            continue  # a heading line like "7. CONFIDENTIALITY", its subsections carry the text

        own = None if _is_sentence(section.heading) else categorize(section.heading)
        parent_category = categorize(parent.heading) if parent is not None else None
        if parent_category and (own is None or not _is_compound(parent.heading)):
            category = parent_category
        else:
            category = own or _title(parent.heading if parent is not None else section.heading)

        if current and category == current_category and parent_number == current_parent and not is_top:
            current.append(section)
            continue
        flush()
        current = [section]
        current_category = category
        current_parent = parent_number
    flush()
    return entries


def index_contract(session: Session, contract: Contract) -> int:
    """Replace a contract's indexed sections. Returns how many were saved."""
    session.execute(delete(ContractSection).where(ContractSection.contract_id == contract.id))
    entries = build_sections(contract.full_text or "")
    for position, entry in enumerate(entries):
        session.add(ContractSection(contract_id=contract.id, position=position, **entry))
    session.commit()
    return len(entries)


if __name__ == "__main__":
    from nonna.database import SessionLocal

    with SessionLocal() as session:
        for contract in session.scalars(select(Contract).order_by(Contract.id)):
            count = index_contract(session, contract)
            print(f"{contract.title}: {count} sections")