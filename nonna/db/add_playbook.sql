-- Aurelia's playbook: our standard position for each clause type, and the fallback we'll accept.
-- Safe to run more than once. Run with:
--   psql al_dente -f nonna/db/add_playbook.sql

BEGIN;

CREATE TABLE IF NOT EXISTS playbook_rules (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    clause_type    TEXT NOT NULL CHECK (clause_type IN
                     ('liability_cap', 'payment_terms', 'governing_law', 'indemnification', 'term_renewal')),
    standard       JSONB NOT NULL,   -- what we ask for
    fallback       JSONB NOT NULL,   -- the least we'll accept without escalating
    guidance       TEXT NOT NULL,    -- what to tell the attorney, in plain English
    note           TEXT,             -- why this version of the rule was set
    set_by         TEXT NOT NULL,
    set_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    superseded_at  TIMESTAMPTZ       -- null means this is the current rule
);

-- Only one current rule per clause type
CREATE UNIQUE INDEX IF NOT EXISTS playbook_rules_current
    ON playbook_rules (clause_type) WHERE superseded_at IS NULL;

-- Aurelia's starting playbook (we're the customer, buying services from vendors)
INSERT INTO playbook_rules (clause_type, standard, fallback, guidance, note, set_by)
SELECT * FROM (VALUES
    ('liability_cap',
     '{"min_cap": 2000000}'::jsonb, '{"min_cap": 1000000}'::jsonb,
     'Ask for a cap of at least $2M. Go down to $1M for smaller deals. Anything lower, or no cap at all, goes to the GC.',
     'Starting playbook', 'Aurelia Legal'),
    ('payment_terms',
     '{"min_net_days": 45}'::jsonb, '{"min_net_days": 30}'::jsonb,
     'We pay net 45 from a correct invoice. Net 30 is fine for small vendors. Shorter than net 30 needs Finance and GC sign-off.',
     'Starting playbook', 'Aurelia Legal'),
    ('governing_law',
     '{"jurisdictions": ["Delaware"]}'::jsonb, '{"jurisdictions": ["Delaware", "New York", "California"]}'::jsonb,
     'Delaware law. New York or California is fine if the vendor pushes. Anything else, including foreign law, goes to the GC.',
     'Starting playbook', 'Aurelia Legal'),
    ('indemnification',
     '{"mutual": true, "covers_ip": true}'::jsonb, '{"mutual": true, "covers_ip": false}'::jsonb,
     'Mutual indemnity, and the vendor covers IP infringement claims against us. We can drop the IP piece for low-risk services. One-way indemnity in the vendor''s favor goes to the GC.',
     'Starting playbook', 'Aurelia Legal'),
    ('term_renewal',
     '{"max_notice_days": 60, "max_renewal_months": 12}'::jsonb, '{"max_notice_days": 90, "max_renewal_months": 12}'::jsonb,
     'Fixed terms are best. If it auto-renews, renewals should be a year or less and we should only need 60 days'' notice to stop them. 90 days is the most we accept.',
     'Starting playbook', 'Aurelia Legal')
) AS defaults (clause_type, standard, fallback, guidance, note, set_by)
WHERE NOT EXISTS (SELECT 1 FROM playbook_rules);

COMMIT;