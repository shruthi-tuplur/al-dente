import { useState } from 'react'
import GcSignOffForm from './GcSignOffForm'
import { BaselineConflictError, GcSignOffError, reviewClause } from './nonnaApi'
import type { Corrections, GcSignOff } from './nonnaApi'
import type { Term } from './format'

// One field an attorney can fix, per clause type
type Field =
  | { key: string; label: string; kind: 'amount' | 'days' | 'text' | 'months' | 'years'; placeholder: string }
  | { key: string; label: string; kind: 'date' }
  | { key: string; label: string; kind: 'choice'; options: { value: string; label: string }[] }
  | { key: string; label: string; kind: 'yes_no' }

const FIELDS: Record<string, Field[]> = {
  liability_cap: [{ key: 'cap_amount', label: 'Cap amount', kind: 'amount', placeholder: '3000000' }],
  payment_terms: [
    { key: 'net_days', label: 'Net days', kind: 'days', placeholder: '45' },
    {
      key: 'payment_structure',
      label: 'Billing',
      kind: 'choice',
      options: [
        { value: 'invoice', label: 'On invoice' },
        { value: 'milestone', label: 'Milestone billing' },
      ],
    },
  ],
  governing_law: [{ key: 'jurisdiction', label: 'Jurisdiction', kind: 'text', placeholder: 'Delaware' }],
  indemnification: [
    { key: 'is_mutual', label: 'Mutual (both sides indemnify)', kind: 'yes_no' },
    { key: 'covers_ip_infringement', label: 'Covers IP infringement', kind: 'yes_no' },
  ],
  term_renewal: [
    { key: 'initial_term_months', label: 'Initial term (months)', kind: 'months', placeholder: '36' },
    { key: 'end_date', label: 'Or a fixed end date', kind: 'date' },
    { key: 'auto_renews', label: 'Renews automatically', kind: 'yes_no' },
    { key: 'renewal_term_months', label: 'Renewal period (months)', kind: 'months', placeholder: '12' },
    { key: 'notice_days', label: 'Notice to stop renewal (days)', kind: 'days', placeholder: '90' },
],
termination_convenience: [
  {
    key: 'who_may_terminate',
    label: 'Who can terminate',
    kind: 'choice',
    options: [
      { value: 'either', label: 'Either side' },
      { value: 'aurelia', label: 'Only us' },
      { value: 'vendor', label: 'Only the vendor' },
    ],
  },
  { key: 'notice_days', label: 'Notice needed (days)', kind: 'days', placeholder: '90' },
],
confidentiality: [
  { key: 'survival_years', label: 'Years after it ends', kind: 'years', placeholder: '7' },
  { key: 'perpetual', label: 'Lasts forever', kind: 'yes_no' },
  { key: 'trade_secrets_indefinite', label: 'Trade secrets kept as long as they stay secret', kind: 'yes_no' },
],
insurance: [
  { key: 'general_liability_per_occurrence', label: 'General liability per occurrence (USD)', kind: 'amount', placeholder: '2000000' },
  { key: 'general_liability_aggregate', label: 'General liability aggregate (USD)', kind: 'amount', placeholder: '5000000' },
  { key: 'products_liability_limit', label: 'Products liability (USD)', kind: 'amount', placeholder: '5000000' },
  { key: 'professional_liability_limit', label: 'Professional liability (USD)', kind: 'amount', placeholder: '3000000' },
  { key: 'years_after_term', label: 'Keep coverage for (years after it ends)', kind: 'years', placeholder: '3' },
],
}

// Optional fields can be left blank (a term with no renewal has no renewal period)
const OPTIONAL = new Set([
'initial_term_months',
'end_date',
'renewal_term_months',
'notice_days',
'survival_years',
'general_liability_per_occurrence',
'general_liability_aggregate',
'products_liability_limit',
'professional_liability_limit',
'years_after_term',
])
export function canCorrect(clauseType: string, presence: string): boolean {
  return clauseType in FIELDS && presence === 'present'
}

function startingValues(fields: Field[], terms: Term[]): Corrections {
  const values: Corrections = {}
  for (const field of fields) {
    const term = terms.find((t) => t.term_key === field.key)
    if (field.kind === 'yes_no') values[field.key] = term?.value === true
    else if (field.kind === 'date') values[field.key] = (term?.value as string | null) ?? ''
    else if (field.kind === 'choice') values[field.key] = (term?.value as string | null) ?? field.options[0].value
    else {
      const value = term?.value
      // Numbers come from the API as strings like "2500000"; show them without trailing zeros
      values[field.key] = value == null ? '' : String(Number(value) || value)
    }
  }
  return values
}

