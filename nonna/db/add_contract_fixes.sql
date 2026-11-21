-- Fixing upload mistakes: a log of every fix to a contract's details (title, type, date,
-- vendor, the contract it falls under) and every upload deleted by mistake.
-- Safe to run more than once. Run with:
--   psql al_dente -f nonna/db/add_contract_fixes.sql
--
-- Append-only, like the rest of Nonna's records. It keeps the contract's title as text, so
-- the record survives even when the upload itself was deleted.

BEGIN;

CREATE TABLE IF NOT EXISTS contract_fixes (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    counterparty_id  BIGINT NOT NULL REFERENCES counterparties (id) ON DELETE CASCADE,
    contract_id      BIGINT,          -- no foreign key on purpose: a deleted upload keeps its record
    contract_title   TEXT NOT NULL,
    action           TEXT NOT NULL CHECK (action IN ('edited', 'moved_in', 'moved_out', 'deleted')),
    changes          JSONB,           -- {"Type": {"from": "SOW", "to": "MSA"}, ...}
    note             TEXT NOT NULL CHECK (btrim(note) <> ''),   -- why, in the attorney's words
    changed_by       TEXT NOT NULL,
    changed_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS contract_fixes_counterparty_idx ON contract_fixes (counterparty_id);

-- Never edited or deleted. Deleting the whole vendor still removes its log.
CREATE OR REPLACE FUNCTION protect_contract_fixes() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' AND NOT EXISTS (SELECT 1 FROM counterparties WHERE id = OLD.counterparty_id) THEN
        RETURN OLD;  -- the vendor itself is being deleted
    END IF;
    RAISE EXCEPTION 'contract_fixes is append-only. Add a new fix instead of changing an old one.';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS contract_fixes_append_only ON contract_fixes;
CREATE TRIGGER contract_fixes_append_only
    BEFORE UPDATE OR DELETE ON contract_fixes
    FOR EACH ROW EXECUTE FUNCTION protect_contract_fixes();

COMMIT;