-- GC exceptions: when the GC signs off on a term that's off Aurelia's playbook.
-- Safe to run more than once. Run with:
--   psql al_dente -f nonna/db/add_playbook_exceptions.sql
--
-- An exception is a permanent record. It can't be edited or deleted, only withdrawn
-- once (with who, when, and why), so the history of every sign-off survives.

BEGIN;

CREATE TABLE IF NOT EXISTS playbook_exceptions (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    clause_id           BIGINT NOT NULL REFERENCES clauses (id),
    approved_value      TEXT NOT NULL,   -- the term the GC approved, like "$500,000"
    approved_by         TEXT NOT NULL,   -- the GC who signed off
    approved_on         DATE NOT NULL,
    note                TEXT NOT NULL CHECK (btrim(note) <> ''),   -- why the GC said yes
    recorded_by         TEXT NOT NULL,   -- the attorney who entered it in Nonna
    recorded_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    review_decision_id  BIGINT REFERENCES review_decisions (id),   -- the approval it came with, if any
    withdrawn_at        TIMESTAMPTZ,
    withdrawn_by        TEXT,
    withdraw_note       TEXT,
    CHECK ((withdrawn_at IS NULL) = (withdrawn_by IS NULL)
           AND (withdrawn_at IS NULL) = (withdraw_note IS NULL))
);

-- Only one active exception per clause
CREATE UNIQUE INDEX IF NOT EXISTS playbook_exceptions_active
    ON playbook_exceptions (clause_id) WHERE withdrawn_at IS NULL;

-- Never deleted or edited. The only change allowed is withdrawing it, once.
CREATE OR REPLACE FUNCTION protect_playbook_exceptions() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'GC exceptions are a permanent record. Withdraw it instead of deleting it.';
    END IF;
    IF OLD.withdrawn_at IS NOT NULL THEN
        RAISE EXCEPTION 'This exception was already withdrawn.';
    END IF;
    IF (NEW.clause_id, NEW.approved_value, NEW.approved_by, NEW.approved_on, NEW.note,
        NEW.recorded_by, NEW.recorded_at, NEW.review_decision_id)
       IS DISTINCT FROM
       (OLD.clause_id, OLD.approved_value, OLD.approved_by, OLD.approved_on, OLD.note,
        OLD.recorded_by, OLD.recorded_at, OLD.review_decision_id) THEN
        RAISE EXCEPTION 'GC exceptions can''t be edited. Withdraw it and record a new one.';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS playbook_exceptions_permanent ON playbook_exceptions;
CREATE TRIGGER playbook_exceptions_permanent
    BEFORE UPDATE OR DELETE ON playbook_exceptions
    FOR EACH ROW EXECUTE FUNCTION protect_playbook_exceptions();

COMMIT;