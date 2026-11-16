// Aurelia's playbook: our standard positions, and how every vendor measures up.
// Every tier is worked out by the backend in code, never by the LLM.
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { formatDate } from './format'
import { CURRENT_USER, fetchPlaybook, updatePlaybookRule } from './nonnaApi'
import type { PlaybookAssessment, PlaybookCheck, PlaybookRule, Tier } from './nonnaApi'

export const TIER_LABELS: Record<Tier, string> = {
  standard: 'Standard',
  fallback: 'Fallback',
  outside: 'Off playbook',
  not_comparable: "Can't compare",
}

export function PlaybookBadge({ assessment }: { assessment: PlaybookAssessment }) {
  return (
    <span className={`badge badge-tier-${assessment.tier}`} title={assessment.reason}>
      {assessment.needs_sign_off ? 'Needs GC sign-off' : TIER_LABELS[assessment.tier]}
    </span>
  )
}

// What the email to the GC is about
export interface EmailContext {
  vendor: string
  term: string
  contract: { title: string; effective_date: string }
}

// A draft email to the GC, opened in the attorney's own email app. Nothing is sent by Nonna.
function gcEmailLink(assessment: PlaybookAssessment, about: EmailContext): string {
  const pending = assessment.needs_sign_off
  const subject = pending
    ? `GC sign-off needed: ${about.vendor} ${about.term.toLowerCase()}`
    : `Off-playbook term: ${about.vendor} ${about.term.toLowerCase()}`
  const lines = [
    'Hi,',
    '',
    pending
      ? `A new contract with ${about.vendor} has a term that's off our playbook, so I need your sign-off before I approve it.`
      : `Flagging an off-playbook term in our signed contract with ${about.vendor}, so we can raise it at renewal or renegotiation.`,
    '',
    `Contract: ${about.contract.title}, effective ${formatDate(about.contract.effective_date)}`,
    `Term: ${about.term}`,
    `What it says: ${assessment.value}`,
    `Why it's flagged: ${assessment.reason}`,
    ...(assessment.guidance ? [`Our playbook: ${assessment.guidance}`] : []),
    '',
    pending
      ? 'Can you let me know if this is okay to approve, and why? I\'ll record your answer in Nonna.'
      : 'Let me know if you want to handle this differently.',
    '',
    'Thanks!',
  ]
  return `mailto:?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(lines.join('\r\n'))}`
}

export function EmailGcLink({ assessment, about }: { assessment: PlaybookAssessment; about: EmailContext }) {
  if (assessment.tier !== 'outside') return null
  return (
    <a className="playbook-email" href={gcEmailLink(assessment, about)}>
      ✉ Email the GC
    </a>
  )
}

// The playbook result for one clause, with the reason when it isn't simply standard
export function PlaybookNote({
  assessment,
  about,
}: {
  assessment: PlaybookAssessment | null | undefined
  about?: EmailContext
}) {
  if (!assessment) return null
  return (
    <p className="playbook-note">
      <PlaybookBadge assessment={assessment} />
      {assessment.tier !== 'standard' && <span>{assessment.reason}</span>}
      {about && <EmailGcLink assessment={assessment} about={about} />}
    </p>
  )
}

