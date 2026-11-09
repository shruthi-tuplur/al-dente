-- Nonna seed data: a small, realistic contract history to test the schema.
--
-- All companies are fictional. Clause text is short placeholder language
-- written for testing, not copied from any real agreement.
--
-- Run after schema.sql:
--   psql al_dente -f nonna/db/schema.sql
--   psql al_dente -f nonna/db/seed.sql
--
-- Story:
--   Castellan Bioprocessing is a manufacturing partner we have worked with for years.
--     2022  NDA           signed with the Swiss parent (Castellan Bioprocessing AG)
--     2023  MSA           signed with the US subsidiary
--     2024  SOW #1        under the MSA, milestone payments, net 30
--     2024  Amendment 1   raises the MSA liability cap from $1M to $2M (approved change)
--     2025  SOW #2        just uploaded, net 60 payment terms, still pending review
--   Halvorsen Scientific is a newer vendor with one MSA that has no liability cap.

BEGIN;

-- ---------------------------------------------------------------------------
-- Counterparties and entities
-- ---------------------------------------------------------------------------
INSERT INTO counterparties (name) VALUES
    ('Castellan Bioprocessing'),
    ('Halvorsen Scientific');

INSERT INTO counterparty_entities (counterparty_id, legal_name, jurisdiction)
SELECT c.id, e.legal_name, e.jurisdiction
FROM (VALUES
    ('Castellan Bioprocessing', 'Castellan Bioprocessing AG',        'Switzerland'),
    ('Castellan Bioprocessing', 'Castellan Bioprocessing US, Inc.',  'Delaware'),
    ('Halvorsen Scientific',    'Halvorsen Scientific Ltd.',         'England and Wales')
) AS e (counterparty, legal_name, jurisdiction)
JOIN counterparties c ON c.name = e.counterparty;


-- ---------------------------------------------------------------------------
-- Contracts (parents first, so SOWs and amendments can point to them)
-- ---------------------------------------------------------------------------
INSERT INTO contracts (counterparty_id, entity_id, contract_type, title,
                       effective_date, expiration_date, status,
                       file_path, file_hash, full_text, uploaded_by)
SELECT ent.counterparty_id, ent.id, v.contract_type, v.title,
       v.effective_date::date, v.expiration_date::date, v.status,
       v.file_path, v.file_hash, v.full_text, 'seed'
FROM (VALUES
    ('Castellan Bioprocessing AG', 'NDA', 'Mutual Nondisclosure Agreement',
     '2022-03-01', '2025-03-01', 'expired',
     'storage/contracts/castellan/2022-nda.pdf', 'sha256:castellan-2022-nda',
     'Mutual Nondisclosure Agreement between Castellan Bioprocessing AG and Client...'),
    ('Castellan Bioprocessing US, Inc.', 'MSA', 'Master Services Agreement',
     '2023-01-15', NULL, 'active',
     'storage/contracts/castellan/2023-msa.pdf', 'sha256:castellan-2023-msa',
     'Master Services Agreement between Castellan Bioprocessing US, Inc. and Client...'),
    ('Halvorsen Scientific Ltd.', 'MSA', 'Master Supply Agreement',
     '2024-09-01', NULL, 'active',
     'storage/contracts/halvorsen/2024-msa.pdf', 'sha256:halvorsen-2024-msa',
     'Master Supply Agreement between Halvorsen Scientific Ltd. and Client...')
) AS v (entity, contract_type, title, effective_date, expiration_date, status,
        file_path, file_hash, full_text)
JOIN counterparty_entities ent ON ent.legal_name = v.entity;

-- Children of the Castellan MSA
INSERT INTO contracts (counterparty_id, entity_id, contract_type, title,
                       effective_date, status, parent_contract_id, amends_contract_id,
                       file_path, file_hash, full_text, uploaded_by)
SELECT msa.counterparty_id, msa.entity_id, v.contract_type, v.title,
       v.effective_date::date, 'active',
       CASE WHEN v.contract_type = 'SOW' THEN msa.id END,
       CASE WHEN v.contract_type = 'amendment' THEN msa.id END,
       v.file_path, v.file_hash, v.full_text, 'seed'
