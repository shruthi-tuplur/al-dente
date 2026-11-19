// Record the GC's sign-off on a term that's off Aurelia's playbook: who, when, and why.
// Used in Review (approving a new term) and on the Playbook page (a signed term).
// A div, not a form, because it can sit inside the correction form.
import { useState } from 'react'
import { todayISO } from './format'
import type { GcSignOff } from './nonnaApi'

interface Props {
  message?: string // why the sign-off is needed, shown above the form
  submitLabel: string
  busy: boolean
  error?: string
  onSubmit: (signOff: GcSignOff) => void
  onCancel: () => void
}

export default function GcSignOffForm({ message, submitLabel, busy, error, onSubmit, onCancel }: Props) {
  const [approvedBy, setApprovedBy] = useState('')
  const [approvedOn, setApprovedOn] = useState(todayISO())
  const [note, setNote] = useState('')
  const [missing, setMissing] = useState('')

  function submit() {
    if (!approvedBy.trim()) return setMissing('Say which GC signed off.')
    if (!approvedOn) return setMissing('Add the date the GC signed off.')
    if (approvedOn > todayISO()) return setMissing("The sign-off date can't be in the future.")
    if (!note.trim()) return setMissing('Say why the GC signed off.')
    setMissing('')
    onSubmit({ approved_by: approvedBy.trim(), approved_on: approvedOn, note: note.trim() })
  }

  return (
    <div className="gc-signoff">
      {message && <p className="review-conflict">⚠ {message}</p>}
      <p className="correction-title">GC sign-off</p>
      <div className="correction-fields">
        <label className="correction-field">
          <span>GC who signed off</span>
          <input type="text" value={approvedBy} onChange={(e) => setApprovedBy(e.target.value)} placeholder="Dana Reyes" />
        </label>
        <label className="correction-field">
          <span>Date</span>
          <input type="date" value={approvedOn} max={todayISO()} onChange={(e) => setApprovedOn(e.target.value)} />
        </label>
      </div>
      <label className="correction-field">
        <span>Why the GC said yes</span>
        <textarea
          className="review-note"
          rows={2}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Small, low-risk engagement. A $500K cap covers the fees many times over."
        />
      </label>
      {(missing || error) && <p className="intake-error">{missing || error}</p>}
      <div className="intake-actions">
        <button type="button" className="btn btn-sm btn-primary" disabled={busy} onClick={submit}>
          {busy ? 'Saving…' : submitLabel}
        </button>
        <button type="button" className="btn btn-sm btn-quiet" disabled={busy} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  )
}