// The cards that show up under Nonna's replies. Every value here comes straight
// from the database through the API, never from the LLM's own words.
import type { ReactNode } from 'react'
import { useBulkReview } from './bulkReview'
import ClauseBlock from './ClauseBlock'
import ReviewControls, { ApproveAllBar } from './ReviewControls'
import {
  CONTRACT_TYPE_LABELS,
  clauseLabel,
  describeTerms,
  formatDate,
} from './format'
import type { Term } from './format'
import type { Card } from './nonnaApi'

interface Source {
  id: number
  contract_type: string
  title: string
  effective_date: string
}

interface ClauseData {
  id: number
  clause_type: string
  section_number: string | null
  heading: string | null
  full_text: string | null
  presence: string
  review_status: string
  terms: Term[]
}

interface Position {
  id: number
  clause_type: string
  set_by: string
  set_at: string
  note: string | null
  source: Source
  clause: ClauseData
}

interface ContractData {
  id: number
  contract_type: string
  title: string
  effective_date: string
  status: string
  signed_by_entity: string
  parent_contract_id: number | null
  amends_contract_id: number | null
}

interface Decision {
  id: number
  action: string
  note: string | null
  reviewer: string
  created_at: string
}

interface HistoryEntry {
  source: Source
  clause: ClauseData
  decisions: Decision[]
}

interface QueueItem {
  counterparty_name: string
  source: Source
  clause: ClauseData
}

interface ProfileData {
  counterparty: {
    name: string
    entities: { id: number; legal_name: string }[]
    contracts: ContractData[]
  }
  positions: Position[]
  pending_review: number
}

function sourceLine(source: Source, clause: ClauseData): string {
  const type = CONTRACT_TYPE_LABELS[source.contract_type] ?? source.contract_type
  return `${type}${clause.section_number ? ` §${clause.section_number}` : ''} · ${formatDate(source.effective_date)}`
}

function clauseValue(clause: ClauseData): string {
  if (clause.presence === 'absent') return 'Not in this contract'
  if (clause.presence === 'incorporated_by_reference') return 'Follows the MSA'
  return describeTerms(clause.clause_type, clause.terms) ?? 'See clause text'
}

function TermRows({ positions }: { positions: Position[] }) {
  if (positions.length === 0) {
    return <p className="card-empty">No agreed terms yet.</p>
  }
  return (
    <ul className="card-rows">
      {positions.map((p) => (
        <li key={p.id}>
          <div className="card-row">
            <span className="card-label">{clauseLabel(p.clause_type)}</span>
            <span className="card-value">{clauseValue(p.clause)}</span>
          </div>
          <span className="quote">{sourceLine(p.source, p.clause)}</span>
        </li>
      ))}
    </ul>
  )
}

function DocumentRow({ contract, nested }: { contract: ContractData; nested: boolean }) {
  return (
    <li className={nested ? 'doc doc-nested' : 'doc'}>
      <div className="card-row">
        <span>
          <span className="doc-type">{CONTRACT_TYPE_LABELS[contract.contract_type] ?? contract.contract_type}</span>
          {contract.title}
        </span>
        <span className="card-meta">{formatDate(contract.effective_date)}</span>
      </div>
      <span className="quote">
        Signed by {contract.signed_by_entity}
        {contract.status !== 'active' ? ` · ${contract.status}` : ''}
      </span>
    </li>
  )
}

// Contracts in order, with SOWs and amendments tucked under the contract they belong to
function DocumentList({ contracts }: { contracts: ContractData[] }) {
  const ids = new Set(contracts.map((c) => c.id))
  const parentOf = (c: ContractData) => c.parent_contract_id ?? c.amends_contract_id
  const topLevel = contracts.filter((c) => {
    const parent = parentOf(c)
    return parent === null || !ids.has(parent)
  })

  return (
    <ul className="card-rows">
      {topLevel.map((contract) => (
        <li key={contract.id} className="doc-group">
          <ul className="card-rows">
            <DocumentRow contract={contract} nested={false} />
            {contracts
              .filter((c) => parentOf(c) === contract.id)
              .map((child) => (
                <DocumentRow key={child.id} contract={child} nested />
              ))}
          </ul>
        </li>
      ))}
    </ul>
  )
}

