# Nonna 👵🍝

**A counterparty clause library for in-house legal teams.** Nonna remembers what your team actually agreed to with every vendor, across every MSA, SOW, amendment, and change order, the way a nonna never forgets a recipe.

Part of [Al Dente](../README.md), a library of legal AI tools built to be clean, secure, and trustworthy enough for a whole legal team.

---

## The problem

Legal teams negotiate with the same companies over and over. But when someone asks "what did we agree to with this vendor last time?", the answer is usually buried across a stack of PDFs: an MSA, three SOWs, an amendment that changed one section, and a change order nobody remembers.

Most clause libraries store a company's **standard** positions. They don't store the history of what was **actually negotiated** with each counterparty. So terms quietly drift: a new SOW says net 60 when the MSA says net 45, a cap gets lowered, and nobody notices until it matters. Teams without API access to their CLM have even less visibility.

I saw this firsthand while interning at an in-house contracts team at a pharmaceutical company. Nonna is the tool I wished they had.

## What Nonna does

- **Upload a contract** (PDF or Word). Nonna reads it, proposes the parties, contract type, effective date, and which MSA it falls under, and an attorney confirms before anything is saved.
- **Extracts key terms** (liability cap, payment terms, governing law, indemnification) and saves them as *pending* until an attorney reviews them.
- **Review dashboard** with every pending term grouped by vendor and contract, shown next to what's currently agreed, with a **Matches** or **Different** badge so drift is visible before anyone clicks Approve.
- **Drift guard.** Approving a term that differs from the agreed baseline is blocked unless the attorney approves it as an intentional change with a note.
- **Corrections.** Attorneys can fix values Nonna extracted wrong. The original value is kept in the decision log, and changing an agreed term still requires explicit confirmation.
- **Chat.** Ask in plain English: "what's our liability cap with Lucca and has it changed?", "what was the exact indemnity clause we used?", "which vendors have a cap under $1M?" Answers come with cards showing the data and its source.
- **Library.** Browse every vendor, every contract (grouped by type, with the full text and the original file), and every clause:
  - **Key terms Nonna tracks:** the four terms with values, review status, and version history (Agreed vs Earlier version)
  - **Every clause, as written:** every section of every contract, filed under about 20 topics (Confidentiality, IP, Termination, Force majeure, and so on), verbatim with a Copy button
- **Questions across all vendors.** Compare one agreed term across the whole vendor list, with filters. The math happens in code, never in the model.

