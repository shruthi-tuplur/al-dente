"""Nonna's chat: Claude answers questions using tools that read the database.

The rule: the LLM writes the sentence, the database fills the cards.
Claude only sees what the tools return, and every value shown in a card
comes straight from lookups.py, never from the model's own words.
Claude has read-only tools. It cannot approve or change anything.
"""

import json
import os
from typing import Any

import anthropic
from dotenv import load_dotenv
from sqlalchemy.orm import Session

from nonna import amendments, deadlines, drafting, lookups, notes, playbook, precedence
from nonna import history as decision_history
from nonna.sections import CATEGORY_ORDER
from nonna.schemas import BASELINE_TYPES, Card, ChatMessage, ChatResponse, ClauseType, VendorFilter

load_dotenv()

MODEL = os.getenv("NONNA_MODEL", "claude-sonnet-5-5")
MAX_TOOL_ROUNDS = 6
CLAUSE_TYPES = [c.value for c in ClauseType]

SYSTEM_PROMPT = """You are Nonna, a counterparty clause library for an in-house legal team. \
You help attorneys see what their company agreed to with each counterparty (a company they \
contract with).

How to answer:
- Only state contract facts (amounts, terms, dates, jurisdictions, clause language) that came \
from your tools in this conversation. Never guess, and never use outside knowledge about a \
company's contracts.
- If the tools return nothing relevant, say plainly that Nonna has no record of it.
- Cite the source for every fact: the contract title and section number.
- Current positions already reflect amendments. When the history shows a change, say what \
changed, when, and the decision note if there is one.
- Clauses with review_status "pending" have not been reviewed by an attorney. Say so when you \
mention them, and never treat them as agreed terms.
- Clauses with review_status "corrected" were fixed by an attorney after Nonna extracted \
them wrong. The stored value is the corrected one. If the history shows what was changed, you \
can mention the original value and the attorney's note.
- You cannot approve, reject, or change anything. If asked, say the attorney can do it from \
the review card.
- Nonna tracks seven key terms in depth: liability caps, indemnification, payment terms, \
governing law, termination for convenience (who can walk away without a reason, and the notice), \
confidentiality period (how long it lasts after the agreement ends, and whether trade secrets \
are protected for as long as they stay secret), and insurance minimums (general liability per \
occurrence and aggregate, products and professional liability). Those have extracted values, \
attorney review, and agreed baselines. In who_may_terminate, "aurelia" means only Aurelia (us) \
can terminate, "vendor" means only the vendor can, and "either" means both sides can.
- Nonna also tracks each contract's term and renewal (term_renewal): its length, whether it \
renews automatically, and the notice needed to stop it. Each contract has its own term, so \
there's no vendor-wide baseline for it.
- For questions about expirations, renewals, or notice deadlines ("what's expiring soon?", \
"when do I need to send notice to Lucca?"), use get_deadlines. Every date is worked out in \
code, so never calculate or adjust a date yourself. Give the date to act by and the contract. \
Mention any contracts whose term is still waiting for review or isn't on file. Remind the user \
that the dates are estimates from the reviewed term and should be confirmed against the contract.
- Every other clause (termination for cause, IP, force majeure, notices, the rest of the \
confidentiality and insurance wording, and so on) is filed by topic exactly as written. Use list_clause_topics to see what's on file and \
get_section_text to pull the wording. These are not reviewed and have no agreed baseline, so \
say "here's what the contract says", never "this is what was agreed". If several contracts \
have the clause, mention which ones and their dates, and don't decide which one controls.
- If a topic isn't on file, say Nonna has no record of it in that counterparty's contracts.
- For "who decided what" about a vendor (who approved the cap, why something was changed, \
what the GC signed off on, what happened recently), use get_decision_history. It's the \
permanent record: uploads, approvals, corrections, rejections, GC exceptions, which-term-controls \
calls, and notes. Quote who, when, and their reason exactly as recorded. Never add a reason \
nobody wrote. If the reason is blank, say no note was left.
- Relationship notes are what the team knows about a vendor that isn't in any contract ("they \
always fight us on IP", "business owner is in CMC", "renegotiating in Q2"). Use \
get_relationship_notes when someone asks what to know before talking to a vendor, how a vendor \
negotiates, who to talk to, or what's coming up. They're the team's own notes, not contract \
terms: say "your team noted" with who and when, and never present a note as something agreed. \
Only active notes count. Nonna can't write notes from chat; people add them in the Library.
- For "which term controls?", or when an SOW and the MSA disagree on a key term ("SOW 2 says \
net 60 but the MSA says net 45"), use check_precedence. It lines up both terms, the MSA's \
order-of-precedence clause, and whether the SOW names the MSA section and says it supersedes \
it, all checked in code. Never decide which term controls yourself, not even as a guess or a \
"likely": that's the attorney's call. Report the pieces in a few bullets. If an attorney \
already made a call (the "call" field), say which term they said controls, who, and why. If \
not, say it's waiting for an attorney's call in the Library. The card shows the precedence \
clause, so don't retype it.
- Do not give legal advice or your own opinion about whether a term is good. Report what was \
agreed. The one yardstick you can use is Aurelia's playbook, the company's own standard positions.
- Never write contract language yourself: no clauses, SOW sections, or amendment wording, not \
even a sample. To start a new SOW with a vendor, use draft_sow, which copies what was already \
agreed and checks its own numbers. If they ask to draft anything other than an SOW, say Nonna \
can only draft SOWs from history for now.
- draft_sow needs a brief: what the new project is, and any scope, fees, or timing the user \
gave. Pass their own words and don't add facts. If they haven't said what the project is, ask \
first. After it runs, say in a few bullets what it started from, what Nonna set (like payment \
terms), how many blanks are left, and any things to check. Don't quote or write clause text: \
the card shows the draft, and they can open it in the Draft tab to review, edit, and download.
- For questions about the playbook or how vendors measure up ("what's our standard cap?", \
"is Lucca's deal within our playbook?", "which vendors are outside our playbook?"), use \
check_playbook. The tool decides every tier in code: Standard (meets our standard), Fallback \
(below standard but acceptable without escalating), Off playbook (tier "outside": below even \
our fallback), or Can't compare (check by hand). Never decide or change a tier yourself. Lead \
with anything off playbook, then Fallback, and say the playbook's guidance for it. These are \
signed contracts, so an off-playbook term is something to raise at renewal or renegotiation, \
not something to approve now. A term still waiting for review that's off playbook needs GC \
sign-off before anyone approves it. If an off-playbook term has an "exception", the GC already \
signed off on it: say who and when, give their reason, and don't count it as a problem. \
Always say "Aurelia's playbook", not your view.
- If a question is ambiguous (which counterparty, which contract), ask one short question.
- When the user asks for the exact wording, language, or text of one of the four tracked \
clauses, use get_clause_text. For any other clause, use get_section_text. Both show the \
verbatim text in a card, so never retype or quote the clause yourself. Just say which \
contract and section it's from and anything notable.
- For questions across vendors ("which vendors have a cap under $1M?", "who's on Delaware \
law?", "who has net 60?"), use compare_vendors. The tool does the filtering and the math, so \
never compare or filter values yourself, and write amounts as plain numbers in the tool input \
($1M is 1000000). Name the matching vendors and their sources. If the result lists vendors \
with nothing on file, terms waiting for review, a confirmed missing clause, or a cap in another \
currency, say so briefly, so the answer is never quietly incomplete.
- For questions about how a contract reads today, what an amendment changed, or the current \
wording of a section ("what does the Lucca MSA say now?", "what did Amendment No. 1 change?"), \
use get_contract_as_amended. Nonna applies the amendments in code. Say which amendment made each \
change and when. If it lists anything to check by hand, say so plainly. This is a reading aid \
built from the signed documents, not a replacement for them.
- When the user asks for key details, an overview, or a profile of a counterparty, use \
get_counterparty_profile. The app shows it as a card, so reply with one or two sentences and \
mention anything that needs attention (like terms waiting for review).

Style: warm, plain-spoken, and brief, like a trusted colleague who has worked with this team \
for years. Two to four sentences is usually enough. The app shows detailed cards under your \
reply, so you don't need to repeat every value. You can use **bold** for key values and simple "- " bullet lists, but no headings or tables. Write amounts \
like $2,000,000."""

