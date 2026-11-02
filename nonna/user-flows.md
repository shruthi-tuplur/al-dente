# Nonna: User Flows

How attorneys interact with Nonna. Companion to [architecture.md](architecture.md).

Nonna has three core flows:

1. **Add a contract** (upload an executed contract so Nonna remembers it)
2. **Ask Nonna** (answer questions about what was agreed with a counterparty)
3. **Draft with Nonna** (start a new contract from what was agreed before)

The interface is a chat with structured cards and buttons where a decision is needed, so attorneys can ask in plain English but confirm terms with one click.

---

## Flow 1: Add a contract

1. The attorney uploads an executed contract (PDF or DOCX). No CLM integration is required.
2. Nonna extracts the text, identifies the parties, contract type, and effective date, and extracts key terms.
3. **Counterparty matching.** Nonna checks whether the counterparty already exists.
   - **Known counterparty, known entity:** the contract is attached to the existing counterparty.
   - **Known counterparty, new entity:** Nonna asks whether this entity belongs to an existing relationship. Example: "Is Burrata Biologics Sales AG part of your Burrata Biologics relationship?"
   - **New counterparty:** Nonna says she has not seen this company before and asks whether to create a new counterparty. On confirmation she creates a new row in `counterparties` and `counterparty_entities` (all counterparties live in the same database).
   - Matching should catch near-duplicates ("Burrata Biologics Inc." vs "Burrata Biologics, Inc.") so the same company is not created twice.
4. **Contract relationships.** Nonna asks or infers whether the contract has a parent (a SOW under an MSA) or amends another contract, so the contract family tree stays correct.
5. **Review queue.** Extracted clauses and terms are saved with review status `pending`. The attorney sees each one next to the source text and can approve, correct, or reject it.
6. Approved terms become part of the counterparty's history. Only approved or corrected clauses can become a counterparty position (enforced by the database).

---

## Flow 2: Ask Nonna

Example: "What's our liability cap with Burrata Biologics?"

1. The LLM interprets the question (counterparty, clause type, scope).
2. If the question is ambiguous, Nonna asks a clarifying question. Example: "Do you mean under the MSA, or for a specific SOW?"
3. The LLM calls **predefined lookup functions** on the database (tool calling). It never writes free-form SQL and never answers numbers from memory. Example functions:
   - `get_clause_history(counterparty, clause_type)`
   - `get_current_position(counterparty, clause_type, contract_type)`
   - `get_contract_family(contract_id)`
   - `get_decision_log(counterparty, clause_type)`
4. Nonna answers only from what the functions return, and every answer cites the document and section. Example: "Per the 2023 MSA, section 12.2, the cap is $100K."
5. Nonna accounts for hierarchy. Example: "The 2023 MSA set the cap at $100K, but Amendment 1 (2024) raised it to $150K, so the current cap is $150K."
6. If nothing is on file, Nonna says so. She never guesses.

---

## Flow 3: Draft with Nonna

Primary MVP drafting use case: **a new SOW under an existing MSA**. SOWs are the most common repeat drafting task with an existing vendor, they are short and structured, and they show off hierarchy because most terms are inherited from the MSA.

1. The attorney asks: "I need a new SOW with Burrata Biologics for a process development project."
2. Nonna asks for what she cannot know: project name, scope, timeline, budget.
3. Nonna identifies the governing MSA (and any amendments) and explains which terms carry over automatically (liability cap, indemnification, governing law).
4. For terms the SOW sets itself, Nonna shows **term cards** pre-filled with past values and their sources:
   - Payment terms: milestone based, net 30 (from SOW #3) [Use same] [Change]
5. The attorney confirms or changes each term.
6. Nonna **assembles** the draft rather than writing it from scratch:
   - Starts from the company's own SOW template ("our paper").
   - Reuses approved clause language verbatim where it exists.
   - Uses the LLM only to fill gaps (such as the scope description) or adapt a clause.
7. Every section is labeled with where it came from:
   - Verbatim from a past executed contract (with document and section)
   - Adapted from a past contract (edited for this project)
   - New language (needs careful review)
8. The attorney requests changes and Nonna revises. Each revision is saved as a new draft version.
9. When satisfied, the attorney approves the draft and downloads it as .docx.

---

## Drafts are not agreed terms

An approved draft is **not** what was agreed. After the draft goes to the counterparty, their lawyers may redline it, and the final signed version can differ. Only the **executed** contract represents what was actually agreed.

Rules:

- Approved drafts are stored separately from the agreed history and never become counterparty positions.
- When the contract is signed, the attorney uploads the executed version through Flow 1. That version enters the agreed history.
- This creates a natural job for **Too Many Cooks**: compare the executed contract against the approved draft and the counterparty baseline, and flag anything that changed during negotiation. Example: "The counterparty's redlines lowered the cap from $100K to $50K. Was this approved?"

### Open questions for draft storage (to design later)

- Tables for drafts and draft versions (each iteration saved, never overwritten).
- How each draft section links to its source clause, to power the source labels.
- Draft statuses, for example: in_progress, approved, sent, executed, abandoned.
- How an executed contract is linked back to the draft it came from, so Too Many Cooks can compare them.
- Where templates ("our paper") are stored and versioned.
- Whether the existing schema needs any changes, or whether drafts sit alongside it as new tables. Current expectation: new tables only.

---

## Phasing

- **Phase 1 (MVP):** Add a contract (upload, extract, counterparty matching, review queue), history view, and Ask Nonna (read-only, cited answers).
- **Phase 2:** Draft with Nonna, starting with SOWs under an existing MSA.
- **Phase 3:** Too Many Cooks compares executed contracts against drafts and baselines.

Ask Nonna comes before drafting because drafting relies on the same lookup functions.

---

## Where attorneys actually draft

Many attorneys draft directly in Microsoft Word, and several AI drafting tools work as Word add-ins. For the portfolio, Nonna uses a web chat interface and exports .docx. A Word add-in is a possible later direction so Nonna can meet attorneys where they already work.
