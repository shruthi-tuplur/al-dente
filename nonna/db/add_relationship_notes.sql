-- Relationship notes: what the team knows about a vendor that isn't in any contract.
-- "They always fight us on IP." "Business owner is in CMC." "Renegotiating in Q2."
-- Safe to run more than once. Run with:
--   psql al_dente -f nonna/db/add_relationship_notes.sql
--
-- Notes are never edited or deleted. Retire one by archiving it (once, with who and when),
-- then add a new one, so the history of what the team knew survives.

BEGIN;

CREATE TABLE IF NOT EXISTS relationship_notes (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    counterparty_id  BIGINT NOT NULL REFERENCES counterparties (id) ON DELETE CASCADE,
    topic            TEXT NOT NULL DEFAULT 'other'
                     CHECK (topic IN ('negotiation', 'people', 'timing', 'other')),
    body             TEXT NOT NULL CHECK (btrim(body) <> '' AND length(body) <= 1000),
    written_by       TEXT NOT NULL,
    written_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at      TIMESTAMPTZ,
    archived_by      TEXT,
    CHECK ((archived_at IS NULL) = (archived_by IS NULL))
);

CREATE INDEX IF NOT EXISTS relationship_notes_counterparty_idx ON relationship_notes (counterparty_id);

-- The only change allowed is archiving a note, once. Deleting the vendor still removes its notes.
CREATE OR REPLACE FUNCTION protect_relationship_notes() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF NOT EXISTS (SELECT 1 FROM counterparties WHERE id = OLD.counterparty_id) THEN
            RETURN OLD;  -- the vendor itself is being deleted
        END IF;
        RAISE EXCEPTION 'Relationship notes are kept for the record. Archive it instead of deleting it.';
    END IF;
    IF OLD.archived_at IS NOT NULL THEN
        RAISE EXCEPTION 'This note was already archived.';
    END IF;
    IF (NEW.counterparty_id, NEW.topic, NEW.body, NEW.written_by, NEW.written_at)
       IS DISTINCT FROM
       (OLD.counterparty_id, OLD.topic, OLD.body, OLD.written_by, OLD.written_at) THEN
        RAISE EXCEPTION 'Notes can''t be edited. Archive it and add a new one.';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS relationship_notes_kept ON relationship_notes;
CREATE TRIGGER relationship_notes_kept
    BEFORE UPDATE OR DELETE ON relationship_notes
    FOR EACH ROW EXECUTE FUNCTION protect_relationship_notes();

COMMIT;