TOOLS: list[dict[str, Any]] = [
    {
        "name": "find_counterparty",
        "description": (
            "Search counterparties by name, or by the legal name of an entity that signed for "
            "them. Partial names work. Use this first to get a counterparty_id."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Full or partial name."}},
            "required": ["name"],
        },
    },
    {
        "name": "get_contracts",
        "description": (
            "List a counterparty's signing entities and contracts, oldest first. Shows which MSA "
            "each SOW falls under (parent_contract_id) and which contract each amendment "
            "changes (amends_contract_id)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"counterparty_id": {"type": "integer"}},
            "required": ["counterparty_id"],
        },
    },
    {
        "name": "get_current_positions",
        "description": (
            "Get the currently agreed baseline terms with a counterparty, with the source "
            "contract and section. Amendments are already applied, and only attorney-reviewed "
            "clauses become positions. applies_to says which contract types a position covers. "
            "Leave out clause_type to get every position."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "counterparty_id": {"type": "integer"},
                "clause_type": {"type": "string", "enum": BASELINE_TYPES},
            },
            "required": ["counterparty_id"],
        },
    },
    {
        "name": "get_clause_history",
        "description": (
            "How one clause type appeared across every contract with a counterparty, oldest "
            "first. Includes clauses that were absent, incorporated by reference, or still "
            "pending review, plus attorney decision notes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "counterparty_id": {"type": "integer"},
                "clause_type": {"type": "string", "enum": CLAUSE_TYPES},
            },
            "required": ["counterparty_id", "clause_type"],
        },
    },
    {
        "name": "get_counterparty_profile",
        "description": (
            "Get a full overview of a counterparty in one call: its signing entities, every "
            "contract (with which MSA each SOW or amendment belongs to), every currently agreed "
            "term with its source, and how many extracted terms are waiting for review. Use this "
            "when the user asks for key details, an overview, a summary, or a profile of a "
            "counterparty."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"counterparty_id": {"type": "integer"}},
            "required": ["counterparty_id"],
        },
    },
    {
        "name": "get_clause_text",
        "description": (
            "Get the exact, verbatim text of a clause with a counterparty, with its source "
            "contract and section. Leave out contract_id to get the currently agreed version(s), "
            "or pass a contract_id (from get_contracts) to get that contract's version. The app "
            "shows the verbatim text in a card."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "counterparty_id": {"type": "integer"},
                "clause_type": {"type": "string", "enum": CLAUSE_TYPES},
                "contract_id": {"type": "integer"},
            },
            "required": ["counterparty_id", "clause_type"],
        },
    },
    {
        "name": "list_clause_topics",
        "description": (
            "List every clause topic on file in a counterparty's contracts (like Confidentiality, "
            "Termination, Insurance), with how many contracts have each one. Use this to find "
            "the right topic name before get_section_text."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"counterparty_id": {"type": "integer"}},
            "required": ["counterparty_id"],
        },
    },
    {
        "name": "get_section_text",
        "description": (
            "Get the exact, verbatim text of any clause in a counterparty's contracts, filed by "
            "topic. Pass a topic from list_clause_topics, a word or phrase to search for (like "
            "'non-solicitation' or 'audit'), or both. Add contract_id to limit it to one "
            "contract. Not reviewed by an attorney. The app shows the verbatim text in a card."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "counterparty_id": {"type": "integer"},
                "topic": {
                    "type": "string",
                    "description": "A topic name, for example: " + ", ".join(CATEGORY_ORDER),
                },
                "search": {"type": "string", "description": "A word or phrase to look for."},
                "contract_id": {"type": "integer"},
            },
            "required": ["counterparty_id"],
        },
    },
        {
        "name": "compare_vendors",
        "description": (
            "Compare one agreed term across every vendor, with optional filters. Only agreed "
            "(attorney-reviewed) terms count as matches. The result also lists vendors with "
            "nothing on file, vendors where an attorney confirmed the clause is missing (for "
            "example no liability cap), vendors with that term still waiting for review, and "
            "caps in another currency that a USD filter can't compare. Use only the filters that "
            "fit the clause type. Leave all filters out to list every vendor's agreed term."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "clause_type": {"type": "string", "enum": BASELINE_TYPES},
                "cap_below": {"type": "number", "description": "Liability caps strictly under this USD amount."},
                "cap_at_least": {"type": "number", "description": "Liability caps at or above this USD amount."},
                "net_days_min": {"type": "integer", "description": "Payment terms of at least this many days."},
                "net_days_max": {"type": "integer", "description": "Payment terms of at most this many days."},
                "payment_structure": {"type": "string", "enum": ["invoice", "milestone"]},
                "jurisdiction": {"type": "string", "description": "Governing law, like Delaware or New York."},
                "is_mutual": {"type": "boolean", "description": "Indemnification goes both ways."},
                "covers_ip_infringement": {"type": "boolean", "description": "Indemnification covers IP infringement."},
                "notice_days_max": {
                    "type": "integer",
                    "description": "Termination for convenience on this many days' notice or less.",
                },
                "who_may_terminate": {
                    "type": "string",
                    "enum": ["either", "aurelia", "vendor"],
                    "description": "Who can terminate for convenience: either side, only Aurelia (us), or only the vendor.",
                },
                "survival_years_min": {
                    "type": "integer",
                    "description": "Confidentiality lasting at least this many years after the agreement ends (forever counts).",
                },
                "survival_years_max": {
                    "type": "integer",
                    "description": "Confidentiality lasting at most this many years after the agreement ends.",
                },
                "general_liability_below": {
                    "type": "number",
                    "description": "General liability insurance strictly under this USD amount per occurrence.",
                },
                "general_liability_at_least": {
                    "type": "number",
                    "description": "General liability insurance of at least this USD amount per occurrence.",
                },
                "applies_to": {
                    "type": "string",
                    "enum": ["MSA", "SOW", "NDA"],
                    "description": "Only terms agreed for this kind of agreement.",
                },
            },
            "required": ["clause_type"],
        },
    },
        {
        "name": "get_deadlines",
        "description": (
            "Expirations, renewals, and notice deadlines for active contracts, soonest first. "
            "Dates are worked out in code from each contract's effective date and its reviewed "
            "term. Also lists contracts whose term is waiting for review or isn't on file. "
            "Use within_days for 'coming up soon' questions, or counterparty_id for one vendor."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "within_days": {
                    "type": "integer",
                    "description": "Only deadlines in the next this many days (past ones are included).",
                },
                "counterparty_id": {"type": "integer"},
            },
        },
    },
        {
        "name": "get_contract_as_amended",
        "description": (
            "How a contract reads today with its amendments applied, worked out in code. Returns "
            "only the sections that amendments replaced, added, or deleted (with the original "
            "wording), plus anything Nonna couldn't apply and flagged to check by hand. Pass "
            "section to also get that section's current wording, changed or not. Get contract_id "
            "from get_contracts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "contract_id": {"type": "integer"},
                "section": {"type": "string", "description": "A section number, like 11.2"},
            },
            "required": ["contract_id"],
        },
    },
    {
        "name": "draft_sow",
        "description": (
            "Start the next SOW with a vendor from what was already agreed, using the same "
            "drafting code as the Library's Draft tab: standard wording copied word for word, deal "
            "sections adapted from the brief with [blanks] for anything missing, payment terms set "
            "by code to what was agreed, and every number checked. Nothing is saved. Needs the "
            "vendor's counterparty_id (use find_counterparty first) and the brief."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "counterparty_id": {"type": "integer"},
                "brief": {
                    "type": "string",
                    "description": "The new project, in the user's own words. Don't add facts they didn't give.",
                },
            },
            "required": ["counterparty_id", "brief"],
        },
    },
    {
        "name": "check_playbook",
        "description": (
            "Aurelia's playbook (our standard position and fallback for each key term, plus "
            "guidance) and how each vendor's agreed master-agreement terms measure up: Standard, "
            "Fallback, Outside (needs GC sign-off), or Can't compare. Tiers are worked out in code. "
            "Leave out counterparty_id for every vendor, and clause_type for every term."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "counterparty_id": {"type": "integer"},
                "clause_type": {"type": "string", "enum": playbook.CLAUSE_TYPES},
            },
        },
    },
    {
        "name": "get_decision_history",
        "description": (
            "Everything anyone decided about one vendor, newest first: uploads, approvals, "
            "intentional changes, corrections (before and after), rejections, GC exceptions, "
            "which-term-controls calls, and notes, each with who, when, and their reason. "
            "Optionally only one kind."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "counterparty_id": {"type": "integer"},
                "group": {
                    "type": "string",
                    "enum": ["contracts", "reviews", "gc", "precedence", "notes"],
                    "description": "Only this kind of decision. Leave out for everything.",
                },
                "limit": {"type": "integer", "description": "Newest N events. Default 25."},
            },
            "required": ["counterparty_id"],
        },
    },
    {
        "name": "get_relationship_notes",
        "description": (
            "The team's relationship notes about one vendor: how they negotiate, the people "
            "involved, and timing or plans. Not contract terms. Active notes only, newest first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"counterparty_id": {"type": "integer"}},
            "required": ["counterparty_id"],
        },
    },
    {
        "name": "check_precedence",
        "description": (
            "Which term controls when a vendor's SOW (or change order) says something different "
            "from its MSA on payment terms, liability cap, governing law, or indemnification. "
            "Returns each conflict with both terms, the MSA's order-of-precedence clause, whether "
            "the SOW names the MSA section and says it supersedes it, and the attorney's call if "
            "one was made. Checked in code; it never decides which term controls."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"counterparty_id": {"type": "integer"}},
            "required": ["counterparty_id"],
        },
    },
    {
        "name": "get_review_queue",
        "description": (
            "Extracted clauses waiting for an attorney to review. Leave out counterparty_id "
            "to see everything pending."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"counterparty_id": {"type": "integer"}},
        },
    },
]

