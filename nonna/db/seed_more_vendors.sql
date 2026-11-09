-- More fictional vendors, so questions across vendors have something to compare.
-- Adds to your existing data (nothing is deleted). Run once, after schema.sql and seed.sql:
--   psql al_dente -f nonna/db/seed_more_vendors.sql
--
-- All companies are fictional and the clause text is short placeholder language.
--   Brindisi Analytics           $500,000 cap, net 30, Delaware, mutual indemnity with IP
--   Sorrento Cell Therapy        $5,000,000 cap, net 60, New York, one-way indemnity
--   Fennel Labs (Germany)        EUR 750,000 cap, net 45, German law
--   Marsala Clinical Logistics   $750,000 cap, net 45, California, plus a SOW at net 90 waiting for review
-- Also gives two approved terms from seed.sql the agreed baseline they were missing:
-- Halvorsen's net 30 and Castellan's MSA net 45.

BEGIN;

INSERT INTO counterparties (name) VALUES
    ('Brindisi Analytics'),
    ('Sorrento Cell Therapy Services'),
    ('Fennel Labs'),
    ('Marsala Clinical Logistics');

INSERT INTO counterparty_entities (counterparty_id, legal_name, jurisdiction)
SELECT c.id, e.legal_name, e.jurisdiction
FROM (VALUES
    ('Brindisi Analytics', 'Brindisi Analytics, Inc.', 'Delaware'),
    ('Sorrento Cell Therapy Services', 'Sorrento Cell Therapy Services LLC', 'Massachusetts'),
    ('Fennel Labs', 'Fennel Labs GmbH', 'Germany'),
    ('Marsala Clinical Logistics', 'Marsala Clinical Logistics Corp.', 'California')
) AS e (counterparty, legal_name, jurisdiction)
JOIN counterparties c ON c.name = e.counterparty;

INSERT INTO contracts (counterparty_id, entity_id, contract_type, title, effective_date, status,
                       file_path, file_hash, full_text, uploaded_by)
SELECT ent.counterparty_id, ent.id, v.contract_type, v.title, v.effective_date::date, 'active',
       v.file_path, v.file_hash, v.full_text, 'seed'
FROM (VALUES
    ('Brindisi Analytics, Inc.', 'MSA', 'Master Services Agreement', '2024-04-01',
     'storage/contracts/seed/brindisi-2024-msa.pdf', 'sha256:brindisi-2024-msa',
     'Master Services Agreement between Brindisi Analytics, Inc. and Client...'),
    ('Sorrento Cell Therapy Services LLC', 'MSA', 'Master Manufacturing Services Agreement', '2023-11-15',
     'storage/contracts/seed/sorrento-2023-msa.pdf', 'sha256:sorrento-2023-msa',
     'Master Manufacturing Services Agreement between Sorrento Cell Therapy Services LLC and Client...'),
    ('Fennel Labs GmbH', 'MSA', 'Master Research Services Agreement', '2025-02-01',
     'storage/contracts/seed/fennel-2025-msa.pdf', 'sha256:fennel-2025-msa',
     'Master Research Services Agreement between Fennel Labs GmbH and Client...'),
    ('Marsala Clinical Logistics Corp.', 'MSA', 'Master Services Agreement', '2025-06-10',
     'storage/contracts/seed/marsala-2025-msa.pdf', 'sha256:marsala-2025-msa',
     'Master Services Agreement between Marsala Clinical Logistics Corp. and Client...')
) AS v (entity, contract_type, title, effective_date, file_path, file_hash, full_text)
JOIN counterparty_entities ent ON ent.legal_name = v.entity;

-- A Marsala SOW that just came in, still waiting for review
INSERT INTO contracts (counterparty_id, entity_id, contract_type, title, effective_date, status,
                       parent_contract_id, file_path, file_hash, full_text, uploaded_by)
SELECT msa.counterparty_id, msa.entity_id, 'SOW', 'Statement of Work No. 1: Cold Chain Distribution',
       '2025-08-01'::date, 'active', msa.id,
       'storage/contracts/seed/marsala-2025-sow-1.pdf', 'sha256:marsala-2025-sow-1',
       'Statement of Work No. 1 under the Master Services Agreement dated June 10, 2025...', 'seed'
FROM contracts msa
WHERE msa.file_hash = 'sha256:marsala-2025-msa';

INSERT INTO clauses (contract_id, clause_type, section_number, heading, full_text,
                     presence, extraction_method, confidence, review_status)
SELECT ct.id, v.clause_type, v.section_number, v.heading, v.full_text,
       v.presence, v.extraction_method, v.confidence::numeric, v.review_status
