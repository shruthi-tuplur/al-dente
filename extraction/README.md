# Extraction

The shared term extraction pipeline used by [Nonna](../nonna/) and [Too Many Cooks](../too_many_cooks/).

## Clause types (MVP)

| Clause | Method | Human review |
|---|---|---|
| Liability cap | Deterministic | Optional |
| Governing law | Deterministic | Optional |
| Payment terms | Deterministic | Optional |
| Indemnification | LLM | Required |

## Why two methods

Exact values like dollar amounts, payment days, and governing law have one correct answer, so they are extracted with deterministic code that is predictable and easy to test. Clause language like indemnification varies widely in wording, so an LLM extracts it and an attorney reviews the result before it is stored.

## Output

Every extraction returns the clause type, the extracted value, the source text it came from, and the method used, so any result can be traced back to the contract.
