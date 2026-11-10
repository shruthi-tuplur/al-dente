# Nonna

A counterparty clause library. Nonna remembers what a legal team agreed to with each counterparty, the way a nonna never forgets a recipe.

<!-- Add a screenshot or GIF of the review screen here, e.g. ![Nonna review screen](docs/review.png) -->

## Problem

Legal teams negotiate with the same companies over and over, but there is often no easy way to see what was previously agreed with a specific counterparty. Most clause libraries store a company's standard positions, not the history of what was actually negotiated with each counterparty. Teams without CLM API access have even less visibility.

## How it works

1. Upload an executed contract (PDF or DOCX, manual upload, no CLM integration required).
2. Nonna identifies the parties, contract type, and effective date, matches the counterparty to an existing relationship (or proposes a new one), and suggests a parent contract (for example, a SOW under its MSA). The attorney confirms before anything is saved.
3. Key terms are extracted: deterministic code for exact values, Claude only for indemnification language.
4. Every extracted clause is saved as **pending**. An attorney approves, corrects, or rejects it next to the source text before it counts.
5. Approved terms become part of the counterparty's history: counterparty → contract → clause → version, with a log of who decided what and why.
6. Attorneys ask questions in plain English ("What's our liability cap with Aurelia?") and Nonna answers from the database.

## Features

- **Ask Nonna:** a chat that answers questions using tool calling. The model calls predefined lookup functions on the database. It never writes free-form SQL and never answers numbers from memory.
- **Contract intake:** upload, party and date detection, counterparty matching, and parent contract suggestions, all confirmed by a person.
- **Review queue:** approve, correct, or reject extracted clauses next to the source text, one at a time or in bulk.
- **Counterparty library:** current agreed positions per clause type, full clause history, and the source contract behind every value.
- **Full contract view:** open the original document behind any clause.

## Design choices

- Deterministic extraction for exact values (dollar amounts, dates, governing law).
- LLM extraction for messier clause language (indemnification), always reviewed by a human.
- A clause that can't be found is never recorded as absent, because a missing clause is something a person should check.
- The chat can only read data through predefined functions, so answers are traceable to source contracts.
- Stores both full clause text and structured key terms, linked together for an audit trail.
- Postgres database (with constraints that only let approved or corrected clauses become a counterparty position) designed so [Too Many Cooks](../too_many_cooks/) can compare new contracts against it.

## MVP scope

- Clause types: liability cap, governing law, payment terms, indemnification
- Upload, extract, store, view history, approve changes
- Chat over the counterparty library

## Run it locally

From the repo root, after following [Getting started](../README.md#getting-started):

```bash
# Backend (FastAPI) on http://127.0.0.1:8000
uv run uvicorn nonna.api:app --reload

# Frontend (React + Vite) in a second terminal
cd nonna/web
npm install
npm run dev
```

The frontend forwards `/api/...` calls to the backend, so open the URL Vite prints and you're in.

See [architecture.md](architecture.md) for the database design and [user-flows.md](user-flows.md) for how attorneys use Nonna.

## Results

_Coming soon: extraction accuracy per clause type._

## Limitations

_Coming soon._

## Later

Drafting suggestions, more clause types (term and termination, IP ownership), counterparty summary export.
