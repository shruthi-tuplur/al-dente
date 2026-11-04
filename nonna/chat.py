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
from nonna.schemas import Card, ChatMessage, ChatResponse, ClauseType

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
- You cannot approve, reject, or change anything. If asked, say the attorney can do it from \
the review card.
- Nonna tracks liability caps, indemnification, payment terms, and governing law. For any \
other clause type, say Nonna doesn't track it yet. Drafting is not available yet either.
- Do not give legal advice or opinions about whether a term is good. Report what was agreed.
- When the user asks for the exact wording, language, or text of a clause, use \
get_clause_text. The card shows the verbatim text, so never retype, quote, or paraphrase the \
clause yourself. Just say which contract and section it's from and anything notable.
- When the user asks for key details, an overview, or a profile of a counterparty, use \
get_counterparty_profile. The app shows it as a card, so reply with one or two sentences and \
mention anything that needs attention (like terms waiting for review).

Style: warm, plain-spoken, and brief, like a trusted colleague who has worked with this team \
for years. Lead with the direct answer in one sentence. Keep the whole reply under 80 words \
unless the user asks for more detail. Mention only the most important source and any warning \
(a pending review, a value mismatch). The app shows cards with the full details and every \
source under your reply, so never list every clause or section in your text. You can use **bold** for key values and simple "- " bullet lists, but no headings or tables. Write amounts like $2,000,000."""

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
    "get_contracts": "Pulled the contract list",
    "get_current_positions": "Checked current terms",
    "get_clause_history": "Looked through the history",
    "get_review_queue": "Checked the review queue",
    "get_counterparty_profile": "Pulled the full profile",
    "get_clause_text": "Pulled the exact wording",
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