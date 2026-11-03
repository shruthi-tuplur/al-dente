import { useState } from 'react'
import { BaselineConflictError, reviewClause } from './nonnaApi'
import type { ReviewAction } from './nonnaApi'

type State =
  | { kind: 'idle' }
  | { kind: 'busy' }
  | { kind: 'conflict'; message: string }
  | { kind: 'done'; message: string; approved: boolean }

// Approve or reject one extracted clause. These buttons call the API directly,
// so the LLM never approves anything.
export default function ReviewControls({ clauseId }: { clauseId: number }) {
  const [state, setState] = useState<State>({ kind: 'idle' })
  const [note, setNote] = useState('')
  const [error, setError] = useState('')

  async function submit(action: ReviewAction, withNote?: string) {
    const previous = state
    setError('')
    setState({ kind: 'busy' })
    try {
      const outcome = await reviewClause(clauseId, action, withNote)
      setState({ kind: 'done', message: outcome.message, approved: action !== 'rejected' })
    } catch (err) {
      if (err instanceof BaselineConflictError) {
        setState({ kind: 'conflict', message: err.message })
      } else {
        setError(err instanceof Error ? err.message : "Nonna couldn't save that decision.")
        setState(previous.kind === 'conflict' ? previous : { kind: 'idle' })
      }
    }
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
            onClick={() => void submit('approved')}
          >
            Approve
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
      </div>

      {error && <p className="intake-error">{error}</p>}
    </div>
  )
}