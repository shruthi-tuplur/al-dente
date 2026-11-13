// The cards that show up under Nonna's replies. Every value here comes straight
// from the database through the API, never from the LLM's own words.
import type { ReactNode } from 'react'
import { useBulkReview } from './bulkReview'
import ClauseBlock from './ClauseBlock'
import { canCorrect } from './CorrectionForm'
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

  interface SectionTextData {
    source: Source
    section: {
      id: number
      category: string
      section_number: string | null
      heading: string | null
      full_text: string
    }
  }
  
  function SectionCard({ items }: { items: SectionTextData[] }) {
    return (
      <ul className="card-rows clause-list">
        {items.map((item) => (
          <li key={item.section.id}>
            <div className="card-row">
              <span className="card-label">
                {item.source.title}
                {item.section.section_number ? ` · §${item.section.section_number}` : ''}
              </span>
              <span className="badge">As written</span>
            </div>
            <span className="quote">
              {formatDate(item.source.effective_date)}
              {item.section.heading ? ` · ${item.section.heading}` : ''}
            </span>
            <ClauseBlock text={item.section.full_text} />
          </li>
        ))}
      </ul>
    )
  }

  interface VendorComparison {
    clause_type: string
    filters: string
    matches: { counterparty_id: number; counterparty_name: string; applies_to: string[]; source: Source; clause: ClauseData }[]
    other_agreed: number
    not_comparable: string[]
    confirmed_absent: string[]
    no_record: string[]
    pending: string[]
  }
  
  const ABSENT_LABEL: Record<string, string> = {
    liability_cap: 'No cap in the contract',
    payment_terms: 'No payment terms in the contract',
    governing_law: 'No governing law clause',
    indemnification: 'No indemnification clause',
  }
  
  // One agreed term across every vendor. The filtering happened in code, not in the model.
  function VendorsCard({ data }: { data: VendorComparison }) {
    const notes: { label: string; names: string[] }[] = [
      { label: ABSENT_LABEL[data.clause_type] ?? 'Not in the contract', names: data.confirmed_absent },
      { label: 'Cap in another currency, not compared', names: data.not_comparable },
      { label: 'Waiting for review', names: data.pending },
      { label: 'Nothing agreed on file', names: data.no_record },
    ].filter((n) => n.names.length > 0)
  
    return (
      <>
        <p className="card-subtitle">
          {data.filters === 'every vendor' ? 'Every vendor' : `Filter: ${data.filters}`} ·{' '}
          {data.matches.length} {data.matches.length === 1 ? 'match' : 'matches'}
          {data.other_agreed ? ` · ${data.other_agreed} other ${data.other_agreed === 1 ? 'vendor' : 'vendors'} didn't match` : ''}
        </p>
        {data.matches.length === 0 ? (
          <p className="card-empty">No agreed terms match.</p>
        ) : (
          <ul className="card-rows">
            {data.matches.map((row) => (
              <li key={row.clause.id}>
                <div className="card-row">
                  <span className="card-label">
                    {row.counterparty_name}
                    <span className="vendor-scope">{row.applies_to[0]}</span>
                  </span>
                  <span className="card-value">{clauseValue(row.clause)}</span>
                </div>
                <span className="quote">
                  {row.source.title}
                  {row.clause.section_number ? ` · §${row.clause.section_number}` : ''} ·{' '}
                  {formatDate(row.source.effective_date)}
                </span>
              </li>
            ))}
          </ul>
        )}
        {notes.length > 0 && (
          <ul className="vendor-notes">
            {notes.map((n) => (
              <li key={n.label}>
                <span className="vendor-note-label">{n.label}:</span> {n.names.join(', ')}
              </li>
            ))}
          </ul>
        )}
      </>
    )
  }  

  interface DeadlineRow {
    counterparty_name: string
    source: Source
    term_source: Source
    clause_id: number
    status: 'upcoming' | 'notice_passed' | 'expired' | 'ends_on_event' | 'unknown'
    term_end: string | null
    notice_deadline: string | null
    action_date: string | null
    days_until: number | null
    auto_renews: boolean | null
    summary: string
  }
  
  interface DeadlinesData {
    as_of: string
    within_days: number | null
    rows: DeadlineRow[]
    needs_review: string[]
    no_term_on_file: string[]
  }
  
  function daysLabel(days: number | null): string {
    if (days === null) return ''
    if (days === 0) return 'today'
    if (days === 1) return 'tomorrow'
    if (days > 0) return `in ${days} days`
    return days === -1 ? 'yesterday' : `${-days} days ago`
  }
  
  // What needs doing next for one contract, with a badge showing how urgent it is
  function deadlineHeadline(row: DeadlineRow): { label: string; badge: string; badgeClass: string } {
    const when = row.action_date ? formatDate(row.action_date) : ''
    if (row.status === 'expired') return { label: `Expired ${when}`, badge: 'Expired', badgeClass: 'badge' }
    if (row.status === 'unknown') return { label: 'Dates incomplete', badge: 'Check term', badgeClass: 'badge' }
    const action = row.notice_deadline ? `Send notice by ${when}` : `Expires ${when}`
    const days = row.days_until ?? Infinity
    if (row.status === 'notice_passed') {
      return { label: action, badge: 'Renewed, notice missed', badgeClass: 'badge badge-differs' }
    }
    if (days <= 30) return { label: action, badge: 'Act now', badgeClass: 'badge badge-differs' }
    if (days <= 90) return { label: action, badge: 'Coming up', badgeClass: 'badge badge-pending' }
    return { label: action, badge: 'Later', badgeClass: 'badge' }
  }
  
  // Expirations and renewal deadlines. Every date was worked out in code, not by the model.
  function DeadlinesCard({ data }: { data: DeadlinesData }) {
    const notes = [
      { label: 'Term waiting for review', names: data.needs_review },
      { label: 'No term on file', names: data.no_term_on_file },
    ].filter((n) => n.names.length > 0)
  
    return (
      <>
        <p className="card-subtitle">
          As of {formatDate(data.as_of)} · Estimated from each contract's reviewed term, so confirm against the
          contract before acting
        </p>
        {data.rows.length === 0 ? (
          <p className="card-empty">
            {data.within_days ? `Nothing due in the next ${data.within_days} days.` : 'No deadlines on file.'}
          </p>
        ) : (
          <ul className="card-rows">
            {data.rows.map((row) => {
              const head = deadlineHeadline(row)
              return (
                <li key={row.clause_id + '-' + row.source.id}>
                  <div className="card-row">
                    <span className="card-label">{row.counterparty_name}</span>
                    <span className={head.badgeClass}>{head.badge}</span>
                  </div>
                  <p className="deadline-action">
                    {head.label}
                    {row.days_until !== null && <span className="deadline-days"> · {daysLabel(row.days_until)}</span>}
                  </p>
                  <span className="quote">
                    {row.source.title} · {formatDate(row.source.effective_date)}
                    {row.term_source.id !== row.source.id ? ` · term from ${row.term_source.title}` : ''}
                  </span>
                  <p className="deadline-summary">{row.summary}</p>
                </li>
              )
            })}
          </ul>
        )}
        {notes.length > 0 && (
          <ul className="vendor-notes">
            {notes.map((n) => (
              <li key={n.label}>
                <span className="vendor-note-label">{n.label}:</span> {n.names.join(', ')}
              </li>
            ))}
          </ul>
        )}
      </>
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
                correct={
                  canCorrect(item.clause.clause_type, item.clause.presence)
                    ? { clauseType: item.clause.clause_type, terms: item.clause.terms }
                    : undefined
                }
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
    case 'section':
        body = <SectionCard items={card.data as SectionTextData[]} />
        break
    case 'deadlines':
      body = <DeadlinesCard data={card.data as DeadlinesData} />
      break
    case 'vendors':
        body = <VendorsCard data={card.data as VendorComparison} />
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