## How it works
Nonna is the app. Inside it, Claude (Anthropic's AI model) does three specific jobs: proposing contract details at intake, reading indemnification clauses, and answering chat questions with read-only tools. Everything else, including value extraction, the drift guard, and all comparisons, is plain code.

```
Upload → Intake → Attorney confirms → Extraction → Pending review → Attorney decides → Agreed baseline
                                          │                                                │
                                          └── every section filed by topic (catalog)       └── decision log (append-only)
```

1. **Intake.** Claude reads only the opening of the contract (data minimization) to propose parties, type, and date. Every proposal comes with a quote from the contract, and the quotes are checked in code to make sure they actually appear in the text. Nonna suggests which MSA a SOW or amendment belongs to. Nothing is saved until an attorney confirms.
2. **Extraction.** Deterministic code (regex and parsing) pulls exact values: dollar amounts, payment days, governing law. Claude is used only for indemnification, which is too varied for patterns, and it only sees that one section.
3. **Review.** Every extracted term starts as pending. An attorney approves, rejects, corrects, or approves it as an intentional change. Only reviewed terms can become the agreed baseline, and the database enforces that.
4. **Baselines.** Each vendor has one agreed position per term per contract scope (MSA and amendments share one; SOWs and change orders share another). New contracts are compared against it.
5. **Chat.** Claude answers using read-only tools that call fixed database lookups. It can't approve anything, can't run free-form SQL, and every value in a card comes straight from the database.

## Design choices

**AI where it helps, deterministic code where it must be exact, humans review the output.**

- **The LLM writes the sentence, the database fills the card.** Values, quotes, and clause text shown in the app are never typed by the model.
- **Read-only tools.** The chat model can look things up but cannot approve, reject, or change anything.
- **Human review gates the baseline.** A database trigger refuses to make an unreviewed clause an agreed position.
- **Append-only decision log.** Review decisions can be added, never edited or deleted, enforced by a database trigger. Corrections record exactly what changed (from and to) plus a required note.
- **Drift guard everywhere.** Approving a different value, or correcting an agreed term, both require an explicit "this change was intentional" step with a note. A correction can't be used to quietly change what was agreed.
- **"Not found" is not "absent."** If extraction can't find a clause, it's flagged for a human instead of being recorded as missing. Redacted text gets its own status.
- **Drafts are not agreed terms.** Only executed contracts, reviewed by an attorney, count.
- **Honest answers.** Nonna says when she has no record, when keyword search might have missed something, when a term is still pending, and when a comparison isn't possible (like a cap in euros against a USD filter, which she lists instead of converting).
- **Data minimization.** Each step sends Claude only what it needs: the opening of a contract for intake, one section for indemnification, and tool results for chat.
- **Catalog vs tracked terms.** The "every clause" catalog is verbatim and never reviewed, so it can never become a baseline. Only the four tracked terms get values, review, and drift checks.

See [architecture.md](architecture.md) for the full database design and [user-flows.md](user-flows.md) for the screens.

## Tech stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2, PostgreSQL
- **AI:** Claude API (tool use for chat, structured extraction for intake and indemnification)
- **Frontend:** React, TypeScript, Vite
- **Parsing:** pypdf, python-docx

## Run it locally

You'll need Python 3.12, [uv](https://docs.astral.sh/uv/), PostgreSQL, Node.js, and an Anthropic API key.

**1. Database**

```bash
createdb al_dente
psql al_dente -f nonna/db/schema.sql
psql al_dente -f nonna/db/seed.sql
psql al_dente -f nonna/db/seed_more_vendors.sql
```

**2. Environment.** Create a `.env` file in the repo root (it's gitignored, never commit it):

```
DATABASE_URL=postgresql+psycopg://YOUR_USER@localhost:5432/al_dente
ANTHROPIC_API_KEY=your-key-here
NONNA_OUR_COMPANY=Aurelia Therapeutics
```

Optional: `NONNA_MODEL` to choose the Claude model.

**3. Backend** (from the repo root)

```bash
uv run uvicorn nonna.api:app --reload
```

API docs at http://127.0.0.1:8000/docs

**4. Frontend**

```bash
cd nonna/web
npm install
npm run dev
```

Open http://localhost:5173

**5. Try it.** Upload the sample contracts in `data/base/` in this order: the Lucca MSA, SOW No. 1, Amendment No. 1, then SOW No. 2 (it has a planted payment term drift). Then ask:

- "nonna what are the key details for lucca?"
- "what's our liability cap with lucca and has it changed?"
- "what was the exact indemnity clause we used for lucca?"
- "which vendors have a liability cap under $1M?"
- "what's the non-compete with lucca?" (there isn't one, and she won't invent one)

## Data

All contracts and companies are **fictional**, written for this project (Aurelia Therapeutics and its vendors: Lucca Biologics, Castellan Bioprocessing, and others). No confidential, client, or employer data is used anywhere. Testing on public SEC EDGAR exhibits is planned.

## Results

Formal evals are in progress. What's been tested by hand so far:

- **No invented clauses.** Asked about a non-compete that doesn't exist, Nonna searched several terms, cited what she found (and why it wasn't a non-compete), said keyword search could miss differently worded language, and didn't make one up.
- **Planted drift caught.** Lucca SOW No. 2 changes payment terms to net 60 without the language needed to override the MSA's net 45. Approval is blocked by the drift guard and the Review dashboard marks it as Different.
- **Amendments tracked.** The liability cap shows $2.5M as an earlier version and $3M as agreed after Amendment No. 1.
- **Currency honesty.** Asked to compare caps against €1M, Nonna declined to convert currencies and said so.
- **Correction audit.** Nonna noticed a corrected value that didn't match the clause text and pointed to the correction history.

**Coming next:** extraction accuracy per clause type on a labeled set, and a hallucination test set (questions about clauses that exist vs ones that don't).

## Limitations

- **Four tracked terms.** Only liability cap, payment terms, governing law, and indemnification have extracted values, review, and drift checks. Everything else is browsable verbatim but not compared.
- **Topic sorting uses headings.** Contracts with unusual headings can produce odd topic names in the catalog. They still show up, just sorted to the bottom.
- **Keyword search for untracked clauses.** Searching the catalog matches words, so a clause worded differently can be missed. Nonna says so when it matters.
- **USD only for cap comparisons.** Caps in other currencies are listed, never converted.
- **Clean sample contracts.** Extraction is built around the fictional samples. Real contracts with scanned pages, unusual numbering, or heavy redaction will need more work.
- **Nonna doesn't decide which term controls.** When an SOW and MSA conflict, she shows both and leaves the legal call to the attorney.
- **No login yet.** There's one demo user, so this isn't ready for a real team without authentication and access controls.
- **Can't add a clause Nonna missed.** Corrections fix values that were found. Adding a clause extraction missed entirely isn't built yet.

## Later

- Drafting a new SOW from a vendor's history, with each clause labeled verbatim, adapted, or new
- Tracking more terms with values (term length, auto-renewal, termination notice, confidentiality duration, insurance)
- Expiration and renewal deadline tracking
- A company playbook to compare each vendor's terms against your standard positions
- An "as amended" view that shows a contract as it reads today
- Counterparty one-page summary export
- [Too Many Cooks](../too_many_cooks/), the full drift detector built on Nonna's history
