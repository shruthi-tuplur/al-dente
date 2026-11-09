import { useEffect, useState } from 'react'
import { useBulkReview } from './bulkReview'
import ClauseBlock from './ClauseBlock'
import { canCorrect } from './CorrectionForm'
import { clauseLabel, describeTerms, formatDate } from './format'
import { fetchReviewQueue } from './nonnaApi'
import type { LibraryClause, QueueItem } from './nonnaApi'
import ReviewControls, { ApproveAllBar } from './ReviewControls'

function valueOf(clause: LibraryClause): string {
  if (clause.presence === 'absent') return 'Not in this contract'
  if (clause.presence === 'incorporated_by_reference') return 'Follows the MSA'
  return describeTerms(clause.clause_type, clause.terms) ?? 'See wording'
}

// How this clause compares to what's already agreed with the vendor
function Comparison({ item }: { item: QueueItem }) {
  if (item.clause.presence === 'incorporated_by_reference') {
    return <p className="quote">Uses the terms already agreed in the MSA.</p>
  }
  if (!item.agreed) {
    return <p className="quote">Nothing agreed yet for this. Approving it sets the baseline.</p>
  }
  return (
    <p className="review-compare">
      <span>
        Agreed now: <strong>{valueOf(item.agreed.clause)}</strong> · from {item.agreed.source.title}
      </span>
      {item.matches_agreed === true && <span className="badge badge-agreed">Matches</span>}
      {item.matches_agreed === false && <span className="badge badge-differs">Different</span>}
    </p>
  )
}

function ContractGroup({ items, onDecided }: { items: QueueItem[]; onDecided: () => void }) {
  const bulk = useBulkReview(items.map((item) => item.clause.id))
  const { source } = items[0]

  return (
    <section className="review-contract">
      <div className="review-contract-head">
        <p className="review-contract-title">{source.title}</p>
        <span className="card-meta">{formatDate(source.effective_date)}</span>
      </div>
      <ApproveAllBar bulk={bulk} />
      <ul className="card-rows">
        {items.map((item) => (
          <li key={item.clause.id} className="review-item">
            <div className="card-row">
              <span className="card-label">{clauseLabel(item.clause.clause_type)}</span>
              <span className="card-value">{valueOf(item.clause)}</span>
            </div>
            <Comparison item={item} />
            <span className="quote">
              {item.clause.section_number ? `§${item.clause.section_number}` : 'No section'}
              {item.clause.heading ? ` · ${item.clause.heading}` : ''}
              {item.clause.extraction_method === 'llm' ? ' · read by Claude' : ''}
            </span>
            {item.clause.full_text && (
              <details className="lib-wording">
                <summary>Show exact wording</summary>
                <ClauseBlock text={item.clause.full_text} />
              </details>
            )}
            <ReviewControls
              clauseId={item.clause.id}
              external={bulk.results[item.clause.id]}
              onResolved={() => {
                bulk.markResolved(item.clause.id)
                onDecided()
              }}
              correct={
                canCorrect(item.clause.clause_type, item.clause.presence)
                  ? { clauseType: item.clause.clause_type, terms: item.clause.terms }
                  : undefined
              }
            />
          </li>
        ))}
      </ul>
    </section>
  )
}

// Everything waiting for an attorney, grouped by vendor and then by contract
export default function Review({ onDecided }: { onDecided: () => void }) {
  const [queue, setQueue] = useState<QueueItem[] | null>(null)
  const [error, setError] = useState('')
  const [loadCount, setLoadCount] = useState(0)

  useEffect(() => {
    let current = true
    setError('')
    fetchReviewQueue()
      .then((items) => current && setQueue(items))
      .catch((err: unknown) => current && setError(err instanceof Error ? err.message : "Couldn't load the review queue."))
    return () => {
      current = false
    }
  }, [loadCount])

  // vendor name → contract id → items, keeping the queue's order
  const vendors = new Map<string, Map<number, QueueItem[]>>()
  for (const item of queue ?? []) {
    const contracts = vendors.get(item.counterparty_name) ?? new Map<number, QueueItem[]>()
    contracts.set(item.source.id, [...(contracts.get(item.source.id) ?? []), item])
    vendors.set(item.counterparty_name, contracts)
  }
  const differing = (queue ?? []).filter((item) => item.matches_agreed === false).length

  return (
    <div className="review-page">
      <header className="review-header">
        <div>
          <p className="card-title lib-title">Waiting for review</p>
          <p className="card-subtitle">
            {queue === null
              ? 'Loading…'
              : queue.length === 0
                ? 'Nothing waiting. Every extracted term has been reviewed.'
                : `${queue.length} ${queue.length === 1 ? 'term' : 'terms'} to check${
                    differing ? ` · ${differing} ${differing === 1 ? 'differs' : 'differ'} from what's agreed` : ''
                  }`}
          </p>
        </div>
        <button type="button" className="btn btn-sm btn-quiet" onClick={() => setLoadCount((n) => n + 1)}>
          Refresh
        </button>
      </header>

      {error && <p className="intake-error">⚠ {error}</p>}

      {[...vendors.entries()].map(([vendor, contracts]) => (
        <section key={vendor} className="lib-group">
          <h3 className="lib-group-title">{vendor}</h3>
          {[...contracts.entries()].map(([contractId, items]) => (
            <ContractGroup key={contractId} items={items} onDecided={onDecided} />
          ))}
        </section>
      ))}
    </div>
  )
}