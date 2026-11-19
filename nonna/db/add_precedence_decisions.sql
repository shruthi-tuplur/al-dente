-- Which term controls: the attorney's call when an SOW and its MSA disagree on a term.
-- Safe to run more than once. Run with:
--   psql al_dente -f nonna/db/add_precedence_decisions.sql
--
-- Append-only, like review_decisions: changing your mind adds a new call,
-- and the old one stays in the history.

BEGIN;

CREATE TABLE IF NOT EXISTS precedence_decisions (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sow_clause_id  BIGINT NOT NULL REFERENCES clauses (id),   -- the SOW's (or change order's) term
    msa_clause_id  BIGINT NOT NULL REFERENCES clauses (id),   -- the MSA term it conflicts with
    controls       TEXT NOT NULL CHECK (controls IN ('msa', 'sow')),
    sow_value      TEXT NOT NULL,   -- the two values this call was made for, like "Net 60"
    msa_value      TEXT NOT NULL,
    note           TEXT NOT NULL CHECK (btrim(note) <> ''),   -- why, in the attorney's words
    decided_by     TEXT NOT NULL,
    decided_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS precedence_decisions_sow_clause_idx ON precedence_decisions (sow_clause_id);

CREATE OR REPLACE FUNCTION prevent_precedence_decision_changes() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'precedence_decisions is append-only. Add a new call instead of changing an old one.';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS precedence_decisions_append_only ON precedence_decisions;
CREATE TRIGGER precedence_decisions_append_only
    BEFORE UPDATE OR DELETE ON precedence_decisions
    FOR EACH ROW EXECUTE FUNCTION prevent_precedence_decision_changes();

COMMIT;