"""The "as amended" view: a contract as it reads today, with its amendments applied.

Amendments change contracts with a few standard instructions, so Nonna reads them with
plain code, no AI:
- "Section 11.2 of the Agreement is hereby deleted in its entirety and replaced with the following:"
- "Section 4 of the Agreement is amended and restated to read as follows:"
- "Section 9.4 of the Agreement is hereby deleted in its entirety."
- "The following new Section 13.7 is added to the Agreement:"

Anything an amendment says about a section that Nonna can't apply with confidence is
listed as "check by hand" instead of guessed. Nothing here is saved: the view is worked
out fresh from the original documents every time, so it's always a reading aid, never a
replacement for the signed documents.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload

from nonna.extraction import SIGNATURE_START, split_sections
from nonna.models import Contract
from nonna.schemas import SourceContract

NUMBER = r"(\d{1,2}(?:\.\d{1,2})*(?:\([a-z0-9]+\))?)"
AGREEMENT = r"(?:of\s+the\s+(?:Agreement|MSA|Master\s+Services\s+Agreement|SOW|Statement\s+of\s+Work)\s+)?"

REPLACE = re.compile(
    r"Section\s+" + NUMBER + r"\s+" + AGREEMENT
    + r"is\s+(?:hereby\s+)?(?:deleted\s+in\s+its\s+entirety\s+and\s+replaced\s+(?:with|by)"
    r"|amended\s+and\s+restated(?:\s+in\s+its\s+entirety)?(?:\s+to\s+read\s+as\s+follows)?"
    r"|amended\s+to\s+read\s+as\s+follows"
    r"|replaced\s+(?:with|by))"
    r"(?:\s+the\s+following)?\s*:",
    re.IGNORECASE,
)
DELETE = re.compile(
    r"Section\s+" + NUMBER + r"\s+" + AGREEMENT + r"is\s+(?:hereby\s+)?deleted(?:\s+in\s+its\s+entirety)?\s*\.",
    re.IGNORECASE,
)
ADD = re.compile(
    r"(?:the\s+following\s+)?(?:a\s+)?new\s+Section\s+" + NUMBER + r"[^:.]{0,80}?\s+is\s+(?:hereby\s+)?(?:added|inserted)[^:.]{0,80}:"
    r"|(?:is\s+hereby\s+amended\s+by\s+)?(?:adding|inserting)\s+(?:the\s+following\s+)?(?:as\s+)?(?:a\s+)?new\s+Section\s+"
    + NUMBER + r"[^:.]{0,80}:",
    re.IGNORECASE,
)
# A top-level heading in the amendment itself, like "2. Effect of Amendment"
AMENDMENT_HEADING = re.compile(r"^[ \t]*(\d{1,2})\.[ \t]+(?=[A-Z])", re.MULTILINE)
# A sentence that changes a section, used to catch instructions Nonna can't apply
CHANGE_VERB = re.compile(
    r"\b(?:is|are|shall\s+be|will\s+be)\s+(?:hereby\s+)?(?:amended|replaced|deleted|modified|"
    r"inserted|added|restated|superseded|revised|changed)\b",
    re.IGNORECASE,
)
# Sentence ends (not the dots inside section numbers like 11.2) and line breaks
SENTENCE_BREAK = re.compile(r"(?<=[a-z\)\]\"”])[.;]\s+|\n")
SECTION_MENTION = re.compile(r"Section\s+" + NUMBER, re.IGNORECASE)

Status = Literal["original", "replaced", "added", "deleted"]


@dataclass
class Instruction:
    action: Literal["replace", "delete", "add"]
    section: str
    new_text: str  # empty for deletions
    start: int  # where the instruction sits in the amendment, for citing it
    end: int


class AmendedSection(BaseModel):
    number: str
    heading: str
    text: str  # how it reads today (empty if deleted)
    status: Status
    changed_by: SourceContract | None = None
    original_text: str | None = None  # how it read before, for replaced and deleted sections


class Unresolved(BaseModel):
    amendment: SourceContract
    section: str | None
    wording: str  # the amendment's own sentence, so the attorney can check it


class AmendedContract(BaseModel):
    contract: SourceContract
    amendments: list[SourceContract]  # applied in order, oldest first
    sections: list[AmendedSection]
    unresolved: list[Unresolved]
    changed_count: int


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _key(number: str) -> tuple:
    """Sort key so 2 < 2.1 < 2.10 < 10."""
    return tuple(int(p) if p.isdigit() else p for p in re.split(r"[.()]+", number) if p)


def _heading(text: str, number: str) -> str:
    first = text.strip().splitlines()[0] if text.strip() else ""
    first = re.sub(r"^[\"“']?\s*" + re.escape(number) + r"\.?\s*", "", first)
    return re.split(r"(?<=[a-z\)])\.\s", first, maxsplit=1)[0][:120]


def read_instructions(text: str) -> tuple[list[Instruction], list[tuple[str | None, str]]]:
    """Find the changes an amendment makes. Returns the instructions and any sentences it can't apply."""
    signatures = SIGNATURE_START.search(text)
    body = text[: signatures.start()] if signatures else text

    found: list[tuple[str, re.Match]] = []
    for action, pattern in (("replace", REPLACE), ("delete", DELETE), ("add", ADD)):
        found += [(action, m) for m in pattern.finditer(body)]
    found.sort(key=lambda f: f[1].start())

    # A deletion that's really "deleted in its entirety and replaced" was already caught as a replacement
    replaced_spans = [m.span() for action, m in found if action == "replace"]
    found = [
        (a, m) for a, m in found
        if a != "delete" or not any(s <= m.start() < e for s, e in replaced_spans)
    ]

    instructions: list[Instruction] = []
    for i, (action, match) in enumerate(found):
        number = next(g for g in match.groups() if g)
        if action == "delete":
            instructions.append(Instruction("delete", number, "", match.start(), match.end()))
            continue

        # The new wording runs until the next instruction or the amendment's next top-level heading
        start = match.end()
        stops = [len(body)]
        if i + 1 < len(found):
            next_start = found[i + 1][1].start()
            stops.append(body.rfind("\n", start, next_start) + 1 or next_start)
        top = number.split(".")[0].split("(")[0]
        # The amendment numbers its own items ("1.2 Section 9.4 ... is deleted"). The new wording
        # stops at the amendment's next item, but not at the restated section's own subsections.
        line_start = body.rfind("\n", 0, match.start()) + 1
        own = re.match(r"[ \t]*(\d{1,2})\.\d{1,2}[ \t]", body[line_start:match.start() + 1])
        if own and own.group(1) != top:
            item = re.compile(r"^[ \t]*" + own.group(1) + r"\.\d{1,2}[ \t]", re.MULTILINE)
            next_item = item.search(body, start + 1)
            if next_item:
                stops.append(next_item.start())
        for heading in AMENDMENT_HEADING.finditer(body, start + 1):
            if heading.group(1) != top:
                stops.append(heading.start())
                break
        end = min(s for s in stops if s > start)
        new_text = body[start:end].strip().strip("\"“”'")
        # Drop a trailing amendment sub-number left at the end, like a dangling "1.2"
        new_text = re.sub(r"\n[ \t]*\d{1,2}\.\d{1,2}[ \t]*$", "", new_text).strip()
        instructions.append(Instruction(action, number, new_text, match.start(), end))

    # Sentences that change a section in a way Nonna didn't apply, like "Section 13.1 is modified so that..."
    unresolved: list[tuple[str | None, str]] = []
    covered = [(ins.start, ins.end) for ins in instructions]
    position = 0
    for piece in SENTENCE_BREAK.split(body):
        start = body.find(piece, position)
        position = start + len(piece)
        wording = _flat(piece)
        if not SECTION_MENTION.search(wording) or not CHANGE_VERB.search(wording):
            continue
        if any(start < e and position > s for s, e in covered) or re.search(r"except as expressly", wording, re.IGNORECASE):
            continue
        mention = SECTION_MENTION.search(wording)
        unresolved.append((mention.group(1) if mention else None, wording))
    return instructions, unresolved