FROM (VALUES
    ('SOW', 'Statement of Work No. 1: Process Development', '2024-02-10',
     'storage/contracts/castellan/2024-sow-1.pdf', 'sha256:castellan-2024-sow-1',
     'Statement of Work No. 1 under the Master Services Agreement dated January 15, 2023...'),
    ('amendment', 'Amendment No. 1 to Master Services Agreement', '2024-06-01',
     'storage/contracts/castellan/2024-amendment-1.pdf', 'sha256:castellan-2024-amendment-1',
     'Amendment No. 1 to the Master Services Agreement dated January 15, 2023...'),
    ('SOW', 'Statement of Work No. 2: Tech Transfer', '2025-03-01',
     'storage/contracts/castellan/2025-sow-2.pdf', 'sha256:castellan-2025-sow-2',
     'Statement of Work No. 2 under the Master Services Agreement dated January 15, 2023...')
) AS v (contract_type, title, effective_date, file_path, file_hash, full_text)
CROSS JOIN contracts msa
WHERE msa.file_hash = 'sha256:castellan-2023-msa';


-- ---------------------------------------------------------------------------
-- Clauses
-- Amendments only get rows for the clauses they actually change.
-- ---------------------------------------------------------------------------
INSERT INTO clauses (contract_id, clause_type, section_number, heading, full_text,
                     presence, extraction_method, confidence, review_status)
SELECT ct.id, v.clause_type, v.section_number, v.heading, v.full_text,
       v.presence, v.extraction_method, v.confidence::numeric, v.review_status
FROM (VALUES
    -- 2022 NDA
    ('sha256:castellan-2022-nda', 'governing_law', '9.1', 'Governing Law',
     'This Agreement shall be governed by the laws of the State of New York.',
     'present', 'deterministic', NULL, 'approved'),
    ('sha256:castellan-2022-nda', 'liability_cap', NULL, NULL, NULL,
     'absent', 'deterministic', NULL, 'approved'),
    ('sha256:castellan-2022-nda', 'payment_terms', NULL, NULL, NULL,
     'absent', 'deterministic', NULL, 'approved'),
    ('sha256:castellan-2022-nda', 'indemnification', NULL, NULL, NULL,
     'absent', 'llm', 0.950, 'approved'),

    -- 2023 MSA
    ('sha256:castellan-2023-msa', 'liability_cap', '12.2', 'Limitation of Liability',
     'Except for indemnification obligations and breaches of confidentiality, each party''s aggregate liability under this Agreement shall not exceed one million US dollars ($1,000,000).',
     'present', 'deterministic', NULL, 'approved'),
    ('sha256:castellan-2023-msa', 'governing_law', '18.3', 'Governing Law',
     'This Agreement shall be governed by the laws of the State of New York, without regard to its conflict of laws principles.',
     'present', 'deterministic', NULL, 'approved'),
    ('sha256:castellan-2023-msa', 'payment_terms', '6.1', 'Payment',
     'Client shall pay each undisputed invoice within forty-five (45) days of receipt.',
     'present', 'deterministic', NULL, 'approved'),
    ('sha256:castellan-2023-msa', 'indemnification', '11.1', 'Indemnification',
     'Each party shall indemnify, defend, and hold harmless the other party from third-party claims arising from its breach of this Agreement, its negligence or willful misconduct, or its infringement of third-party intellectual property rights.',
     'present', 'llm', 0.860, 'corrected'),

    -- 2024 SOW #1 (cap, law, and indemnity come from the MSA)
    ('sha256:castellan-2024-sow-1', 'payment_terms', '5', 'Payment Schedule',
     'Fees are payable upon completion of each milestone listed in Exhibit A. Client shall pay each milestone invoice within thirty (30) days of receipt.',
     'present', 'deterministic', NULL, 'approved'),
    ('sha256:castellan-2024-sow-1', 'liability_cap', '1', 'Incorporation',
     'This SOW is governed by the terms of the Master Services Agreement.',
     'incorporated_by_reference', 'deterministic', NULL, 'approved'),
    ('sha256:castellan-2024-sow-1', 'governing_law', '1', 'Incorporation',
     'This SOW is governed by the terms of the Master Services Agreement.',
     'incorporated_by_reference', 'deterministic', NULL, 'approved'),
    ('sha256:castellan-2024-sow-1', 'indemnification', '1', 'Incorporation',
     'This SOW is governed by the terms of the Master Services Agreement.',
     'incorporated_by_reference', 'llm', 0.920, 'approved'),

    -- 2024 Amendment 1 (only changes the cap)
    ('sha256:castellan-2024-amendment-1', 'liability_cap', '2', 'Amendment to Section 12.2',
     'Section 12.2 of the Agreement is amended by replacing "one million US dollars ($1,000,000)" with "two million US dollars ($2,000,000)".',
     'present', 'deterministic', NULL, 'approved'),

    -- 2025 SOW #2 (just uploaded, waiting in the review queue)
    ('sha256:castellan-2025-sow-2', 'payment_terms', '5', 'Payment Schedule',
     'Fees are payable upon completion of each milestone listed in Exhibit A. Client shall pay each milestone invoice within sixty (60) days of receipt.',
     'present', 'deterministic', NULL, 'pending'),
    ('sha256:castellan-2025-sow-2', 'liability_cap', '1', 'Incorporation',
     'This SOW is governed by the terms of the Master Services Agreement.',
     'incorporated_by_reference', 'deterministic', NULL, 'pending'),

    -- Halvorsen 2024 MSA (no cap at all)
    ('sha256:halvorsen-2024-msa', 'liability_cap', NULL, NULL, NULL,
     'absent', 'deterministic', NULL, 'approved'),
    ('sha256:halvorsen-2024-msa', 'governing_law', '20.1', 'Governing Law',
     'This Agreement shall be governed by the laws of England and Wales.',
     'present', 'deterministic', NULL, 'approved'),
    ('sha256:halvorsen-2024-msa', 'payment_terms', '7.2', 'Payment',
     'Client shall pay each invoice within thirty (30) days of the invoice date.',
     'present', 'deterministic', NULL, 'approved')
) AS v (file_hash, clause_type, section_number, heading, full_text,
        presence, extraction_method, confidence, review_status)
