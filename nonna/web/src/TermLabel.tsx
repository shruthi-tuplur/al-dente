// A term's name with a plain-English hint on hover (or on tap / keyboard focus).
// The meanings live in format.ts, the same ones the one-pager prints.
import type { ReactNode } from 'react'
import { CLAUSE_MEANINGS, clauseLabel } from './format'
import type { ClauseType } from './format'

export default function TermLabel({ type, children }: { type: string; children?: ReactNode }) {
  const label = children ?? clauseLabel(type)
  const meaning = CLAUSE_MEANINGS[type as ClauseType]
  if (!meaning) return <>{label}</>
  return (
    <span className="term-hint" tabIndex={0}>
      {label}
      <span className="term-hint-bubble" role="tooltip">
        {meaning}
      </span>
    </span>
  )
}