def apply(
    base_text: str,
    amendments: list[tuple[SourceContract, str]],
) -> tuple[list[AmendedSection], list[Unresolved]]:
    """Apply each amendment's instructions to the base contract, oldest first. Pure, so it's easy to test."""
    sections = [
        AmendedSection(number=s.number, heading=s.heading, text=s.text, status="original")
        for s in split_sections(base_text)
    ]
    unresolved: list[Unresolved] = []

    def find(number: str) -> int | None:
        return next((i for i, s in enumerate(sections) if s.number == number and s.status != "deleted"), None)

    for source, text in amendments:
        instructions, leftovers = read_instructions(text)
        unresolved += [Unresolved(amendment=source, section=n, wording=w) for n, w in leftovers]

        for ins in instructions:
            index = find(ins.section)
            if ins.action == "add":
                if index is not None:
                    unresolved.append(Unresolved(
                        amendment=source, section=ins.section,
                        wording=f"Adds a new Section {ins.section}, but the agreement already has one. Check by hand.",
                    ))
                    continue
                new = AmendedSection(
                    number=ins.section, heading=_heading(ins.new_text, ins.section),
                    text=ins.new_text, status="added", changed_by=source,
                )
                position = next((i for i, s in enumerate(sections) if _key(s.number) > _key(ins.section)), len(sections))
                sections.insert(position, new)
                continue

            if index is None:
                unresolved.append(Unresolved(
                    amendment=source, section=ins.section,
                    wording=f"Changes Section {ins.section}, but Nonna couldn't find that section in the agreement.",
                ))
                continue

            # Changing a whole section also changes its subsections
            children = [
                i for i, s in enumerate(sections)
                if s.number.startswith(ins.section + ".") and s.status != "deleted"
            ]
            target = sections[index]
            original = "\n".join([target.text] + [sections[i].text for i in children])
            for i in children:
                sections[i] = sections[i].model_copy(update={
                    "status": "deleted", "changed_by": source, "original_text": sections[i].text, "text": "",
                })
            if ins.action == "delete":
                sections[index] = target.model_copy(update={
                    "status": "deleted", "changed_by": source, "original_text": original, "text": "",
                })
            else:
                sections[index] = target.model_copy(update={
                    "status": "replaced", "changed_by": source,
                    "original_text": target.original_text or original,
                    "text": ins.new_text, "heading": _heading(ins.new_text, ins.section) or target.heading,
                })
            if children and ins.action == "replace":
                # The restated section now carries its own subsections, so don't list the old ones separately
                sections = [s for i, s in enumerate(sections) if i not in children]

    return sections, unresolved


def _source(contract: Contract) -> SourceContract:
    return SourceContract(
        id=contract.id, contract_type=contract.contract_type,
        title=contract.title, effective_date=contract.effective_date,
    )


class NotFound(Exception):
    pass


def as_amended(session: Session, contract_id: int) -> AmendedContract:
    contract = session.get(Contract, contract_id, options=[selectinload(Contract.amendments)])
    if contract is None:
        raise NotFound(f"No contract with id {contract_id}.")
    amendments = sorted(contract.amendments, key=lambda a: a.effective_date)
    sections, unresolved = apply(
        contract.full_text or "",
        [(_source(a), a.full_text or "") for a in amendments],
    )
    return AmendedContract(
        contract=_source(contract),
        amendments=[_source(a) for a in amendments],
        sections=sections,
        unresolved=unresolved,
        changed_count=sum(1 for s in sections if s.status != "original"),
    )