# Short status line shown under Nonna's reply, based on the last tool she used
STATUS_FOR_TOOL = {
    "get_clause_text": "Pulled the exact wording",
    "get_section_text": "Pulled the exact wording",
    "list_clause_topics": "Checked what's on file",
    "get_counterparty_profile": "Pulled the full profile",
    "get_contracts": "Pulled the contract list",
    "get_current_positions": "Checked current terms",
    "get_clause_history": "Looked through the history",
    "get_review_queue": "Checked the review queue",
    "compare_vendors": "Compared every vendor",
    "get_deadlines": "Checked the calendar",
    "get_contract_as_amended": "Read it with the amendments applied",
    "check_playbook": "Checked against our playbook",
    "check_precedence": "Lined up the SOW and the MSA",
    "get_relationship_notes": "Read the team's notes",
    "get_decision_history": "Read the decision history",
    "draft_sow": "Drafted from what you've agreed",
}

CLAUSE_LABELS = {
    "liability_cap": "Liability cap",
    "indemnification": "Indemnification",
    "payment_terms": "Payment terms",
    "governing_law": "Governing law",
    "term_renewal": "Term and renewal",
    "termination_convenience": "Termination for convenience",
    "confidentiality": "Confidentiality period",
    "insurance": "Insurance minimums",
}


