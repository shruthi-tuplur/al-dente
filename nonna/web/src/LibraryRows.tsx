// One version of a key term, as a compact row: where it's from and its value on one line,
// the status badges next to the value, and the extras (wording, fix) as quiet links on one line.
// Used by the Overview (versions of a term) and the Contracts tab (terms in a contract).
import { useState } from 'react'
import type { ReactNode } from 'react'
import ClauseBlock from './ClauseBlock'
import CorrectionForm, { canCorrect } from './CorrectionForm'
import { describeTerms } from './format'
import type { LibraryClause, PlaybookAssessment } from './nonnaApi'
import { ExceptionLine, PlaybookBadge } from './Playbook'

export interface Status {
  agreed: Set<number>
  superseded: Set<number>
  playbook: Record<string, PlaybookAssessment> // by clause id
}

export function clauseSummary(clause: LibraryClause): string {
  if (clause.presence === 'absent') return 'Not in this contract'
  if (clause.presence === 'incorporated_by_reference') return 'Follows the MSA'
  return describeTerms(clause.clause_type, clause.terms) ?? 'See wording'
}

export function statusBadge(clause: LibraryClause, status: Status) {
  if (status.agreed.has(clause.id)) return <span className="badge badge-agreed">Agreed</span>
  if (status.superseded.has(clause.id)) return <span className="badge">Earlier version</span>
  if (clause.review_status === 'pending') return <span className="badge badge-pending">Waiting for review</span>
  if (clause.review_status === 'rejected') return <span className="badge">Rejected</span>
  if (clause.review_status === 'corrected') return <span className="badge">Corrected</span>
  return <span className="badge">Approved</span>
}

export function ClauseRow({
  clause,
  contractId,
  status,
  title,
  onChanged,
}: {
  clause: LibraryClause
  contractId: number
  status: Status
  title: ReactNode
  onChanged: () => void
}) {
  const [open, setOpen] = useState<'wording' | 'fix' | null>(null)
  const [saved, setSaved] = useState('')
  const reviewed = clause.review_status === 'approved' || clause.review_status === 'corrected'
  const fixable = reviewed && canCorrect(clause.clause_type, clause.presence)
  const assessment = status.playbook[clause.id]
  // Only spell out the playbook when it matters: off playbook, or the GC signed off
  const playbookLine = assessment && (assessment.exception || assessment.tier === 'outside')

  function toggle(view: 'wording' | 'fix') {
    setSaved('')
    setOpen((current) => (current === view ? null : view))
  }

  return (
    <li className="lib-row">
      <div className="lib-row-main">
        <div className="lib-row-where">
          <span className="lib-row-title">{title}</span>
          <span className="lib-row-section">
            {clause.section_number ? `§${clause.section_number}` : 'No section'}
            {clause.heading ? ` · ${clause.heading}` : ''}
          </span>
        </div>
        <div className="lib-row-what">
          <span className="lib-row-value">{clauseSummary(clause)}</span>
          <span className="lib-row-badges">
            {assessment && <PlaybookBadge assessment={assessment} />}
            {statusBadge(clause, status)}
          </span>
        </div>
      </div>

      {playbookLine && (
        <p className="lib-row-note">
          {assessment.exception ? <ExceptionLine exception={assessment.exception} /> : assessment.reason}
        </p>
      )}

      {(clause.full_text || fixable) && (
        <div className="lib-row-actions">
          {clause.full_text && (
            <button type="button" className="lib-link" aria-expanded={open === 'wording'} onClick={() => toggle('wording')}>
              {open === 'wording' ? 'Hide wording' : 'Exact wording'}
            </button>
          )}
          {fixable && (
            <button type="button" className="lib-link" aria-expanded={open === 'fix'} onClick={() => toggle('fix')}>
              Fix value
            </button>
          )}
        </div>
      )}

      {saved && <p className="review-done">✓ {saved}</p>}
      {open === 'wording' && clause.full_text && <ClauseBlock text={clause.full_text} contractId={contractId} />}
      {open === 'fix' && (
        <CorrectionForm
          clauseId={clause.id}
          clauseType={clause.clause_type}
          terms={clause.terms}
          onSaved={(message) => {
            setOpen(null)
            setSaved(message)
            onChanged()
          }}
          onCancel={() => setOpen(null)}
        />
      )}
    </li>
  )
}