JOIN contracts ct ON ct.file_hash = v.file_hash;


-- ---------------------------------------------------------------------------
-- Clause terms (only for clauses with their own language)
-- ---------------------------------------------------------------------------
INSERT INTO clause_terms (clause_id, term_key, value_numeric, value_text, value_bool, unit)
SELECT cl.id, v.term_key, v.value_numeric::numeric, v.value_text, v.value_bool::boolean, v.unit
FROM (VALUES
    ('sha256:castellan-2022-nda',         'governing_law',   'jurisdiction',           NULL,      'New York',          NULL,    NULL),
    ('sha256:castellan-2023-msa',         'liability_cap',   'cap_amount',             '1000000', NULL,                NULL,    'USD'),
    ('sha256:castellan-2023-msa',         'liability_cap',   'carve_outs',             NULL,      'indemnification; confidentiality', NULL, NULL),
    ('sha256:castellan-2023-msa',         'governing_law',   'jurisdiction',           NULL,      'New York',          NULL,    NULL),
    ('sha256:castellan-2023-msa',         'payment_terms',   'net_days',               '45',      NULL,                NULL,    'days'),
    ('sha256:castellan-2023-msa',         'payment_terms',   'payment_structure',      NULL,      'invoice',           NULL,    NULL),
    ('sha256:castellan-2023-msa',         'indemnification', 'is_mutual',              NULL,      NULL,                'true',  NULL),
    ('sha256:castellan-2023-msa',         'indemnification', 'covers_ip_infringement', NULL,      NULL,                'true',  NULL),
    ('sha256:castellan-2024-sow-1',       'payment_terms',   'net_days',               '30',      NULL,                NULL,    'days'),
    ('sha256:castellan-2024-sow-1',       'payment_terms',   'payment_structure',      NULL,      'milestone',         NULL,    NULL),
    ('sha256:castellan-2024-amendment-1', 'liability_cap',   'cap_amount',             '2000000', NULL,                NULL,    'USD'),
    ('sha256:castellan-2025-sow-2',       'payment_terms',   'net_days',               '60',      NULL,                NULL,    'days'),
    ('sha256:castellan-2025-sow-2',       'payment_terms',   'payment_structure',      NULL,      'milestone',         NULL,    NULL),
    ('sha256:halvorsen-2024-msa',         'governing_law',   'jurisdiction',           NULL,      'England and Wales', NULL,    NULL),
    ('sha256:halvorsen-2024-msa',         'payment_terms',   'net_days',               '30',      NULL,                NULL,    'days'),
    ('sha256:halvorsen-2024-msa',         'payment_terms',   'payment_structure',      NULL,      'invoice',           NULL,    NULL)
) AS v (file_hash, clause_type, term_key, value_numeric, value_text, value_bool, unit)
JOIN contracts ct ON ct.file_hash = v.file_hash
JOIN clauses cl ON cl.contract_id = ct.id AND cl.clause_type = v.clause_type;