class ChatUnavailable(Exception):
    """Nonna can't reach Claude (missing key, network problem, or API error)."""


def _client() -> anthropic.Anthropic:
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key or key == "your-key-here":
        raise ChatUnavailable("ANTHROPIC_API_KEY is not set. Add your key to the .env file.")
    return anthropic.Anthropic(api_key=key)


def _add_card(cards: list[Card], card: Card) -> None:
    """Add a card unless an identical one is already there."""
    if card not in cards:
        cards.append(card)


def run_tool(session: Session, name: str, tool_input: dict[str, Any], cards: list[Card]) -> Any:
    """Run one of Nonna's tools and return JSON-safe data for Claude.

    Tools that produce something worth showing also add a card.
    """
    if name == "find_counterparty":
        return [c.model_dump(mode="json") for c in lookups.find_counterparties(session, tool_input["name"])]

    if name == "get_contracts":
        detail = lookups.get_counterparty_detail(session, tool_input["counterparty_id"])
        data = detail.model_dump(mode="json")
        _add_card(cards, Card(type="contracts", title=f"Contracts with {detail.name}", data=data))
        return data

    if name == "get_current_positions":
        clause_type = tool_input.get("clause_type")
        positions = lookups.get_positions(session, tool_input["counterparty_id"], clause_type=clause_type)
        data = [p.model_dump(mode="json") for p in positions]
        title = CLAUSE_LABELS[clause_type] if clause_type else "Current agreed terms"
        _add_card(cards, Card(type="positions", title=title, data=data))
        return data

    if name == "get_clause_history":
        clause_type = tool_input["clause_type"]
        history = lookups.get_clause_history(session, tool_input["counterparty_id"], clause_type)
        data = [h.model_dump(mode="json") for h in history]
        _add_card(cards, Card(type="history", title=f"{CLAUSE_LABELS[clause_type]} history", data=data))
        return data

    if name == "get_counterparty_profile":
        counterparty_id = tool_input["counterparty_id"]
        detail = lookups.get_counterparty_detail(session, counterparty_id)
        data = {
            "counterparty": detail.model_dump(mode="json"),
            "positions": [p.model_dump(mode="json") for p in lookups.get_positions(session, counterparty_id)],
            "pending_review": len(lookups.get_review_queue(session, counterparty_id)),
        }
        _add_card(cards, Card(type="profile", title=detail.name, data=data))
        return data

    if name == "get_clause_text":
        clause_type = tool_input["clause_type"]
        texts = lookups.get_clause_texts(
            session, tool_input["counterparty_id"], clause_type, tool_input.get("contract_id")
        )
        data = [t.model_dump(mode="json") for t in texts]
        if data:
            _add_card(cards, Card(type="clause", title=f"{CLAUSE_LABELS[clause_type]} · exact wording", data=data))
        return data

    if name == "list_clause_topics":
        return [t.model_dump(mode="json") for t in lookups.list_topics(session, tool_input["counterparty_id"])]

    if name == "get_section_text":
        topic, search = tool_input.get("topic"), tool_input.get("search")
        if not topic and not search:
            raise ValueError("Pass a topic, a search phrase, or both.")
        texts = lookups.get_section_texts(
            session, tool_input["counterparty_id"], topic, search, tool_input.get("contract_id")
        )
        data = [t.model_dump(mode="json") for t in texts]
        if data:
            label = data[0]["section"]["category"] if topic else f"“{search}”"
            _add_card(cards, Card(type="section", title=f"{label} · exact wording", data=data))
        return data

    if name == "compare_vendors":
        clause_type = tool_input["clause_type"]
        filters = VendorFilter(**{k: v for k, v in tool_input.items() if k != "clause_type"})
        comparison = lookups.compare_vendors(session, clause_type, filters)
        data = comparison.model_dump(mode="json")
        _add_card(cards, Card(type="vendors", title=f"{CLAUSE_LABELS[clause_type]} across vendors", data=data))
        return data
    if name == "get_deadlines":
        result = deadlines.get_deadlines(
            session, tool_input.get("within_days"), tool_input.get("counterparty_id")
        )
        data = result.model_dump(mode="json")
        within = tool_input.get("within_days")
        title = f"Deadlines in the next {within} days" if within else "Expirations and renewals"
        _add_card(cards, Card(type="deadlines", title=title, data=data))
        return data
    
    if name == "get_contract_as_amended":
        result = amendments.as_amended(session, tool_input["contract_id"])
        wanted = tool_input.get("section")
        # Only what changed (plus the one section asked about), not the whole contract
        shown = [s for s in result.sections if s.status != "original" or s.number == wanted]
        data = result.model_dump(mode="json")
        data["sections"] = [s.model_dump(mode="json") for s in shown]
        if wanted and not any(s.number == wanted for s in result.sections):
            data["note"] = f"There's no Section {wanted} in this contract."
        _add_card(cards, Card(type="amended", title=f"{result.contract.title}, as amended", data=data))
        return data

    if name == "draft_sow":
        try:
            draft = drafting.make_draft(
                session, int(tool_input["counterparty_id"]), drafting.DraftIn(brief=str(tool_input.get("brief", "")))
            )
        except drafting.DraftUnavailable as error:
            raise ValueError(str(error)) from error
        _add_card(cards, Card(
            type="draft",
            title=f"Draft SOW No. {draft.number} with {draft.counterparty_name}",
            data=draft.model_dump(mode="json"),
        ))
        # The model gets a summary only. The wording stays in the card, so it can't be retyped or changed.
        return {
            "sow_number": draft.number,
            "vendor": draft.counterparty_name,
            "started_from": draft.template,
            "verbatim_sections": sum(s.label == "verbatim" for s in draft.sections),
            "adapted_sections": sum(s.label != "verbatim" for s in draft.sections),
            "blanks_to_fill_in": draft.blanks,
            "things_to_check": [c for s in draft.sections for c in s.checks],
            "what_nonna_changed": [
                f"{s.number + '. ' if s.number else ''}{s.heading or s.kind}: {s.note}"
                for s in draft.sections
                if s.note and s.note != "Adapted from your brief."
            ],
        }

    if name == "check_playbook":
        result = playbook.check_vendors(session, tool_input.get("counterparty_id"))
        wanted = tool_input.get("clause_type")
        data = result.model_dump(mode="json")
        if wanted:
            data["rules"] = [r for r in data["rules"] if r["clause_type"] == wanted]
            for row in data["rows"]:
                row["cells"] = {wanted: row["cells"].get(wanted)}
            cells = [row["cells"][wanted] or {} for row in data["rows"]]
            data["outside_count"] = sum(c.get("tier") == "outside" and not c.get("exception") for c in cells)
            data["exception_count"] = sum(c.get("tier") == "outside" and bool(c.get("exception")) for c in cells)
        names = [r["counterparty_name"] for r in data["rows"]]
        title = f"{names[0]} vs our playbook" if tool_input.get("counterparty_id") and names else "Vendors vs our playbook"
        _add_card(cards, Card(type="playbook", title=title, data=data))
        return data

    if name == "get_decision_history":
        result = decision_history.get_history(session, tool_input["counterparty_id"])
        group = tool_input.get("group")
        events = [e for e in result.events if not group or e.group == group]
        limit = max(1, min(int(tool_input.get("limit") or 25), 100))
        result = result.model_copy(update={"events": events[:limit]})
        data = result.model_dump(mode="json")
        _add_card(cards, Card(type="decisions", title=f"Decision history: {result.counterparty_name}", data=data))
        return data

    if name == "get_relationship_notes":
        result = notes.get_notes(session, tool_input["counterparty_id"], include_archived=False)
        data = result.model_dump(mode="json")
        _add_card(cards, Card(type="notes", title=f"Team notes: {result.counterparty_name}", data=data))
        return data

    if name == "check_precedence":
        report = precedence.get_conflicts(session, tool_input["counterparty_id"])
        data = report.model_dump(mode="json")
        _add_card(cards, Card(type="precedence", title=f"Which term controls: {report.counterparty_name}", data=data))
        return data

    if name == "get_review_queue":
        queue = lookups.get_review_queue(session, tool_input.get("counterparty_id"))
        data = [q.model_dump(mode="json") for q in queue]
        _add_card(cards, Card(type="review_queue", title="Waiting for review", data=data))
        return data

    raise ValueError(f"Unknown tool: {name}")


