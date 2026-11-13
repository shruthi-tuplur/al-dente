-- Nonna database schema (PostgreSQL 16+)
-- See ../architecture.md for the design behind these tables.
--
-- Run with:
--   psql al_dente -f nonna/db/schema.sql
--
-- Rerunnable: drops and recreates every Nonna table. Do not run against
-- a database with data you want to keep.

BEGIN;

-- Hide "does not exist, skipping" notices on a fresh database
SET LOCAL client_min_messages TO warning;

DROP TABLE IF EXISTS contract_sections CASCADE;

DROP TABLE IF EXISTS counterparty_positions CASCADE;
DROP TABLE IF EXISTS review_decisions CASCADE;
DROP TABLE IF EXISTS clause_terms CASCADE;
DROP TABLE IF EXISTS clauses CASCADE;
DROP TABLE IF EXISTS contracts CASCADE;
DROP TABLE IF EXISTS counterparty_entities CASCADE;
DROP TABLE IF EXISTS counterparties CASCADE;
DROP FUNCTION IF EXISTS prevent_review_decision_changes() CASCADE;
DROP FUNCTION IF EXISTS check_position_baseline() CASCADE;


-- ---------------------------------------------------------------------------
-- counterparties: the business relationship as the legal team thinks about it
-- ---------------------------------------------------------------------------
CREATE TABLE counterparties (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- ---------------------------------------------------------------------------
-- counterparty_entities: the specific legal entities that actually sign
-- ---------------------------------------------------------------------------
CREATE TABLE counterparty_entities (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    counterparty_id  BIGINT NOT NULL REFERENCES counterparties (id) ON DELETE CASCADE,
    legal_name       TEXT NOT NULL,
    jurisdiction     TEXT,

    UNIQUE (counterparty_id, legal_name),
    -- Lets contracts prove their entity belongs to their counterparty (see below)
    UNIQUE (id, counterparty_id)
);


-- ---------------------------------------------------------------------------
-- contracts
-- ---------------------------------------------------------------------------
CREATE TABLE contracts (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    counterparty_id     BIGINT NOT NULL REFERENCES counterparties (id) ON DELETE CASCADE,
    entity_id           BIGINT NOT NULL,
    contract_type       TEXT NOT NULL
                        CHECK (contract_type IN ('NDA', 'MSA', 'SOW', 'amendment', 'change_order')),
    title               TEXT NOT NULL,
    effective_date      DATE NOT NULL,
    expiration_date     DATE,
    status              TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'expired', 'superseded')),
    parent_contract_id  BIGINT REFERENCES contracts (id),   -- a SOW points to its MSA
    amends_contract_id  BIGINT REFERENCES contracts (id),   -- an amendment points to what it changes
    file_path           TEXT NOT NULL,
    file_hash           TEXT NOT NULL UNIQUE,               -- catches duplicate uploads
    full_text           TEXT,
    uploaded_by         TEXT NOT NULL,
    uploaded_at         TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- The signing entity must belong to the same counterparty as the contract
    FOREIGN KEY (entity_id, counterparty_id)
        REFERENCES counterparty_entities (id, counterparty_id),

    CHECK (expiration_date IS NULL OR expiration_date >= effective_date),
    CHECK (parent_contract_id IS NULL OR parent_contract_id <> id),
    CHECK (amends_contract_id IS NULL OR amends_contract_id <> id),
    -- Only amendments amend things
    CHECK (amends_contract_id IS NULL OR contract_type = 'amendment')
);

CREATE INDEX contracts_counterparty_date_idx ON contracts (counterparty_id, effective_date);
CREATE INDEX contracts_parent_idx ON contracts (parent_contract_id);
CREATE INDEX contracts_amends_idx ON contracts (amends_contract_id);


-- ---------------------------------------------------------------------------
-- clauses: full clause text, one row per clause type per contract
--
-- No row          = not extracted yet
-- presence absent = checked, and the clause is not in the contract
-- ---------------------------------------------------------------------------
CREATE TABLE clauses (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    contract_id        BIGINT NOT NULL REFERENCES contracts (id) ON DELETE CASCADE,
    clause_type        TEXT NOT NULL
                       CHECK (clause_type IN ('liability_cap', 'indemnification',
                                              'payment_terms', 'governing_law',
                                              'term_renewal')),
    section_number     TEXT,
    heading            TEXT,
    full_text          TEXT,
    start_offset       INTEGER,
    end_offset         INTEGER,
    presence           TEXT NOT NULL
                       CHECK (presence IN ('present', 'absent', 'incorporated_by_reference')),
    extraction_method  TEXT NOT NULL
                       CHECK (extraction_method IN ('deterministic', 'llm', 'manual')),
    confidence         NUMERIC(4, 3) CHECK (confidence BETWEEN 0 AND 1),
    review_status      TEXT NOT NULL DEFAULT 'pending'
                       CHECK (review_status IN ('pending', 'approved', 'rejected', 'corrected')),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (contract_id, clause_type),

    -- A present clause must have its text
    CHECK (presence <> 'present' OR full_text IS NOT NULL),
    -- Offsets come in pairs and point forward
    CHECK ((start_offset IS NULL) = (end_offset IS NULL)),
    CHECK (start_offset IS NULL OR (start_offset >= 0 AND end_offset > start_offset))
);

CREATE INDEX clauses_type_idx ON clauses (clause_type);
CREATE INDEX clauses_review_status_idx ON clauses (review_status);


