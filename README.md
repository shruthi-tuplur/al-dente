# Al Dente

A library of legal AI tools built from real legal team bottlenecks, designed to be clean, secure, and reliable enough for a whole legal team to trust.

## Why this exists

Legal teams negotiate with the same counterparties over and over, and attorneys are increasingly building their own AI tools to keep up. Those tools often work for one person but are not ready for a team: inconsistent results, secrets in code, confidential data sent where it should not go, and no way to measure accuracy.

Al Dente takes real legal bottlenecks and "spaghetti" (messy ideas and messy code) and turns them into tools that are cooked just right.

## The tools

| Tool | What it does | Status |
|---|---|---|
| [Nonna](nonna/) | Counterparty clause library. Remembers what a legal team agreed to with each counterparty across MSAs, SOWs, and amendments, with attorney review, corrections, a drift guard, an append-only decision log, a review dashboard, a full clause catalog, and a chat that can answer questions across every vendor. | Built, evals in progress |
| [Too Many Cooks](too_many_cooks/) | Contract drift detector. Flags when a new contract quietly drifts from what was previously negotiated with that counterparty. Builds on Nonna. | An early version runs inside Nonna (drift guard and Matches / Different review). Full tool planned. |
| [Despaghettify](despaghettify/) | Code audit tool. Reviews attorney-built scripts and explains, in plain English, how to make them secure and team-ready. | Planned |

Nonna and Too Many Cooks share one extraction pipeline. It currently lives in [`nonna/extraction.py`](nonna/extraction.py) and will move into [`extraction/`](extraction/) when Too Many Cooks is built.

## Design principles

- **Start with a real problem.** Every tool comes from a bottleneck observed in actual legal work.
- **Start small.** Ship an MVP, measure it, then grow.
- **AI where it helps, deterministic code where it must be exact.** Dollar amounts, dates, and governing law are extracted with deterministic code. Messier clause language uses an LLM.
- **Humans review the output.** Every extraction and every drift flag is reviewed by an attorney before it counts.
- **Data minimization.** Each task uses only the data it needs.
- **Measure results.** Each tool has evals with clear metrics, reported in its README.
- **No CLM API required.** Manual upload is a supported path, because many legal teams do not have API access to their contract management system.

## Data

All contracts and companies in this repository are **fictional**, written for this project to simulate a real negotiation history: an in-house legal team at a fictional biotech (Aurelia Therapeutics) and its vendors (Lucca Biologics, Castellan Bioprocessing, and others), including amendments, SOWs, and planted drifts. Any resemblance to a real company is unintentional.

No confidential, client, or employer data is used anywhere in this repository.

Public contract sources are planned for evaluation on real-world documents:

- [SEC EDGAR](https://www.sec.gov/edgar) contract exhibits
- [CUAD](https://www.atticusprojectai.org/cuad) (Contract Understanding Atticus Dataset)

See [`data/`](data/) for details.

## Repository layout

```
al-dente/
├── extraction/        # Future home of the shared extraction pipeline (see nonna/extraction.py)
├── nonna/             # Counterparty clause library (FastAPI backend, React frontend, Postgres schema)
├── too_many_cooks/    # Contract drift detector
├── despaghettify/     # Code audit tool for attorney-built scripts
├── data/              # Sample contracts, synthetic versions, answer keys
├── evals/             # Accuracy and drift detection evaluations
└── tests/             # pytest test suite
```

## Getting started

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), PostgreSQL, and Node.js.

```bash
git clone https://github.com/shruthi-tuplur/al-dente.git
cd al-dente
uv sync                          # install Python dependencies
cp .env.example .env             # then add your own API key and database URL

createdb al_dente
psql al_dente -f nonna/db/schema.sql
psql al_dente -f nonna/db/seed.sql
psql al_dente -f nonna/db/seed_more_vendors.sql

uv run pytest                    # run the test suite
```

To run Nonna locally, see [nonna/README.md](nonna/README.md#run-it-locally).

API keys and database credentials are read from environment variables only and are never committed.

## Stack

Python, FastAPI, SQLAlchemy, PostgreSQL, React, TypeScript, Vite, pytest, Claude API.

## Roadmap

- [x] Shared extraction pipeline: liability cap, governing law, payment terms, indemnification
- [x] Nonna: upload with attorney-confirmed intake, extraction, review, and version history across MSAs, SOWs, and amendments
- [x] Ask Nonna: chat that answers questions through read-only database lookups, with sourced cards
- [x] Drift guard: changes to agreed terms require an intentional approval with a note
- [x] Corrections: attorneys fix extracted values, with the original kept in an append-only log
- [x] Review dashboard: pending terms shown next to what's agreed, marked Matches or Different
- [x] Library: every vendor, contract, and clause, including a full verbatim clause catalog by topic
- [x] Questions across all vendors: compare an agreed term across every counterparty, with exact filtering in code
- [ ] Nonna evals: extraction accuracy per clause type and a hallucination test set
- [ ] Too Many Cooks MVP: side-by-side drift report with approve and reject flow
- [ ] Too Many Cooks evals: detection rate and false positives on planted drifts
- [ ] Despaghettify MVP: security and reliability checks for Python scripts, plain-English report
- [ ] Despaghettify case study: before and after on early versions of Nonna and Too Many Cooks

## About

Built by Shruthi Tuplur, an engineer with a legal background (paralegal certificate, law firm experience, MS in Computer Science, and legal engineering experience on an in-house biotech legal team).

[LinkedIn]([https://www.linkedin.com/in/YOUR-HANDLE](https://www.linkedin.com/in/shruthi-tuplur/)) 
