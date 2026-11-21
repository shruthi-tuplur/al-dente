// The Overview tab: the first thing you see for a vendor.
// What needs your attention, the key terms in one table (click a row for every version),
// the team's newest notes, and every other clause filed by topic at the bottom.
import { useEffect, useRef, useState } from 'react'
import ClauseBlock from './ClauseBlock'
import { CLAUSE_LABELS, formatDate, todayISO } from './format'
import type { ClauseType } from './format'
import { ClauseRow, clauseSummary } from './LibraryRows'
import type { Status } from './LibraryRows'
import { fetchVendorDeadlines } from './nonnaApi'
import type { CounterpartyLibrary, LibraryClause, LibraryContract, LibrarySection, RelationshipNotes } from './nonnaApi'
import { PlaybookBadge } from './Playbook'
import { NotesStrip } from './RelationshipNotes'
import WhichTermControls from './TermControls'
import TermLabel from './TermLabel'

// "MSA", "SOW No. 2", "Amendment No. 1": short enough for a table
export function shortName(contract: LibraryContract): string {
  if (contract.contract_type === 'MSA') return 'MSA'
  if (contract.contract_type === 'NDA') return 'NDA'
  const kind = { SOW: 'SOW', amendment: 'Amendment', change_order: 'Change order' }[contract.contract_type]
  const number = contract.title.match(/No\.\s*(\d+)/i)
  return number ? `${kind} No. ${number[1]}` : contract.title
}

type Version = { contract: LibraryContract; clause: LibraryClause }

function versionsOf(type: ClauseType, library: CounterpartyLibrary): Version[] {
  return library.contracts
    .flatMap(({ contract, clauses }) => clauses.filter((c) => c.clause_type === type).map((clause) => ({ contract, clause })))
    .sort((a, b) => b.contract.effective_date.localeCompare(a.contract.effective_date)) // newest first
}

// The version that counts: the agreed one, or else the newest reviewed one
function currentOf(versions: Version[], status: Status): Version | undefined {
  return (
    versions.find(({ clause }) => status.agreed.has(clause.id)) ??
    versions.find(
      ({ clause }) =>
        clause.presence === 'present' && (clause.review_status === 'approved' || clause.review_status === 'corrected'),
    )
  )
}

function TermLine({
  type,
  library,
  status,
  onChanged,
}: {
  type: ClauseType
  library: CounterpartyLibrary
  status: Status
  onChanged: () => void
}) {
  const [open, setOpen] = useState(false)
  const versions = versionsOf(type, library)
  const current = currentOf(versions, status)
  const pending = versions.filter(({ clause }) => clause.review_status === 'pending').length
  const assessment = current ? status.playbook[current.clause.id] : undefined

  let value = 'Nothing on file'
  if (current) value = clauseSummary(current.clause)
  else if (pending) value = 'Waiting for review'

  return (
    <li className={open ? 'term-line term-line-open' : 'term-line'}>
      <button type="button" className="term-line-row" aria-expanded={open} onClick={() => setOpen(!open)} disabled={versions.length === 0}>
        <span className="term-line-name">
          <TermLabel type={type}>{CLAUSE_LABELS[type]}</TermLabel>
        </span>
        <span className="term-line-value">
          <span className={current ? '' : 'term-line-empty'}>{value}</span>
          {current && (
            <span className="term-line-source">
              {shortName(current.contract)}
              {current.clause.section_number ? ` §${current.clause.section_number}` : ''}
            </span>
          )}
        </span>
        <span className="term-line-badge">
          {assessment && <PlaybookBadge assessment={assessment} />}
          {pending > 0 && <span className="badge badge-pending">{pending} to review</span>}
        </span>
        <span className="term-line-count">
          {versions.length > 0 && `${versions.length} ${versions.length === 1 ? 'version' : 'versions'}`}
          <span className="term-line-chevron" aria-hidden="true">
            {versions.length > 0 ? (open ? '▾' : '▸') : ''}
          </span>
        </span>
      </button>
      {open && (
        <ol className="term-line-versions">
          {versions.map(({ contract, clause }) => (
            <ClauseRow
              key={clause.id}
              clause={clause}
              contractId={contract.id}
              status={status}
              title={`${shortName(contract)} · ${formatDate(contract.effective_date)}`}
              onChanged={onChanged}
            />
          ))}
        </ol>
      )}
    </li>
  )
}