-- ---------------------------------------------------------------------------
-- clause_terms: structured values extracted from a clause
-- Exactly one value column is filled per row, so comparisons stay exact.
-- ---------------------------------------------------------------------------
CREATE TABLE clause_terms (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    clause_id      BIGINT NOT NULL REFERENCES clauses (id) ON DELETE CASCADE,
    term_key       TEXT NOT NULL,
    value_numeric  NUMERIC,
    value_text     TEXT,
    value_bool     BOOLEAN,
    value_date     DATE,
    unit           TEXT,

    UNIQUE (clause_id, term_key),
    CHECK (num_nonnulls(value_numeric, value_text, value_bool, value_date) = 1)
);

CREATE INDEX clause_terms_key_idx ON clause_terms (term_key);


-- ---------------------------------------------------------------------------
-- review_decisions: append-only decision history
-- ---------------------------------------------------------------------------
CREATE TABLE review_decisions (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    clause_id   BIGINT NOT NULL REFERENCES clauses (id),
    action      TEXT NOT NULL
                CHECK (action IN ('approved', 'rejected', 'corrected', 'approved_change')),
        note        TEXT,
    reviewer    TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- For corrections: what the attorney changed, like
    -- {"cap_amount": {"from": "2500000", "to": "25000000"}}
    changes     JSONB,

    -- Intentional changes and corrections always need a reason
    CHECK (action NOT IN ('approved_change', 'corrected') OR (note IS NOT NULL AND btrim(note) <> '')),
    -- A correction always records what it changed
    CHECK (action <> 'corrected' OR changes IS NOT NULL)
);

CREATE INDEX review_decisions_clause_idx ON review_decisions (clause_id, created_at);

-- Enforce append-only: decisions can be added, never edited or deleted
CREATE FUNCTION prevent_review_decision_changes() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'review_decisions is append-only. Add a new decision instead of changing an old one.';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER review_decisions_append_only
    BEFORE UPDATE OR DELETE ON review_decisions
    FOR EACH ROW EXECUTE FUNCTION prevent_review_decision_changes();


-- ---------------------------------------------------------------------------
-- counterparty_positions: the agreed baseline per counterparty and clause type
-- Too Many Cooks compares new contracts against the current position.
-- Old positions are kept (superseded_at set) so the history of baselines survives.
-- ---------------------------------------------------------------------------
CREATE TABLE counterparty_positions (
    id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    counterparty_id      BIGINT NOT NULL REFERENCES counterparties (id) ON DELETE CASCADE,
    clause_type          TEXT NOT NULL
                         CHECK (clause_type IN ('liability_cap', 'indemnification',
                                                'payment_terms', 'governing_law')),
    contract_type_scope  TEXT[] NOT NULL
                         CHECK (cardinality(contract_type_scope) > 0
                                AND contract_type_scope <@ ARRAY['NDA', 'MSA', 'SOW',
                                                                 'amendment', 'change_order']),
    baseline_clause_id   BIGINT NOT NULL REFERENCES clauses (id),
    set_by               TEXT NOT NULL,
    set_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    note                 TEXT,
    superseded_at        TIMESTAMPTZ,

    CHECK (superseded_at IS NULL OR superseded_at >= set_at)
);

-- Only one current position per counterparty, clause type, and scope
CREATE UNIQUE INDEX counterparty_positions_current_idx
    ON counterparty_positions (counterparty_id, clause_type, contract_type_scope)
    WHERE superseded_at IS NULL;

-- Human review gates the baseline: a clause can only become a position if an
-- attorney approved or corrected it, and it must belong to this counterparty
-- and match the clause type.
CREATE FUNCTION check_position_baseline() RETURNS trigger AS $$
DECLARE
    c RECORD;
BEGIN
    SELECT cl.clause_type, cl.review_status, ct.counterparty_id
      INTO c
      FROM clauses cl
      JOIN contracts ct ON ct.id = cl.contract_id
     WHERE cl.id = NEW.baseline_clause_id;

    IF c.counterparty_id <> NEW.counterparty_id THEN
        RAISE EXCEPTION 'Baseline clause % belongs to a different counterparty.', NEW.baseline_clause_id;
    END IF;

    IF c.clause_type <> NEW.clause_type THEN
        RAISE EXCEPTION 'Baseline clause % is a % clause, not %.',
            NEW.baseline_clause_id, c.clause_type, NEW.clause_type;
    END IF;

    IF c.review_status NOT IN ('approved', 'corrected') THEN
        RAISE EXCEPTION 'Baseline clause % has review status "%". Only reviewed clauses can become a position.',
            NEW.baseline_clause_id, c.review_status;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER counterparty_positions_baseline_check
    BEFORE INSERT OR UPDATE OF baseline_clause_id, counterparty_id, clause_type
    ON counterparty_positions
    FOR EACH ROW EXECUTE FUNCTION check_position_baseline();

-- ---------------------------------------------------------------------------
-- contract_sections: every section of a contract, filed under a clause category
-- Verbatim catalog for browsing. No extracted values and no review: the four
-- tracked clause types live in clauses, clause_terms, and counterparty_positions.
-- ---------------------------------------------------------------------------
CREATE TABLE contract_sections (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    contract_id     BIGINT NOT NULL REFERENCES contracts (id) ON DELETE CASCADE,
    position        INTEGER NOT NULL,
    category        TEXT NOT NULL,
    section_number  TEXT,
    heading         TEXT,
    full_text       TEXT NOT NULL,
    start_offset    INTEGER,
    end_offset      INTEGER,

    UNIQUE (contract_id, position)
);

CREATE INDEX contract_sections_category_idx ON contract_sections (category);

COMMIT;