FROM (VALUES
    ('sha256:brindisi-2024-msa', 'liability_cap', '10.2', 'Limitation of Liability',
     'Except for indemnification obligations and breaches of confidentiality, each party''s aggregate liability under this Agreement shall not exceed five hundred thousand US dollars ($500,000).',
     'present', 'deterministic', NULL, 'approved'),
    ('sha256:brindisi-2024-msa', 'payment_terms', '5.1', 'Payment',
     'Client shall pay each undisputed invoice within thirty (30) days of receipt.',
     'present', 'deterministic', NULL, 'approved'),
    ('sha256:brindisi-2024-msa', 'governing_law', '14.1', 'Governing Law',
     'This Agreement shall be governed by the laws of the State of Delaware.',
     'present', 'deterministic', NULL, 'approved'),
    ('sha256:brindisi-2024-msa', 'indemnification', '9.1', 'Indemnification',
     'Each party shall indemnify, defend, and hold harmless the other party from third-party claims arising from its breach of this Agreement or its negligence or willful misconduct, or its infringement of third-party intellectual property rights.',
     'present', 'llm', 0.900, 'approved'),
    ('sha256:sorrento-2023-msa', 'liability_cap', '12.1', 'Limitation of Liability',
     'Except for indemnification obligations and breaches of confidentiality, each party''s aggregate liability under this Agreement shall not exceed five million US dollars ($5,000,000).',
     'present', 'deterministic', NULL, 'approved'),
    ('sha256:sorrento-2023-msa', 'payment_terms', '6.2', 'Payment',
     'Client shall pay each undisputed invoice within sixty (60) days of receipt.',
     'present', 'deterministic', NULL, 'approved'),
    ('sha256:sorrento-2023-msa', 'governing_law', '17.4', 'Governing Law',
     'This Agreement shall be governed by the laws of the State of New York.',
     'present', 'deterministic', NULL, 'approved'),
    ('sha256:sorrento-2023-msa', 'indemnification', '11.1', 'Indemnification',
     'Supplier shall indemnify, defend, and hold harmless Client from third-party claims arising from Supplier''s breach of this Agreement or its negligence or willful misconduct.',
     'present', 'llm', 0.900, 'approved'),
    ('sha256:fennel-2025-msa', 'liability_cap', '13.3', 'Limitation of Liability',
     'Except for indemnification obligations and breaches of confidentiality, each party''s aggregate liability under this Agreement shall not exceed seven hundred fifty thousand euros (EUR 750,000).',
     'present', 'deterministic', NULL, 'approved'),
    ('sha256:fennel-2025-msa', 'payment_terms', '7.1', 'Payment',
     'Client shall pay each undisputed invoice within forty-five (45) days of receipt.',
     'present', 'deterministic', NULL, 'approved'),
    ('sha256:fennel-2025-msa', 'governing_law', '19.2', 'Governing Law',
     'This Agreement shall be governed by the laws of the Federal Republic of Germany.',
     'present', 'deterministic', NULL, 'approved'),
    ('sha256:fennel-2025-msa', 'indemnification', '12.1', 'Indemnification',
     'Each party shall indemnify, defend, and hold harmless the other party from third-party claims arising from its breach of this Agreement or its negligence or willful misconduct, or its infringement of third-party intellectual property rights.',
     'present', 'llm', 0.900, 'approved'),
    ('sha256:marsala-2025-msa', 'liability_cap', '11.2', 'Limitation of Liability',
     'Except for indemnification obligations and breaches of confidentiality, each party''s aggregate liability under this Agreement shall not exceed seven hundred fifty thousand US dollars ($750,000).',
     'present', 'deterministic', NULL, 'approved'),
    ('sha256:marsala-2025-msa', 'payment_terms', '4.3', 'Payment',
     'Client shall pay each undisputed invoice within forty-five (45) days of receipt.',
     'present', 'deterministic', NULL, 'approved'),
    ('sha256:marsala-2025-msa', 'governing_law', '15.1', 'Governing Law',
     'This Agreement shall be governed by the laws of the State of California.',
     'present', 'deterministic', NULL, 'approved'),
    ('sha256:marsala-2025-msa', 'indemnification', '10.1', 'Indemnification',
     'Each party shall indemnify, defend, and hold harmless the other party from third-party claims arising from its breach of this Agreement or its negligence or willful misconduct.',
     'present', 'llm', 0.900, 'approved'),
    ('sha256:marsala-2025-sow-1', 'payment_terms', '3', 'Fees and Payment',
     'Client shall pay each milestone invoice within ninety (90) days of receipt.',
     'present', 'deterministic', NULL, 'pending')
) AS v (file_hash, clause_type, section_number, heading, full_text,
        presence, extraction_method, confidence, review_status)
