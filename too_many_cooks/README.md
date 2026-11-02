# Too Many Cooks

A contract drift detector. Too many cooks spoil the broth: drift usually happens when many different people touch the same counterparty relationship over time (new attorneys, different negotiators, old templates).

## Problem

Negotiated terms can quietly change between agreements with the same counterparty. If the last three agreements had a $100K liability cap and the new one says $50K, and no one catches it, the team loses protection it already negotiated.

## How it works

1. A new contract is uploaded and its key terms are extracted with the shared [`extraction`](../extraction/) pipeline.
2. Terms are compared against that counterparty's history in [Nonna](../nonna/).
3. Differences are flagged with the old value, new value, and source contract.
4. An attorney marks each flag as accidental drift (fix it) or approved (intentional, with a note). Approved changes update Nonna so the tool does not keep crying wolf.

## Design choices

- Exact comparison for numbers, dates, and defined values.
- Semantic comparison (LLM) for clause wording, with a confidence score.
- Human review on every flag.
- Approved-drift log so alerts stay meaningful.

## Evaluation

Known drifts are planted into contract versions, and the tool is measured on detection rate and false positives.

_Results coming soon._

## Status

Planned. Depends on Nonna.