function Attention({
  library,
  status,
  openCalls,
  onShowCalls,
}: {
  library: CounterpartyLibrary
  status: Status
  openCalls: number
  onShowCalls: () => void
}) {
  const [nextDate, setNextDate] = useState<{ date: string; summary: string } | null>(null)

  useEffect(() => {
    let current = true
    const today = todayISO()
    fetchVendorDeadlines(library.counterparty.id)
      .then(({ rows }) => {
        const upcoming = rows
          .filter((r) => r.action_date && r.action_date >= today)
          .sort((a, b) => (a.action_date ?? '').localeCompare(b.action_date ?? ''))[0]
        if (current) setNextDate(upcoming ? { date: upcoming.action_date!, summary: upcoming.summary } : null)
      })
      .catch(() => current && setNextDate(null))
    return () => {
      current = false
    }
  }, [library])

  const clauses = library.contracts.flatMap(({ clauses: c }) => c)
  const pending = clauses.filter((c) => c.review_status === 'pending').length
  const offPlaybook = clauses.filter((c) => {
    const a = status.playbook[c.id]
    return status.agreed.has(c.id) && a && a.tier === 'outside' && !a.exception
  }).length

  const items = [
    openCalls > 0 && (
      <button key="calls" type="button" className="attention-chip attention-urgent" onClick={onShowCalls}>
        ⚖ {openCalls} which-term-controls {openCalls === 1 ? 'call' : 'calls'} to make ↓
      </button>
    ),
    pending > 0 && (
      <span key="pending" className="attention-chip">
        {pending} {pending === 1 ? 'term' : 'terms'} waiting in Review
      </span>
    ),
    offPlaybook > 0 && (
      <span key="playbook" className="attention-chip attention-urgent">
        {offPlaybook} agreed {offPlaybook === 1 ? 'term' : 'terms'} off playbook
      </span>
    ),
    nextDate && (
      <span key="date" className="attention-chip" title={nextDate.summary}>
        Next deadline: {formatDate(nextDate.date)}
      </span>
    ),
  ].filter(Boolean)

  return (
    <section className="overview-section">
      <p className="overview-label">Needs your attention</p>
      {items.length === 0 ? (
        <p className="attention-none">✓ Nothing needs your attention right now.</p>
      ) : (
        <div className="attention-row">{items}</div>
      )}
    </section>
  )
}

function AsWritten({ library }: { library: CounterpartyLibrary }) {
  const titles = new Map(library.contracts.map(({ contract }) => [contract.id, contract]))
  const byCategory = new Map<string, LibrarySection[]>()
  for (const section of library.sections) {
    byCategory.set(section.category, [...(byCategory.get(section.category) ?? []), section])
  }
  const rank = (c: string) => {
    const i = library.category_order.indexOf(c)
    return i === -1 ? library.category_order.length : i
  }
  const categories = [...byCategory.keys()].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b))
  if (categories.length === 0) return null

  return (
    <section className="overview-section">
      <p className="overview-label">
        Every clause, as written <span className="lib-group-count">{categories.length}</span>
      </p>
      <p className="overview-hint">Exactly what each contract says, filed by topic. Not reviewed.</p>
      <ul className="topic-list">
        {categories.map((category) => {
          const sections = byCategory.get(category) ?? []
          return (
            <li key={category}>
              <details className="topic">
                <summary>
                  <span>{category}</span>
                  <span className="term-line-count">
                    {sections.length} {sections.length === 1 ? 'section' : 'sections'}
                  </span>
                </summary>
                <ol className="term-line-versions">
                  {sections.map((section) => {
                    const contract = titles.get(section.contract_id)
                    return (
                      <li key={section.id} className="lib-row">
                        <div className="lib-row-where">
                          <span className="lib-row-title">
                            {contract ? `${shortName(contract)} · ${formatDate(contract.effective_date)}` : 'Contract'}
                          </span>
                          <span className="lib-row-section">
                            {section.section_number ? `§${section.section_number}` : 'No section number'}
                            {section.heading ? ` · ${section.heading}` : ''}
                          </span>
                        </div>
                        <ClauseBlock text={section.full_text} contractId={section.contract_id} />
                      </li>
                    )
                  })}
                </ol>
              </details>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

export default function LibraryOverview({
  library,
  status,
  notes,
  onChanged,
  onOpenNotes,
}: {
  library: CounterpartyLibrary
  status: Status
  notes: RelationshipNotes | null
  onChanged: () => void
  onOpenNotes: () => void
}) {
  const [openCalls, setOpenCalls] = useState(0)
  const callsRef = useRef<HTMLDivElement>(null)

  return (
    <div className="overview">
      <Attention
        library={library}
        status={status}
        openCalls={openCalls}
        onShowCalls={() => callsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
      />

      <div ref={callsRef}>
        <WhichTermControls
          counterpartyId={library.counterparty.id}
          reloadKey={library}
          onReport={(report) => setOpenCalls(report.open_count)}
        />
      </div>

      <section className="overview-section">
        <p className="overview-label">Key terms</p>
        <p className="overview-hint">The agreed value for each term. Click a term to see every version and its wording.</p>
        <ul className="term-table">
          {(Object.keys(CLAUSE_LABELS) as ClauseType[]).map((type) => (
            <TermLine key={type} type={type} library={library} status={status} onChanged={onChanged} />
          ))}
        </ul>
      </section>

      {notes && (
        <section className="overview-section">
          <p className="overview-label">Team notes</p>
          <NotesStrip data={notes} onOpen={onOpenNotes} />
        </section>
      )}

      <AsWritten library={library} />
    </div>
  )
}