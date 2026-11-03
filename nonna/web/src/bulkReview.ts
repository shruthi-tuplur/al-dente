import { useState } from 'react'
import { BaselineConflictError, reviewClause } from './nonnaApi'

export type ReviewResult =
  | { kind: 'done'; message: string; approved: boolean }
  | { kind: 'conflict'; message: string }
  | { kind: 'error'; message: string }

// "Approve all" for a group of extracted clauses. Approves them one at a time
// (so baselines are never created twice at once), and anything that conflicts
// with an agreed baseline is flagged instead of approved.
export function useBulkReview(clauseIds: number[]) {
  const [results, setResults] = useState<Record<number, ReviewResult>>({})
  const [resolved, setResolved] = useState<Set<number>>(new Set())
  const [busy, setBusy] = useState(false)
  const [summary, setSummary] = useState('')

  const flagged = new Set(
    Object.entries(results)
      .filter(([, r]) => r.kind === 'conflict')
      .map(([id]) => Number(id)),
  )
  const pending = clauseIds.filter((id) => !resolved.has(id) && !flagged.has(id))

  function markResolved(clauseId: number) {
    setResolved((prev) => new Set(prev).add(clauseId))
  }

  async function approveAll() {
    setBusy(true)
    setSummary('')
    let approved = 0
    let needsAttention = 0

    for (const clauseId of pending) {
      try {
        const outcome = await reviewClause(clauseId, 'approved')
        setResults((prev) => ({
          ...prev,
          [clauseId]: { kind: 'done', message: outcome.message, approved: true },
        }))
        markResolved(clauseId)
        approved += 1
      } catch (err) {
        needsAttention += 1
        const result: ReviewResult =
          err instanceof BaselineConflictError
            ? { kind: 'conflict', message: err.message }
            : { kind: 'error', message: err instanceof Error ? err.message : "Couldn't save that decision." }
        setResults((prev) => ({ ...prev, [clauseId]: result }))
      }
    }

    setSummary(
      needsAttention === 0
        ? `✓ Approved ${approved}.`
        : `✓ Approved ${approved}. ⚠ ${needsAttention} ${needsAttention === 1 ? 'needs' : 'need'} your attention below.`,
    )
    setBusy(false)
  }

  return { results, pending, markResolved, approveAll, busy, summary }
}