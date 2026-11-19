import { useEffect, useState } from 'react'
import type { useBulkReview, ReviewResult } from './bulkReview'
import CorrectionForm from './CorrectionForm'
import type { Term } from './format'
import GcSignOffForm from './GcSignOffForm'
import { BaselineConflictError, GcSignOffError, reviewClause } from './nonnaApi'
import type { GcSignOff, ReviewAction } from './nonnaApi'

type State =
  | { kind: 'idle' }
  | { kind: 'busy' }
  | { kind: 'conflict'; message: string }
  // Off the playbook: the approval waits for the GC's sign-off. Keeps the action and note
  // so an "approve as a change" doesn't lose its note.
  | { kind: 'signoff'; message?: string; action: ReviewAction; note?: string; busy?: boolean }
  | { kind: 'done'; message: string; approved: boolean }

interface Props {
  clauseId: number
  external?: ReviewResult // a result from "Approve all"
  onResolved?: () => void // tells the parent this clause is decided
  correct?: { clauseType: string; terms: Term[] } // shows "Fix value" when set
  needsSignOff?: boolean // off the playbook, so Approve asks for the GC's sign-off first
}

// Approve or reject one extracted clause. These buttons call the API directly,
// so the LLM never approves anything.
export default function ReviewControls({ clauseId, external, onResolved, correct, needsSignOff }: Props) {
  const [state, setState] = useState<State>({ kind: 'idle' })
  const [fixing, setFixing] = useState(false)
  const [note, setNote] = useState('')
  const [error, setError] = useState('')

  // Show results that came from "Approve all"
  useEffect(() => {
    if (!external) return
    if (external.kind === 'error') {
      setError(external.message)
    } else if (external.kind === 'signoff') {
      setError('')
      setState({ kind: 'signoff', message: external.message, action: 'approved' })
    } else {
      setError('')
      setState(external)
    }
  }, [external])

  async function submit(action: ReviewAction, withNote?: string, gcSignOff?: GcSignOff) {
    const previous = state
    setError('')
    setState(previous.kind === 'signoff' ? { ...previous, busy: true } : { kind: 'busy' })
    try {
      const outcome = await reviewClause(clauseId, action, withNote, undefined, gcSignOff)
      setState({ kind: 'done', message: outcome.message, approved: action !== 'rejected' })
      onResolved?.()
    } catch (err) {
      if (err instanceof BaselineConflictError) {
        setState({ kind: 'conflict', message: err.message })
      } else if (err instanceof GcSignOffError) {
        setState({ kind: 'signoff', message: err.message, action, note: withNote })
      } else {
        setError(err instanceof Error ? err.message : "Nonna couldn't save that decision.")
        if (previous.kind === 'signoff') setState({ ...previous, busy: false })
        else setState(previous.kind === 'conflict' ? previous : { kind: 'idle' })
      }
    }
  }

  function approve() {
    // We already know it's off the playbook, so ask for the sign-off before calling the API
    if (needsSignOff) setState({ kind: 'signoff', action: 'approved' })
    else void submit('approved')
  }

  function approveAsChange() {
    if (!note.trim()) {
      setError('Add a short note explaining why this change was agreed.')
      return
    }
    void submit('approved_change', note.trim())
  }

  if (state.kind === 'done') {
    return (
      <p className={state.approved ? 'review-done' : 'review-done review-rejected'}>
        {state.approved ? '✓' : '✕'} {state.message}
      </p>
    )
  }

  if (state.kind === 'signoff') {
    const { action, note: changeNote } = state
    return (
      <div className="review-controls">
        <GcSignOffForm
          message={state.message}
          submitLabel={action === 'approved_change' ? 'Approve as a change' : 'Approve with sign-off'}
          busy={Boolean(state.busy)}
          error={error}
          onSubmit={(signOff) => void submit(action, changeNote, signOff)}
          onCancel={() => {
            setError('')
            setState({ kind: 'idle' })
          }}
        />
      </div>
    )
  }

  if (fixing && correct) {
    return (
      <CorrectionForm
        clauseId={clauseId}
        clauseType={correct.clauseType}
        terms={correct.terms}
        onSaved={(message) => {
          setFixing(false)
          setState({ kind: 'done', message, approved: true })
          onResolved?.()
        }}
        onCancel={() => setFixing(false)}
      />
    )
  }

  return (
    <div className="review-controls">
      {state.kind === 'conflict' && (
        <>
          <p className="review-conflict">⚠ {state.message}</p>
          <textarea
            className="review-note"
            rows={2}
            value={note}
            onChange={(e) => {
              setNote(e.target.value)
              setError('')
            }}
            placeholder="Why was this change agreed?"
            aria-label="Note explaining the change"
          />
        </>
      )}

      <div className="intake-actions">
        {state.kind === 'conflict' ? (
          <button type="button" className="btn btn-sm btn-primary" onClick={approveAsChange}>
            Approve as a change
          </button>
        ) : (
          <button
            type="button"
            className="btn btn-sm btn-primary"
            disabled={state.kind === 'busy'}
            onClick={approve}
          >
            {needsSignOff ? 'Approve with GC sign-off' : 'Approve'}
          </button>
        )}
        <button
          type="button"
          className="btn btn-sm btn-quiet"
          disabled={state.kind === 'busy'}
          onClick={() => void submit('rejected')}
        >
          Reject
        </button>
        {correct && (
          <button
            type="button"
            className="btn btn-sm btn-quiet"
            disabled={state.kind === 'busy'}
            onClick={() => {
              setError('')
              setFixing(true)
            }}
          >
            Fix value
          </button>
        )}
      </div>

      {error && <p className="intake-error">{error}</p>}
    </div>
  )
}

// The "Approve all" button that sits above a list of extracted clauses
export function ApproveAllBar({ bulk }: { bulk: ReturnType<typeof useBulkReview> }) {
  if (bulk.pending.length < 2 && !bulk.summary) return null
  return (
    <div className="approve-all">
      {bulk.pending.length >= 2 && (
        <button
          type="button"
          className="btn btn-sm btn-primary"
          disabled={bulk.busy}
          onClick={() => void bulk.approveAll()}
        >
          {bulk.busy ? 'Approving…' : `Approve all (${bulk.pending.length})`}
        </button>
      )}
      {bulk.summary && <span className="approve-all-summary">{bulk.summary}</span>}
    </div>
  )
}