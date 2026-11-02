# Nonna

A counterparty clause library. Nonna remembers what a legal team agreed to with each counterparty, the way a nonna never forgets a recipe.

## Problem

Legal teams negotiate with the same companies over and over, but there is often no easy way to see what was previously agreed with a specific counterparty. Most clause libraries store a company's standard positions, not the history of what was actually negotiated with each counterparty. Teams without CLM API access have even less visibility.

## How it works

1. Upload executed contracts (manual upload, no CLM integration required).
2. Key terms are extracted using the shared [`extraction`](../extraction/) pipeline.
3. Terms are stored per counterparty with version history: counterparty → contract → clause → version.
4. When drafting, an attorney can pull the language previously used with that counterparty.
5. Attorneys can log intentional changes as approved, with a note explaining why, creating a decision history per counterparty.

## Design choices

- Deterministic extraction for exact values (dollar amounts, dates, governing law).
- LLM extraction for messier clause language (indemnification), always reviewed by a human.
- Stores both full clause text and structured key terms, linked together for an audit trail.
- Postgres database designed so [Too Many Cooks](../too_many_cooks/) can compare new contracts against it.

See [architecture.md](architecture.md) for the full database design.

## MVP scope

- Clause types: liability cap, governing law, payment terms, indemnification
- Single counterparty view
- Upload, extract, store, view history, approve changes

## Results

_Coming soon: extraction accuracy per clause type._

## Limitations

_Coming soon._

## Later

Drafting suggestions, more clause types (term and termination, IP ownership), counterparty summary export.