def run_chat(session: Session, history: list[ChatMessage]) -> ChatResponse:
    """Send the conversation to Claude, run any tools it asks for, and return the reply."""
    client = _client()
    messages: list[dict[str, Any]] = [{"role": m.role, "content": m.content} for m in history]
    cards: list[Card] = []
    status: str | None = None

    for _ in range(MAX_TOOL_ROUNDS):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )
        except anthropic.APIError as error:
            raise ChatUnavailable(f"Couldn't reach Claude: {error}") from error

        if response.stop_reason != "tool_use":
            break

        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            status = STATUS_FOR_TOOL.get(block.name, status)
            try:
                output = run_tool(session, block.name, block.input, cards)
                results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(output)}
                )
            except (lookups.NotFound, amendments.NotFound, ValueError, KeyError) as error:
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(error),
                        "is_error": True,
                    }
                )

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": results})
    else:
        return ChatResponse(
            reply="That took more digging than I can do in one go. Try asking a narrower question.",
            status=status,
            cards=cards,
        )

    # The profile card already shows the contracts and agreed terms, so don't repeat them
    if any(card.type == "profile" for card in cards):
        cards = [c for c in cards if c.type not in ("contracts", "positions")]

    reply = "".join(block.text for block in response.content if block.type == "text").strip()
    return ChatResponse(reply=reply or "I'm not sure how to answer that.", status=status, cards=cards)