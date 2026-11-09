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

from nonna import lookups
from nonna.sections import CATEGORY_ORDER
from nonna.schemas import Card, ChatMessage, ChatResponse, ClauseType, VendorFilter

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
- Nonna tracks four key terms in depth: liability caps, indemnification, payment terms, and \
governing law. Those have extracted values, attorney review, and agreed baselines.
- Every other clause (confidentiality, termination, IP, insurance, force majeure, notices, and \
so on) is filed by topic exactly as written. Use list_clause_topics to see what's on file and \
get_section_text to pull the wording. These are not reviewed and have no agreed baseline, so \
say "here's what the contract says", never "this is what was agreed". If several contracts \
have the clause, mention which ones and their dates, and don't decide which one controls.
- If a topic isn't on file, say Nonna has no record of it in that counterparty's contracts. \
Drafting is not available yet.
- Do not give legal advice or opinions about whether a term is good. Report what was agreed.
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
                "clause_type": {"type": "string", "enum": CLAUSE_TYPES},
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
                "clause_type": {"type": "string", "enum": CLAUSE_TYPES},
                "cap_below": {"type": "number", "description": "Liability caps strictly under this USD amount."},
                "cap_at_least": {"type": "number", "description": "Liability caps at or above this USD amount."},
                "net_days_min": {"type": "integer", "description": "Payment terms of at least this many days."},
                "net_days_max": {"type": "integer", "description": "Payment terms of at most this many days."},
                "payment_structure": {"type": "string", "enum": ["invoice", "milestone"]},
                "jurisdiction": {"type": "string", "description": "Governing law, like Delaware or New York."},
                "is_mutual": {"type": "boolean", "description": "Indemnification goes both ways."},
                "covers_ip_infringement": {"type": "boolean", "description": "Indemnification covers IP infringement."},
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
}

CLAUSE_LABELS = {
    "liability_cap": "Liability cap",
    "indemnification": "Indemnification",
    "payment_terms": "Payment terms",
    "governing_law": "Governing law",
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
            except (lookups.NotFound, ValueError, KeyError) as error:
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