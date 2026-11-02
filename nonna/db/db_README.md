# Nonna database

PostgreSQL schema, seed data, and example queries for Nonna. See [../architecture.md](../architecture.md) for the design.

| File | What it does |
|---|---|
| `schema.sql` | Creates all tables, constraints, indexes, and triggers. Rerunnable: drops and recreates everything. |
| `seed.sql` | Loads a small fictional contract history for testing. |
| `queries.sql` | The core questions Nonna must answer, used to check that the schema works. |

## Run it

```bash
createdb al_dente
psql al_dente -f nonna/db/schema.sql
psql al_dente -f nonna/db/seed.sql
psql al_dente -f nonna/db/queries.sql
```

## Seed data story

All companies are fictional and clause text is placeholder language written for testing.

- **Castellan Bioprocessing** (manufacturing partner): 2022 NDA with the Swiss parent, 2023 MSA with the US subsidiary, 2024 SOW #1, 2024 Amendment 1 raising the liability cap from $1M to $2M, and a 2025 SOW #2 with net 60 payment terms still pending review.
- **Halvorsen Scientific** (newer vendor): one 2024 MSA with no liability cap.

## What the queries show

1. Liability cap history for one counterparty, including absent and incorporated-by-reference rows
2. Current agreed positions, with the value and source document
3. MSAs without a liability cap, split into "confirmed absent" and "not extracted yet"
4. The decision log with reviewer notes
5. The review queue of pending extractions
6. A preview of Too Many Cooks: pending terms that differ from the current baseline (catches SOW #2's net 60 against the net 30 baseline)