// Every vendor down the side, every key term across the top
export function PlaybookMatrix({ data }: { data: PlaybookCheck }) {
  const columns = data.rules
  const flagged = data.rows.flatMap((row) =>
    columns
      .map((rule) => ({ rule, cell: row.cells[rule.clause_type] }))
      .filter(({ cell }) => cell && (cell.tier === 'outside' || cell.tier === 'not_comparable'))
      .map(({ rule, cell }) => ({ vendor: row.counterparty_name, rule, cell: cell! })),
  )

  return (
    <>
      <div className="playbook-table-wrap">
        <table className="playbook-table">
          <thead>
            <tr>
              <th scope="col">Vendor</th>
              {columns.map((rule) => (
                <th key={rule.clause_type} scope="col">
                  {rule.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row) => (
              <tr key={row.counterparty_id}>
                <th scope="row">{row.counterparty_name}</th>
                {columns.map((rule) => {
                  const cell = row.cells[rule.clause_type]
                  return (
                    <td key={rule.clause_type}>
                      {cell ? (
                        <>
                          <PlaybookBadge assessment={cell} />
                          <span className="playbook-cell-value">{cell.value}</span>
                        </>
                      ) : (
                        <span className="playbook-cell-empty">Nothing on file</span>
                      )}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {flagged.length > 0 && (
        <div className="playbook-flags-wrap">
          <p className="playbook-subhead">
            Needs a look <span className="lib-group-count">{flagged.length}</span>
          </p>
          <ul className="playbook-flags">
            {flagged.map(({ vendor, rule, cell }) => (
              <li key={`${vendor}-${rule.clause_type}`} className="playbook-flag">
                <div className="playbook-flag-head">
                  <PlaybookBadge assessment={cell} />
                  <span className="playbook-flag-vendor">{vendor}</span>
                  <span className="playbook-flag-term">{rule.label}</span>
                </div>
                <p className="playbook-flag-reason">{cell.reason}</p>
                <p className="playbook-flag-source">
                  From {cell.source.title}, {formatDate(cell.source.effective_date)}
                </p>
                <EmailGcLink assessment={cell} about={{ vendor, term: rule.label, contract: cell.source }} />
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  )
}

// The settings each rule has, matching RULE_FIELDS in playbook.py
type FieldKind = 'amount' | 'days' | 'months' | 'list' | 'yes_no'
const RULE_FIELDS: Record<string, { key: string; label: string; kind: FieldKind }[]> = {
  liability_cap: [{ key: 'min_cap', label: 'Cap of at least (USD)', kind: 'amount' }],
  payment_terms: [{ key: 'min_net_days', label: 'Net days, at least', kind: 'days' }],
  governing_law: [{ key: 'jurisdictions', label: 'Jurisdictions (comma separated)', kind: 'list' }],
  indemnification: [
    { key: 'mutual', label: 'Must be mutual', kind: 'yes_no' },
    { key: 'covers_ip', label: 'Must cover IP infringement', kind: 'yes_no' },
  ],
  term_renewal: [
    { key: 'max_notice_days', label: 'Notice to stop renewal, at most (days)', kind: 'days' },
    { key: 'max_renewal_months', label: 'Renewal period, at most (months)', kind: 'months' },
  ],
}

type Values = Record<string, string | boolean>

function toValues(rule: Record<string, unknown>, clauseType: string): Values {
  const values: Values = {}
  for (const field of RULE_FIELDS[clauseType] ?? []) {
    const value = rule[field.key]
    if (field.kind === 'yes_no') values[field.key] = value === true
    else if (field.kind === 'list') values[field.key] = Array.isArray(value) ? value.join(', ') : ''
    else values[field.key] = value == null ? '' : String(value)
  }
  return values
}

function RuleFields({
  clauseType,
  values,
  onChange,
}: {
  clauseType: string
  values: Values
  onChange: (values: Values) => void
}) {
  return (
    <div className="correction-fields">
      {(RULE_FIELDS[clauseType] ?? []).map((field) =>
        field.kind === 'yes_no' ? (
          <label key={field.key} className="correction-field">
            {field.label}
            <select
              value={values[field.key] ? 'yes' : 'no'}
              onChange={(e) => onChange({ ...values, [field.key]: e.target.value === 'yes' })}
            >
              <option value="yes">Yes</option>
              <option value="no">No</option>
            </select>
          </label>
        ) : (
          <label key={field.key} className="correction-field">
            {field.label}
            <input
              type="text"
              inputMode={field.kind === 'list' ? 'text' : 'numeric'}
              value={String(values[field.key] ?? '')}
              onChange={(e) => onChange({ ...values, [field.key]: e.target.value })}
            />
          </label>
        ),
      )}
    </div>
  )
}

function RuleCard({ rule, onSaved }: { rule: PlaybookRule; onSaved: () => void }) {
  const [editing, setEditing] = useState(false)
  const [standard, setStandard] = useState<Values>({})
  const [fallback, setFallback] = useState<Values>({})
  const [guidance, setGuidance] = useState('')
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  function startEditing() {
    setStandard(toValues(rule.standard, rule.clause_type))
    setFallback(toValues(rule.fallback, rule.clause_type))
    setGuidance(rule.guidance)
    setNote('')
    setError('')
    setEditing(true)
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!note.trim()) {
      setError('Say why the playbook is changing.')
      return
    }
    setSaving(true)
    setError('')
    try {
      await updatePlaybookRule(rule.clause_type, { standard, fallback, guidance, note, set_by: CURRENT_USER })
      setEditing(false)
      onSaved()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save that.")
    } finally {
      setSaving(false)
    }
  }

  return (
    <li className="playbook-rule">
      <p className="playbook-rule-title">{rule.label}</p>
      <dl className="playbook-rule-tiers">
        <div>
          <dt>
            <span className="badge badge-tier-standard">Standard</span>
          </dt>
          <dd>{rule.standard_text}</dd>
        </div>
        <div>
          <dt>
            <span className="badge badge-tier-fallback">Fallback</span>
          </dt>
          <dd>{rule.fallback_text}</dd>
        </div>
      </dl>
      <p className="playbook-guidance">{rule.guidance}</p>
      <p className="quote">
        Version {rule.version} · set by {rule.set_by} on {formatDate(rule.set_at.slice(0, 10))}
        {rule.note ? ` · ${rule.note}` : ''}
      </p>

      {!editing ? (
        <button type="button" className="lib-fix" onClick={startEditing}>
          Edit rule
        </button>
      ) : (
        <form className="correction-form" onSubmit={save}>
          <p className="correction-title">Standard (what we ask for)</p>
          <RuleFields clauseType={rule.clause_type} values={standard} onChange={setStandard} />
          <p className="correction-title">Fallback (the least we accept without the GC)</p>
          <RuleFields clauseType={rule.clause_type} values={fallback} onChange={setFallback} />
          <label className="correction-field">
            Guidance for attorneys
            <textarea className="review-note" rows={3} value={guidance} onChange={(e) => setGuidance(e.target.value)} />
          </label>
          <label className="correction-field">
            Why is this changing? (required)
            <input type="text" value={note} onChange={(e) => setNote(e.target.value)} placeholder="GC approved a lower cap for small vendors" />
          </label>
          {error && <p className="intake-error">⚠ {error}</p>}
          <div className="playbook-actions">
            <button type="submit" className="btn btn-sm btn-primary" disabled={saving}>
              {saving ? 'Saving…' : 'Save new version'}
            </button>
            <button type="button" className="btn btn-sm btn-quiet" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}
    </li>
  )
}

export default function Playbook() {
  const [data, setData] = useState<PlaybookCheck | null>(null)
  const [error, setError] = useState('')
  const [loadCount, setLoadCount] = useState(0)

  useEffect(() => {
    let current = true
    setError('')
    fetchPlaybook()
      .then((result) => current && setData(result))
      .catch((err: unknown) => current && setError(err instanceof Error ? err.message : "Couldn't load the playbook."))
    return () => {
      current = false
    }
  }, [loadCount])

  return (
    <div className="review-page playbook-page">
      <header className="review-header">
        <div>
          <p className="card-title lib-title">Aurelia's playbook</p>
          <p className="card-subtitle">
            {data === null
              ? 'Loading…'
              : `${data.rows.length} vendors checked · ${data.outside_count} ${
                  data.outside_count === 1 ? 'term' : 'terms'
                } off playbook`}
          </p>
        </div>
        <button type="button" className="btn btn-sm btn-quiet" onClick={() => setLoadCount((n) => n + 1)}>
          Refresh
        </button>
      </header>

      {error && <p className="intake-error">⚠ {error}</p>}

      {data && (
        <>
          <section className="lib-group">
            <h3 className="lib-group-title">Vendors vs our playbook</h3>
            <p className="playbook-intro">
              Each vendor's agreed master-agreement terms. These contracts are already signed, so
              raise anything off playbook at renewal or renegotiation. New terms that are off playbook
              need GC sign-off in Review before anyone approves them.
            </p>
            <PlaybookMatrix data={data} />
          </section>

          <section className="lib-group">
            <h3 className="lib-group-title">Our standard positions</h3>
            <ul className="playbook-rules">
              {data.rules.map((rule) => (
                <RuleCard key={rule.clause_type} rule={rule} onSaved={() => setLoadCount((n) => n + 1)} />
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  )
}
