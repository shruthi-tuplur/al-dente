# Al Dente

A library of legal AI tools built from real legal team bottlenecks, designed to be clean, secure, and reliable enough for a whole legal team to trust.

## Why this exists

Legal teams negotiate with the same counterparties over and over, and attorneys are increasingly building their own AI tools to keep up. Those tools often work for one person but are not ready for a team: inconsistent results, secrets in code, confidential data sent where it should not go, and no way to measure accuracy.

Al Dente takes real legal bottlenecks and "spaghetti" (messy ideas and messy code) and turns them into tools that are cooked just right.

## The tools

| Tool | What it does | Status |
|---|---|---|
| [Nonna](nonna/) | Counterparty clause library. Remembers what a legal team agreed to with each counterparty, with version history, attorney review, and a log of approved changes. | MVP built, evals in progress |
| [Too Many Cooks](too_many_cooks/) | Contract drift detector. Flags when a new contract quietly drifts from what was previously negotiated with that counterparty. Builds on Nonna. | Planned |
| [Despaghettify](despaghettify/) | Code audit tool. Reviews attorney-built scripts and explains, in plain English, how to make them secure and team-ready. | Planned |

Nonna and Too Many Cooks share one extraction pipeline. It currently lives in [`nonna/extraction.py`](nonna/extraction.py) and will move into [`extraction/`](extraction/) when Too Many Cooks is built.

## Design principles

- **Start with a real problem.** Every tool comes from a bottleneck observed in actual legal work.
- **Start small.** Ship an MVP, measure it, then grow.
- **AI where it helps, deterministic code where it must be exact.** Dollar amounts, dates, and governing law are extracted with deterministic code. Messier clause language uses an LLM.
- **Humans review the output.** Every LLM extraction and every drift flag is reviewed by an attorney before it counts.
- **Data minimization.** Each task uses only the data it needs.
- **Measure results.** Each tool has evals with clear metrics, reported in its README.
- **No CLM API required.** Manual upload is a supported path, because many legal teams do not have API access to their contract management system.

## Data

Public sources only:

- [SEC EDGAR](https://www.sec.gov/edgar) contract exhibits
- [CUAD](https://www.atticusprojectai.org/cuad) (Contract Understanding Atticus Dataset)

To simulate a negotiation history with a single counterparty, real public contract text is used as a base, counterparty names are fictionalized, and later versions and planted drifts are generated synthetically. Any resemblance to a real company is unintentional. No confidential or employer data is used anywhere in this repository. See [`data/`](data/) for details.

## Repository layout

```
al-dente/
├── extraction/        # Future home of the shared extraction pipeline (see nonna/extraction.py)
├── nonna/             # Counterparty clause library (FastAPI backend, React frontend, Postgres schema)
├── too_many_cooks/    # Contract drift detector
├── despaghettify/     # Code audit tool for attorney-built scripts
├── data/              # Base contracts, synthetic versions, answer keys
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

uv run pytest                    # run the test suite
```

To run Nonna locally, see [nonna/README.md](nonna/README.md#run-it-locally).

API keys and database credentials are read from environment variables only and are never committed.

## Stack

Python, FastAPI, SQLAlchemy, PostgreSQL, React, TypeScript, Vite, pytest, Claude API.

## Roadmap

- [x] Shared extraction pipeline: liability cap, governing law, payment terms, indemnification
- [x] Nonna MVP: upload, extract, store, view history, approve changes for a single counterparty
- [x] Ask Nonna: chat that answers questions through predefined database lookups
- [ ] Nonna evals: extraction accuracy per clause type
- [ ] Too Many Cooks MVP: side-by-side drift report with approve and reject flow
- [ ] Too Many Cooks evals: detection rate and false positives on planted drifts
- [ ] Despaghettify MVP: security and reliability checks for Python scripts, plain-English report
- [ ] Despaghettify case study: before and after on early versions of Nonna and Too Many Cooks

## About

Built by Shruthi, an engineer with a legal background (paralegal certificate, law firm experience, MS in Computer Science, and legal engineering experience on an in-house biotech legal team).

<!-- Add your LinkedIn / portfolio link here -->
