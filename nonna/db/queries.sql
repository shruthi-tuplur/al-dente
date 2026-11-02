-- Nonna "money queries": the questions Nonna must answer easily.
-- If these are simple to write, the schema is doing its job.
--
-- Run after schema.sql and seed.sql:
--   psql al_dente -f nonna/db/queries.sql
--
-- Tip: inside psql, \x on shows wide rows vertically.


-- ---------------------------------------------------------------------------
-- 1. Clause history: every liability cap with a counterparty, oldest to newest
--    Includes absent and incorporated-by-reference rows, because "there was
--    no cap" and "the SOW points to the MSA" are both part of the story.
-- ---------------------------------------------------------------------------
\echo '1. Liability cap history for Castellan Bioprocessing'

SELECT ct.effective_date,
       ct.contract_type,
       ct.title,
       cl.section_number             AS section,
       cl.presence,
       t.value_numeric               AS cap_amount,
       t.unit,
       cl.review_status
FROM clauses cl
JOIN contracts ct      ON ct.id = cl.contract_id
JOIN counterparties cp ON cp.id = ct.counterparty_id
LEFT JOIN clause_terms t ON t.clause_id = cl.id AND t.term_key = 'cap_amount'
WHERE cp.name = 'Castellan Bioprocessing'
  AND cl.clause_type = 'liability_cap'
ORDER BY ct.effective_date;


-- ---------------------------------------------------------------------------
-- 2. Current baselines: what we consider agreed right now, per clause type,
--    with the value and the document it came from
-- ---------------------------------------------------------------------------
\echo '2. Current agreed positions with Castellan Bioprocessing'

SELECT p.clause_type,
       p.contract_type_scope         AS applies_to,
       t.term_key,
       COALESCE(t.value_numeric::text, t.value_text, t.value_bool::text) AS value,
       t.unit,
       ct.title                      AS source_document,
       cl.section_number             AS section,
       p.set_by,
       p.set_at::date                AS set_on
FROM counterparty_positions p
JOIN counterparties cp ON cp.id = p.counterparty_id
JOIN clauses cl        ON cl.id = p.baseline_clause_id
JOIN contracts ct      ON ct.id = cl.contract_id
LEFT JOIN clause_terms t ON t.clause_id = cl.id
WHERE cp.name = 'Castellan Bioprocessing'
  AND p.superseded_at IS NULL
ORDER BY p.clause_type, t.term_key;


-- ---------------------------------------------------------------------------
-- 3. Missing caps: master agreements with no liability cap, split into
--    "confirmed absent" (checked, not there) and "not extracted yet"
-- ---------------------------------------------------------------------------
\echo '3. MSAs without a liability cap, across all counterparties'

SELECT cp.name                       AS counterparty,
       ct.title,
       ct.effective_date,
       CASE
           WHEN cl.id IS NULL           THEN 'not extracted yet'
           WHEN cl.presence = 'absent'  THEN 'confirmed absent'
       END                           AS cap_status
FROM contracts ct
JOIN counterparties cp ON cp.id = ct.counterparty_id
LEFT JOIN clauses cl   ON cl.contract_id = ct.id AND cl.clause_type = 'liability_cap'
WHERE ct.contract_type = 'MSA'
  AND (cl.id IS NULL OR cl.presence = 'absent')
ORDER BY cp.name;


-- ---------------------------------------------------------------------------
-- 4. Decision log: every review decision for a counterparty, with notes
-- ---------------------------------------------------------------------------
\echo '4. Decision log for Castellan Bioprocessing'

SELECT rd.created_at::date           AS decided_on,
       rd.reviewer,
       rd.action,
       cl.clause_type,
       ct.title                      AS document,
       rd.note
FROM review_decisions rd
JOIN clauses cl        ON cl.id = rd.clause_id
JOIN contracts ct      ON ct.id = cl.contract_id
JOIN counterparties cp ON cp.id = ct.counterparty_id
WHERE cp.name = 'Castellan Bioprocessing'
ORDER BY rd.created_at;


-- ---------------------------------------------------------------------------
-- 5. Review queue: extractions waiting for an attorney
-- ---------------------------------------------------------------------------
\echo '5. Review queue (pending extractions)'

SELECT cp.name                       AS counterparty,
       ct.title                      AS document,
       cl.clause_type,
       cl.presence,
       cl.extraction_method,
       cl.confidence
FROM clauses cl
JOIN contracts ct      ON ct.id = cl.contract_id
JOIN counterparties cp ON cp.id = ct.counterparty_id
WHERE cl.review_status = 'pending'
ORDER BY ct.uploaded_at, cl.clause_type;


-- ---------------------------------------------------------------------------
-- 6. Sneak peek of Too Many Cooks: pending values that differ from the
--    current baseline for the same counterparty, clause type, and contract type
-- ---------------------------------------------------------------------------
\echo '6. Possible drift: pending terms that differ from the current baseline'

SELECT cp.name                       AS counterparty,
       new_ct.title                  AS new_document,
       new_cl.clause_type,
       new_t.term_key,
       COALESCE(base_t.value_numeric::text, base_t.value_text, base_t.value_bool::text) AS baseline_value,
       COALESCE(new_t.value_numeric::text,  new_t.value_text,  new_t.value_bool::text)  AS new_value,
       new_t.unit,
       base_ct.title                 AS baseline_source
FROM clauses new_cl
JOIN contracts new_ct    ON new_ct.id = new_cl.contract_id
JOIN counterparties cp   ON cp.id = new_ct.counterparty_id
JOIN clause_terms new_t  ON new_t.clause_id = new_cl.id
JOIN counterparty_positions p
     ON p.counterparty_id = new_ct.counterparty_id
    AND p.clause_type = new_cl.clause_type
    AND new_ct.contract_type = ANY (p.contract_type_scope)
    AND p.superseded_at IS NULL
JOIN clauses base_cl     ON base_cl.id = p.baseline_clause_id
JOIN contracts base_ct   ON base_ct.id = base_cl.contract_id
JOIN clause_terms base_t ON base_t.clause_id = base_cl.id AND base_t.term_key = new_t.term_key
WHERE new_cl.review_status = 'pending'
  AND (new_t.value_numeric, new_t.value_text, new_t.value_bool)
      IS DISTINCT FROM (base_t.value_numeric, base_t.value_text, base_t.value_bool);
