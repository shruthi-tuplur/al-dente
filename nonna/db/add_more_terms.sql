-- Lets Nonna track three more key terms (no data is lost):
-- termination for convenience, how long confidentiality lasts, and insurance minimums.
-- Safe to run more than once. Run with:
--   psql al_dente -f nonna/db/add_more_terms.sql

BEGIN;

ALTER TABLE clauses DROP CONSTRAINT IF EXISTS clauses_clause_type_check;
ALTER TABLE clauses ADD CONSTRAINT clauses_clause_type_check
    CHECK (clause_type IN ('liability_cap', 'indemnification', 'payment_terms', 'governing_law',
                           'term_renewal', 'termination_convenience', 'confidentiality', 'insurance'));

-- The new terms get agreed baselines per vendor too, so a new contract that drifts gets caught
ALTER TABLE counterparty_positions DROP CONSTRAINT IF EXISTS counterparty_positions_clause_type_check;
ALTER TABLE counterparty_positions ADD CONSTRAINT counterparty_positions_clause_type_check
    CHECK (clause_type IN ('liability_cap', 'indemnification', 'payment_terms', 'governing_law',
                           'termination_convenience', 'confidentiality', 'insurance'));

COMMIT;