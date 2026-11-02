# Nonna: Database Architecture

Nonna is a counterparty clause library. At its base layer it is a Postgres database that remembers what a legal team agreed to with each counterparty, so new contracts start consistent and drift can be caught.

## Core decision: store both full clause text and key terms

| What | Why we need it |
|---|---|
| Full clause text | Source of truth. Attorneys pull it when drafting. Lets a human check whether extraction was right. Keeps nuance like carve-outs and exceptions. |
| Key terms (structured values) | Makes exact comparison possible ($100K vs $50K, net 45 vs net 30). Powers search and Too Many Cooks drift detection. |

Every key term links back to the exact clause and section it came from, which creates an audit trail.

## Mental model

```
Counterparty (e.g. a CDMO)
└── Counterparty entities (the specific legal entities that sign)
    └── Contracts (NDA, MSA, SOW, amendment, change order)
        └── Clauses (full text of each relevant section)
            ├── Clause terms (structured values extracted from the clause)
            └── Review decisions (who approved what, when, and why)
```

Version history is not stored as a separate table. It emerges from lining up the same clause type across a counterparty's contracts in order of effective date.

## Tables

### `counterparties`
The business relationship as the legal team thinks about it ("the CDMO we work with").

| Column | Notes |
|---|---|
| `id` | Primary key |
| `name` | Common name used by the team |
| `created_at` | Timestamp |

### `counterparty_entities`
The specific legal entities that actually sign contracts. One counterparty can have several (a parent company, a US subsidiary, a Swiss sales entity).

| Column | Notes |
|---|---|
| `id` | Primary key |
| `counterparty_id` | Which relationship this entity belongs to |
| `legal_name` | Exact name as written in the contract |
| `jurisdiction` | Where the entity is organized |

### `contracts`

| Column | Notes |
|---|---|
| `id` | Primary key |
| `counterparty_id` | Which relationship (for fast "show me everything with X" queries) |
| `entity_id` | Which specific legal entity signed this contract |
| `contract_type` | NDA, MSA, SOW, amendment, change_order |
| `title` | Contract title |
| `effective_date` | Used to order version history |
| `expiration_date` | Nullable |
| `status` | active, expired, superseded |
| `parent_contract_id` | Nullable. A SOW points to its MSA. |
| `amends_contract_id` | Nullable. An amendment points to the contract it changes. |
| `file_path` | Where the original PDF or DOCX lives in file storage |
| `file_hash` | Detects duplicate uploads |
| `full_text` | Extracted text of the whole contract |
| `uploaded_by`, `uploaded_at` | Who added it and when |

### `clauses`

| Column | Notes |
|---|---|
| `id` | Primary key |
| `contract_id` | Which contract this clause is in |
| `clause_type` | liability_cap, indemnification, payment_terms, governing_law |
| `section_number` | For example "12.2" |
| `heading` | Section heading as written |
| `full_text` | Full clause language |
| `start_offset`, `end_offset` | Character positions in the contract, used for highlighting in the UI |
| `presence` | present, absent, incorporated_by_reference |
| `extraction_method` | deterministic, llm, or manual (entered by a person) |
| `confidence` | Nullable, mainly for LLM extractions |
| `review_status` | pending, approved, rejected, corrected |

### `clause_terms`
Structured values pulled from a clause. Typed columns keep comparisons exact.

| Column | Notes |
|---|---|
| `id` | Primary key |
| `clause_id` | Which clause this came from |
| `term_key` | For example cap_amount, cap_basis, net_days, jurisdiction, is_mutual |
| `value_numeric` | For amounts and day counts |
| `value_text` | For text values |
| `value_bool` | For yes/no values |
| `value_date` | For dates |
| `unit` | For example USD, days |

Example terms:

| Clause type | term_key | Value |
|---|---|---|
| liability_cap | cap_amount | 100000 USD |
| liability_cap | cap_basis | fees paid in prior 12 months |
| payment_terms | net_days | 45 days |
| governing_law | jurisdiction | New York |
| indemnification | is_mutual | true |
| indemnification | covers_ip_infringement | true |

### `review_decisions`
Append-only. Rows are never edited or deleted, so this table is the decision history.

| Column | Notes |
|---|---|
| `id` | Primary key |
| `clause_id` | Which clause was reviewed |
| `action` | approved, rejected, corrected, approved_change |
| `note` | Why (required for approved_change) |
| `reviewer` | Who made the decision |
| `created_at` | When |

### `counterparty_positions`
The current agreed baseline for each clause type with each counterparty. Too Many Cooks compares new contracts against this table.

| Column | Notes |
|---|---|
| `id` | Primary key |
| `counterparty_id` | Which relationship |
| `clause_type` | Which clause type |
| `contract_type_scope` | Which contract types this baseline applies to (for example MSA and amendments, not NDAs) |
| `baseline_clause_id` | The clause that represents the agreed position |
| `set_by`, `set_at`, `note` | Who moved the baseline, when, and why |
| `superseded_at` | Null for the current position. Set when a newer position replaces it, so the history of baselines is kept. |

Only one current position can exist per counterparty, clause type, and scope.

## Example: one counterparty, three contracts

| Contract | Liability cap | Governing law | Payment terms | Indemnification |
|---|---|---|---|---|
| NDA (2022) | absent | present | absent | absent or limited |
| MSA (2023) | $100K | New York | net 45 | mutual |
| SOW #1 (2024), parent = MSA | incorporated by reference | incorporated by reference | milestone based, net 30 (overrides MSA) | incorporated by reference |

## Rules that matter

- **Compare like with like.** An NDA without a cap is not drift from an MSA cap. Positions are scoped by contract type.
- **Hierarchy and precedence.** A SOW can override its MSA on some terms. An amendment supersedes what it amends. The effective position depends on the contract family tree, not only the newest date.
- **Absent is not the same as not extracted.** A missing cap is the most dangerous drift, so "checked and not present" is stored as a real row, separate from "not reviewed yet."
- **Human review gates the baseline.** LLM-extracted terms stay pending and never become a counterparty position until an attorney approves them.

## How the database enforces these rules

The schema in [`db/schema.sql`](db/schema.sql) enforces the rules above directly, so bad data is rejected by the database and not only by application code:

- A contract's signing entity must belong to the same counterparty.
- Duplicate uploads are rejected by file hash.
- A clause marked present must have its text.
- Each clause term stores exactly one value.
- An `approved_change` decision must include a note.
- Review decisions cannot be edited or deleted (append-only trigger).
- A clause can only become a counterparty position if it was approved or corrected by a reviewer, belongs to that counterparty, and matches the clause type.

## File storage

- Original PDFs and DOCX files live in file storage, not in the database. MVP: a local folder. Later: object storage (for example Amazon S3, Google Cloud Storage, or Azure Blob).
- Postgres stores only the file path and a hash of the file.
- Extracted text lives in Postgres so search and highlighting are easy.

## Data note

All counterparties in this repository are fictional, built on public contract text from SEC EDGAR and CUAD. See [`data/`](../data/) for details.