interface Props {
  clauseId: number
  clauseType: string
  terms: Term[]
  onSaved: (message: string) => void
  onCancel: () => void
}

// Fix a value Nonna extracted wrong. The original value stays in the decision history,
// and the fix still goes through the same check against the agreed baseline.
export default function CorrectionForm({ clauseId, clauseType, terms, onSaved, onCancel }: Props) {
  const fields = FIELDS[clauseType] ?? []
  const [values, setValues] = useState<Corrections>(() => startingValues(fields, terms))
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [conflict, setConflict] = useState('')
  // The fixed value is off the playbook, so saving it needs the GC's sign-off
  const [signOff, setSignOff] = useState<{ message: string; asChange: boolean } | null>(null)
  const [error, setError] = useState('')

  function update(key: string, value: string | boolean) {
    setValues((current) => ({ ...current, [key]: value }))
    setConflict('')
    setSignOff(null)
    setError('')
  }

  async function save(asChange: boolean, gcSignOff?: GcSignOff) {
    const missing = fields.find(
        (f) => f.kind !== 'yes_no' && !OPTIONAL.has(f.key) && String(values[f.key]).trim() === '',
      )
    if (missing) {
      setError(`Fill in the ${missing.label.toLowerCase()}.`)
      return
    }
    if (!note.trim()) {
      setError('Add a short note saying what Nonna got wrong.')
      return
    }
    setBusy(true)
    setError('')
    try {
            // Leave out optional fields that were left blank
            const filled = Object.fromEntries(Object.entries(values).filter(([, v]) => v !== ''))
            const outcome = await reviewClause(clauseId, 'corrected', note.trim(), { values: filled, asChange }, gcSignOff)
      onSaved(outcome.message)
    } catch (err) {
      if (err instanceof BaselineConflictError) setConflict(err.message)
      else if (err instanceof GcSignOffError) setSignOff({ message: err.message, asChange })
      else setError(err instanceof Error ? err.message : "Nonna couldn't save that correction.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <form
      className="correction-form"
      onSubmit={(e) => {
        e.preventDefault()
        void save(false)
      }}
    >
      <p className="correction-title">Fix what Nonna pulled out</p>
      <div className="correction-fields">
        {fields.map((field) => {
          const id = `fix-${clauseId}-${field.key}`
          return (
            <label key={field.key} htmlFor={id} className="correction-field">
              <span>{field.label}</span>
              {field.kind === 'yes_no' ? (
                <select
                  id={id}
                  value={values[field.key] ? 'yes' : 'no'}
                  onChange={(e) => update(field.key, e.target.value === 'yes')}
                >
                  <option value="yes">Yes</option>
                  <option value="no">No</option>
                </select>
              ) : field.kind === 'choice' ? (
                <select id={id} value={String(values[field.key])} onChange={(e) => update(field.key, e.target.value)}>
                  {field.options.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              ) : field.kind === 'date' ? (
                 <input id={id} type="date" value={String(values[field.key])} onChange={(e) => update(field.key, e.target.value)} />
              ) : (
                <input
                  id={id}
                  type="text"
                  inputMode={field.kind === 'text' ? 'text' : 'numeric'}
                  value={String(values[field.key])}
                  placeholder={field.placeholder}
                  onChange={(e) => update(field.key, e.target.value)}
                />
              )}
            </label>
          )
        })}
      </div>

      <textarea
        id={`fix-${clauseId}-note`}
        className="review-note"
        rows={2}
        value={note}
        onChange={(e) => {
          setNote(e.target.value)
          setError('')
        }}
        placeholder="What did Nonna get wrong? For example: misread §11.2, the cap is $25M."
        aria-label="Note explaining the correction"
      />

{conflict && !signOff && <p className="review-conflict">⚠ {conflict}</p>}

{signOff ? (
  <GcSignOffForm
    message={signOff.message}
    submitLabel="Save with sign-off"
    busy={busy}
    error={error}
    onSubmit={(gc) => void save(signOff.asChange, gc)}
    onCancel={() => {
      setSignOff(null)
      setError('')
    }}
  />
) : (
  <div className="intake-actions">
    {conflict ? (
      <button type="button" className="btn btn-sm btn-primary" disabled={busy} onClick={() => void save(true)}>
        Save as a change
      </button>
    ) : (
      <button type="submit" className="btn btn-sm btn-primary" disabled={busy}>
        {busy ? 'Saving…' : 'Save correction'}
      </button>
    )}
    <button type="button" className="btn btn-sm btn-quiet" disabled={busy} onClick={onCancel}>
      Cancel
    </button>
  </div>
)}

{error && !signOff && <p className="intake-error">{error}</p>}
</form>
  )
}