-- ---------------------------------------------------------------------------
-- Review decisions (append-only history)
-- ---------------------------------------------------------------------------
INSERT INTO review_decisions (clause_id, action, note, reviewer, created_at, changes)
SELECT cl.id, v.action, v.note, v.reviewer, v.created_at::timestamptz, v.changes::jsonb
FROM (VALUES
    ('sha256:castellan-2022-nda', 'governing_law', 'approved', NULL,
     'j.romano', '2022-03-05 10:00-08', NULL),
    ('sha256:castellan-2023-msa', 'liability_cap', 'approved', NULL,
     'j.romano', '2023-01-20 09:30-08', NULL),
    ('sha256:castellan-2023-msa', 'governing_law', 'approved', NULL,
     'j.romano', '2023-01-20 09:31-08', NULL),
    ('sha256:castellan-2023-msa', 'payment_terms', 'approved', NULL,
     'j.romano', '2023-01-20 09:32-08', NULL),
    ('sha256:castellan-2023-msa', 'indemnification', 'corrected',
     'LLM missed that the IP infringement indemnity is mutual. Corrected is_mutual and covers_ip_infringement.',
     'j.romano', '2023-01-20 09:40-08',
     '{"is_mutual": {"from": false, "to": true}, "covers_ip_infringement": {"from": false, "to": true}}'),
    ('sha256:castellan-2024-sow-1', 'payment_terms', 'approved_change',
     'Milestone billing at net 30 agreed for process development work to align with project funding.',
     'a.ferraro', '2024-02-12 14:00-08', NULL),
    ('sha256:castellan-2024-amendment-1', 'liability_cap', 'approved_change',
     'Cap raised to $2M in exchange for expanded batch volumes. Approved by GC.',
     'a.ferraro', '2024-06-03 11:15-07', NULL),
    ('sha256:halvorsen-2024-msa', 'liability_cap', 'approved',
     'Confirmed no cap in executed MSA. Flagged for renegotiation at renewal.',
     'm.bianchi', '2024-09-04 16:20-07', NULL)
) AS v (file_hash, clause_type, action, note, reviewer, created_at, changes)
JOIN contracts ct ON ct.file_hash = v.file_hash
JOIN clauses cl ON cl.contract_id = ct.id AND cl.clause_type = v.clause_type;


-- ---------------------------------------------------------------------------
-- Counterparty positions (baselines)
-- The $1M cap was the baseline until Amendment 1 replaced it with $2M.
-- ---------------------------------------------------------------------------
INSERT INTO counterparty_positions (counterparty_id, clause_type, contract_type_scope,
                                    baseline_clause_id, set_by, set_at, note, superseded_at)
SELECT ct.counterparty_id, v.clause_type, v.scope::text[], cl.id,
       v.set_by, v.set_at::timestamptz, v.note, v.superseded_at::timestamptz
FROM (VALUES
    ('sha256:castellan-2022-nda', 'governing_law', '{NDA}',
     'j.romano', '2022-03-05 10:05-08', NULL, NULL),
    ('sha256:castellan-2023-msa', 'liability_cap', '{MSA,amendment}',
     'j.romano', '2023-01-20 10:00-08', NULL, '2024-06-03 11:20-07'),
    ('sha256:castellan-2024-amendment-1', 'liability_cap', '{MSA,amendment}',
     'a.ferraro', '2024-06-03 11:20-07', 'Cap raised to $2M by Amendment 1.', NULL),
    ('sha256:castellan-2023-msa', 'governing_law', '{MSA,amendment}',
     'j.romano', '2023-01-20 10:00-08', NULL, NULL),
    ('sha256:castellan-2023-msa', 'indemnification', '{MSA,amendment}',
     'j.romano', '2023-01-20 10:00-08', NULL, NULL),
    ('sha256:castellan-2024-sow-1', 'payment_terms', '{SOW}',
     'a.ferraro', '2024-02-12 14:05-08', 'SOW standard: milestone billing, net 30.', NULL),
    ('sha256:halvorsen-2024-msa', 'governing_law', '{MSA,amendment}',
     'm.bianchi', '2024-09-04 16:25-07', NULL, NULL)
) AS v (file_hash, clause_type, scope, set_by, set_at, note, superseded_at)
JOIN contracts ct ON ct.file_hash = v.file_hash
JOIN clauses cl ON cl.contract_id = ct.id AND cl.clause_type = v.clause_type;

COMMIT;