function ProfileCard({ data }: { data: ProfileData }) {
  const { counterparty, positions, pending_review } = data
  const contractCount = counterparty.contracts.length
  const entityCount = counterparty.entities.length
  return (
    <>
      <p className="card-title">{counterparty.name}</p>
      <p className="card-subtitle">
        {contractCount} {contractCount === 1 ? 'contract' : 'contracts'} · {entityCount} signing{' '}
        {entityCount === 1 ? 'entity' : 'entities'}
      </p>

      <p className="card-section">Agreed terms</p>
      <TermRows positions={positions} />

      <p className="card-section">Documents</p>
      <DocumentList contracts={counterparty.contracts} />

      {pending_review > 0 && (
        <p className="card-pending">
          ⏳ {pending_review} extracted {pending_review === 1 ? 'term is' : 'terms are'} waiting for review
        </p>
      )}
    </>
  )
}

function HistoryCard({ entries }: { entries: HistoryEntry[] }) {
  if (entries.length === 0) return <p className="card-empty">No history yet.</p>
  return (
    <ol className="timeline">
      {entries.map((entry) => (
        <li key={entry.clause.id}>
          <div className="card-row">
            <span>{entry.source.title}</span>
            <span className="card-value">{clauseValue(entry.clause)}</span>
          </div>
          <span className="quote">
            {sourceLine(entry.source, entry.clause)}
            {entry.clause.review_status === 'pending' ? ' · waiting for review' : ''}
          </span>
          {entry.decisions
            .filter((d) => d.note)
            .map((d) => (
              <span key={d.id} className="decision-note">
                "{d.note}" · {d.reviewer}
              </span>
            ))}
        </li>
      ))}
    </ol>
  )
}

interface ClauseTextData {
    source: Source
    clause: ClauseData
    is_agreed: boolean
    applies_to: string[] | null
  }
  
function ClauseCard({ items }: { items: ClauseTextData[] }) {
    return (
      <ul className="card-rows clause-list">
        {items.map((item) => (
          <li key={item.clause.id}>
            <div className="card-row">
              <span className="card-label">
                {item.source.title}
                {item.clause.section_number ? ` · §${item.clause.section_number}` : ''}
              </span>
              <span className={item.is_agreed ? 'badge badge-agreed' : 'badge'}>
                {item.is_agreed ? 'Agreed' : item.clause.review_status === 'pending' ? 'Waiting for review' : item.clause.review_status}
              </span>
            </div>
            <span className="quote">
              {formatDate(item.source.effective_date)}
              {item.applies_to ? ` · applies to ${item.applies_to.join(', ')}` : ''}
            </span>
            {item.clause.full_text ? (
              <ClauseBlock text={item.clause.full_text} />
            ) : (
              <p className="card-empty">{clauseValue(item.clause)}</p>
            )}
          </li>
        ))}
      </ul>
    )
  }

function ReviewQueueCard({ items }: { items: QueueItem[] }) {
    const bulk = useBulkReview(items.map((item) => item.clause.id))
    if (items.length === 0) return <p className="card-empty">Nothing is waiting for review.</p>
    return (
      <>
        <ApproveAllBar bulk={bulk} />
        <ul className="card-rows">
          {items.map((item) => (
            <li key={item.clause.id}>
              <div className="card-row">
                <span className="card-label">
                  {clauseLabel(item.clause.clause_type)} · {item.counterparty_name}
                </span>
                <span className="card-value">{clauseValue(item.clause)}</span>
              </div>
              <span className="quote">
                {item.source.title} · {sourceLine(item.source, item.clause)}
              </span>
              <ReviewControls
                clauseId={item.clause.id}
                external={bulk.results[item.clause.id]}
                onResolved={() => bulk.markResolved(item.clause.id)}
              />
            </li>
          ))}
        </ul>
      </>
    )
  }

export default function CardView({ card }: { card: Card }) {
  let body: ReactNode = null
  switch (card.type) {
    case 'profile':
      body = <ProfileCard data={card.data as ProfileData} />
      break
    case 'clause':
      body = <ClauseCard items={card.data as ClauseTextData[]} />
      break
    case 'positions':
      body = <TermRows positions={card.data as Position[]} />
      break
    case 'history':
      body = <HistoryCard entries={card.data as HistoryEntry[]} />
      break
    case 'contracts':
      body = <DocumentList contracts={(card.data as ProfileData['counterparty']).contracts} />
      break
    case 'review_queue':
      body = <ReviewQueueCard items={card.data as QueueItem[]} />
      break
  }

  return (
    <section className="nonna-card" aria-label={card.title}>
      {card.type !== 'profile' && <p className="card-title">{card.title}</p>}
      {body}
    </section>
  )
}