JOIN contracts ct ON ct.file_hash = v.file_hash;

INSERT INTO clause_terms (clause_id, term_key, value_numeric, value_text, value_bool, unit)
SELECT cl.id, v.term_key, v.value_numeric::numeric, v.value_text, v.value_bool::boolean, v.unit
FROM (VALUES
    ('sha256:brindisi-2024-msa', 'liability_cap', 'cap_amount', '500000', NULL, NULL, 'USD'),
    ('sha256:brindisi-2024-msa', 'payment_terms', 'net_days', '30', NULL, NULL, 'days'),
    ('sha256:brindisi-2024-msa', 'payment_terms', 'payment_structure', NULL, 'invoice', NULL, NULL),
    ('sha256:brindisi-2024-msa', 'governing_law', 'jurisdiction', NULL, 'Delaware', NULL, NULL),
    ('sha256:brindisi-2024-msa', 'indemnification', 'is_mutual', NULL, NULL, 'true', NULL),
    ('sha256:brindisi-2024-msa', 'indemnification', 'covers_ip_infringement', NULL, NULL, 'true', NULL),
    ('sha256:sorrento-2023-msa', 'liability_cap', 'cap_amount', '5000000', NULL, NULL, 'USD'),
    ('sha256:sorrento-2023-msa', 'payment_terms', 'net_days', '60', NULL, NULL, 'days'),
    ('sha256:sorrento-2023-msa', 'payment_terms', 'payment_structure', NULL, 'invoice', NULL, NULL),
    ('sha256:sorrento-2023-msa', 'governing_law', 'jurisdiction', NULL, 'New York', NULL, NULL),
    ('sha256:sorrento-2023-msa', 'indemnification', 'is_mutual', NULL, NULL, 'false', NULL),
    ('sha256:sorrento-2023-msa', 'indemnification', 'covers_ip_infringement', NULL, NULL, 'false', NULL),
    ('sha256:fennel-2025-msa', 'liability_cap', 'cap_amount', '750000', NULL, NULL, 'EUR'),
    ('sha256:fennel-2025-msa', 'payment_terms', 'net_days', '45', NULL, NULL, 'days'),
    ('sha256:fennel-2025-msa', 'payment_terms', 'payment_structure', NULL, 'invoice', NULL, NULL),
    ('sha256:fennel-2025-msa', 'governing_law', 'jurisdiction', NULL, 'Germany', NULL, NULL),
    ('sha256:fennel-2025-msa', 'indemnification', 'is_mutual', NULL, NULL, 'true', NULL),
    ('sha256:fennel-2025-msa', 'indemnification', 'covers_ip_infringement', NULL, NULL, 'true', NULL),
    ('sha256:marsala-2025-msa', 'liability_cap', 'cap_amount', '750000', NULL, NULL, 'USD'),
    ('sha256:marsala-2025-msa', 'payment_terms', 'net_days', '45', NULL, NULL, 'days'),
    ('sha256:marsala-2025-msa', 'payment_terms', 'payment_structure', NULL, 'invoice', NULL, NULL),
    ('sha256:marsala-2025-msa', 'governing_law', 'jurisdiction', NULL, 'California', NULL, NULL),
    ('sha256:marsala-2025-msa', 'indemnification', 'is_mutual', NULL, NULL, 'true', NULL),
    ('sha256:marsala-2025-msa', 'indemnification', 'covers_ip_infringement', NULL, NULL, 'false', NULL),
    ('sha256:marsala-2025-sow-1', 'payment_terms', 'net_days', '90', NULL, NULL, 'days'),
    ('sha256:marsala-2025-sow-1', 'payment_terms', 'payment_structure', NULL, 'milestone', NULL, NULL)
) AS v (file_hash, clause_type, term_key, value_numeric, value_text, value_bool, unit)
JOIN contracts ct ON ct.file_hash = v.file_hash
JOIN clauses cl ON cl.contract_id = ct.id AND cl.clause_type = v.clause_type;

