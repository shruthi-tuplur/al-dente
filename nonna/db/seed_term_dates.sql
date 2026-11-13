-- Term and renewal dates for the seeded vendors, so the deadlines feature has something to show.
-- Adds to your existing data (nothing is deleted). Run once, after the other seed files:
--   psql al_dente -f nonna/db/seed_term_dates.sql
--
-- All fictional, with short placeholder clause text. Already reviewed, like the rest of the seed data.
--   Castellan MSA     3 years from Jan 15, 2023, renews yearly, 60 days' notice
--   Castellan NDA     3 years from Mar 1, 2022, no renewal (already expired)
--   Halvorsen MSA     3 years from Sep 1, 2024, renews yearly, 60 days' notice
--   Brindisi MSA      2 years from Apr 1, 2024, no renewal (already expired)
--   Sorrento MSA      3 years from Nov 15, 2023, renews yearly, 90 days' notice
--   Fennel MSA        2 years from Feb 1, 2025, no renewal
--   Marsala MSA       2 years from Jun 10, 2025, renews yearly, 120 days' notice

BEGIN;

INSERT INTO clauses (contract_id, clause_type, section_number, heading, full_text,
                     presence, extraction_method, confidence, review_status)
SELECT ct.id, 'term_renewal', v.section_number, 'Term', v.full_text,
       'present', 'deterministic', NULL, 'approved'
FROM (VALUES
    ('sha256:castellan-2023-msa', '15.1',
     'This Agreement shall commence on the Effective Date and continue for an initial term of three (3) years. Thereafter, it shall automatically renew for successive one (1) year periods unless either party provides written notice of non-renewal at least sixty (60) days before the end of the then-current term.'),
    ('sha256:castellan-2022-nda', '8.1',
     'This Agreement shall remain in effect for a period of three (3) years from the Effective Date.'),
    ('sha256:halvorsen-2024-msa', '12.1',
     'This Agreement shall commence on the Effective Date and continue for an initial term of three (3) years. Thereafter, it shall automatically renew for successive one (1) year periods unless either party provides written notice of non-renewal at least sixty (60) days before the end of the then-current term.'),
    ('sha256:brindisi-2024-msa', '13.1',
     'The term of this Agreement is two (2) years from the Effective Date.'),
    ('sha256:sorrento-2023-msa', '16.1',
     'This Agreement shall commence on the Effective Date and continue for an initial term of three (3) years. Thereafter, it shall automatically renew for successive one (1) year periods unless either party provides written notice of non-renewal at least ninety (90) days before the end of the then-current term.'),
    ('sha256:fennel-2025-msa', '18.1',
     'The term of this Agreement is two (2) years from the Effective Date.'),
    ('sha256:marsala-2025-msa', '14.1',
     'This Agreement shall commence on the Effective Date and continue for an initial term of two (2) years. Thereafter, it shall automatically renew for successive one (1) year periods unless either party provides written notice of non-renewal at least one hundred twenty (120) days before the end of the then-current term.')
) AS v (file_hash, section_number, full_text)
JOIN contracts ct ON ct.file_hash = v.file_hash;

INSERT INTO clause_terms (clause_id, term_key, value_numeric, value_bool, unit)
SELECT cl.id, v.term_key, v.value_numeric::numeric, v.value_bool::boolean, v.unit
FROM (VALUES
    ('sha256:castellan-2023-msa', 'initial_term_months', '36', NULL, 'months'),
    ('sha256:castellan-2023-msa', 'auto_renews', NULL, 'true', NULL),
    ('sha256:castellan-2023-msa', 'renewal_term_months', '12', NULL, 'months'),
    ('sha256:castellan-2023-msa', 'notice_days', '60', NULL, 'days'),
    ('sha256:castellan-2022-nda', 'initial_term_months', '36', NULL, 'months'),
    ('sha256:castellan-2022-nda', 'auto_renews', NULL, 'false', NULL),
    ('sha256:halvorsen-2024-msa', 'initial_term_months', '36', NULL, 'months'),
    ('sha256:halvorsen-2024-msa', 'auto_renews', NULL, 'true', NULL),
    ('sha256:halvorsen-2024-msa', 'renewal_term_months', '12', NULL, 'months'),
    ('sha256:halvorsen-2024-msa', 'notice_days', '60', NULL, 'days'),
    ('sha256:brindisi-2024-msa', 'initial_term_months', '24', NULL, 'months'),
    ('sha256:brindisi-2024-msa', 'auto_renews', NULL, 'false', NULL),
    ('sha256:sorrento-2023-msa', 'initial_term_months', '36', NULL, 'months'),
    ('sha256:sorrento-2023-msa', 'auto_renews', NULL, 'true', NULL),
    ('sha256:sorrento-2023-msa', 'renewal_term_months', '12', NULL, 'months'),
    ('sha256:sorrento-2023-msa', 'notice_days', '90', NULL, 'days'),
    ('sha256:fennel-2025-msa', 'initial_term_months', '24', NULL, 'months'),
    ('sha256:fennel-2025-msa', 'auto_renews', NULL, 'false', NULL),
    ('sha256:marsala-2025-msa', 'initial_term_months', '24', NULL, 'months'),
    ('sha256:marsala-2025-msa', 'auto_renews', NULL, 'true', NULL),
    ('sha256:marsala-2025-msa', 'renewal_term_months', '12', NULL, 'months'),
    ('sha256:marsala-2025-msa', 'notice_days', '120', NULL, 'days')
) AS v (file_hash, term_key, value_numeric, value_bool, unit)
JOIN contracts ct ON ct.file_hash = v.file_hash
JOIN clauses cl ON cl.contract_id = ct.id AND cl.clause_type = 'term_renewal';

INSERT INTO review_decisions (clause_id, action, note, reviewer)
SELECT cl.id, 'approved', NULL, 'seed'
FROM clauses cl
JOIN contracts ct ON ct.id = cl.contract_id
WHERE cl.clause_type = 'term_renewal'
  AND ct.file_hash IN ('sha256:castellan-2023-msa', 'sha256:castellan-2022-nda', 'sha256:halvorsen-2024-msa',
                       'sha256:brindisi-2024-msa', 'sha256:sorrento-2023-msa', 'sha256:fennel-2025-msa',
                       'sha256:marsala-2025-msa');

COMMIT;