INSERT INTO review_decisions (clause_id, action, note, reviewer, created_at)
SELECT cl.id, 'approved', NULL, v.reviewer, v.created_at::timestamptz
FROM (VALUES
    ('sha256:brindisi-2024-msa', 'liability_cap', 'm.bianchi', '2024-04-03 10:00-07'),
    ('sha256:brindisi-2024-msa', 'payment_terms', 'm.bianchi', '2024-04-03 10:00-07'),
    ('sha256:brindisi-2024-msa', 'governing_law', 'm.bianchi', '2024-04-03 10:00-07'),
    ('sha256:brindisi-2024-msa', 'indemnification', 'm.bianchi', '2024-04-03 10:00-07'),
    ('sha256:sorrento-2023-msa', 'liability_cap', 'j.romano', '2023-11-20 09:00-08'),
    ('sha256:sorrento-2023-msa', 'payment_terms', 'j.romano', '2023-11-20 09:00-08'),
    ('sha256:sorrento-2023-msa', 'governing_law', 'j.romano', '2023-11-20 09:00-08'),
    ('sha256:sorrento-2023-msa', 'indemnification', 'j.romano', '2023-11-20 09:00-08'),
    ('sha256:fennel-2025-msa', 'liability_cap', 'a.ferraro', '2025-02-05 11:30-08'),
    ('sha256:fennel-2025-msa', 'payment_terms', 'a.ferraro', '2025-02-05 11:30-08'),
    ('sha256:fennel-2025-msa', 'governing_law', 'a.ferraro', '2025-02-05 11:30-08'),
    ('sha256:fennel-2025-msa', 'indemnification', 'a.ferraro', '2025-02-05 11:30-08'),
    ('sha256:marsala-2025-msa', 'liability_cap', 'm.bianchi', '2025-06-12 14:15-07'),
    ('sha256:marsala-2025-msa', 'payment_terms', 'm.bianchi', '2025-06-12 14:15-07'),
    ('sha256:marsala-2025-msa', 'governing_law', 'm.bianchi', '2025-06-12 14:15-07'),
    ('sha256:marsala-2025-msa', 'indemnification', 'm.bianchi', '2025-06-12 14:15-07')
) AS v (file_hash, clause_type, reviewer, created_at)
JOIN contracts ct ON ct.file_hash = v.file_hash
JOIN clauses cl ON cl.contract_id = ct.id AND cl.clause_type = v.clause_type;

INSERT INTO counterparty_positions (counterparty_id, clause_type, contract_type_scope,
                                    baseline_clause_id, set_by, set_at, note)
SELECT ct.counterparty_id, v.clause_type, '{MSA,amendment}'::text[], cl.id,
       v.set_by, v.set_at::timestamptz, NULL
FROM (VALUES
    ('sha256:brindisi-2024-msa', 'liability_cap', 'm.bianchi', '2024-04-03 10:00-07'),
    ('sha256:brindisi-2024-msa', 'payment_terms', 'm.bianchi', '2024-04-03 10:00-07'),
    ('sha256:brindisi-2024-msa', 'governing_law', 'm.bianchi', '2024-04-03 10:00-07'),
    ('sha256:brindisi-2024-msa', 'indemnification', 'm.bianchi', '2024-04-03 10:00-07'),
    ('sha256:sorrento-2023-msa', 'liability_cap', 'j.romano', '2023-11-20 09:00-08'),
    ('sha256:sorrento-2023-msa', 'payment_terms', 'j.romano', '2023-11-20 09:00-08'),
    ('sha256:sorrento-2023-msa', 'governing_law', 'j.romano', '2023-11-20 09:00-08'),
    ('sha256:sorrento-2023-msa', 'indemnification', 'j.romano', '2023-11-20 09:00-08'),
    ('sha256:fennel-2025-msa', 'liability_cap', 'a.ferraro', '2025-02-05 11:30-08'),
    ('sha256:fennel-2025-msa', 'payment_terms', 'a.ferraro', '2025-02-05 11:30-08'),
    ('sha256:fennel-2025-msa', 'governing_law', 'a.ferraro', '2025-02-05 11:30-08'),
    ('sha256:fennel-2025-msa', 'indemnification', 'a.ferraro', '2025-02-05 11:30-08'),
    ('sha256:marsala-2025-msa', 'liability_cap', 'm.bianchi', '2025-06-12 14:15-07'),
    ('sha256:marsala-2025-msa', 'payment_terms', 'm.bianchi', '2025-06-12 14:15-07'),
    ('sha256:marsala-2025-msa', 'governing_law', 'm.bianchi', '2025-06-12 14:15-07'),
    ('sha256:marsala-2025-msa', 'indemnification', 'm.bianchi', '2025-06-12 14:15-07'),
    ('sha256:halvorsen-2024-msa', 'payment_terms', 'm.bianchi', '2024-09-04 16:25-07'),
    ('sha256:castellan-2023-msa', 'payment_terms', 'j.romano', '2023-01-20 10:00-08')
) AS v (file_hash, clause_type, set_by, set_at)
JOIN contracts ct ON ct.file_hash = v.file_hash
JOIN clauses cl ON cl.contract_id = ct.id AND cl.clause_type = v.clause_type
-- Skip any that already have an agreed baseline
ON CONFLICT (counterparty_id, clause_type, contract_type_scope) WHERE superseded_at IS NULL DO NOTHING;

COMMIT;