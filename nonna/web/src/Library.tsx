import { useEffect, useState } from 'react'
import ClauseBlock from './ClauseBlock'
import CorrectionForm, { canCorrect } from './CorrectionForm'
import { CLAUSE_LABELS, clauseLabel, describeTerms, formatDate } from './format'
import type { ClauseType } from './format'
import FullContract from './FullContract'
import { fetchCounterparties, fetchLibrary } from './nonnaApi'
import type {
  ContractType,
  CounterpartyLibrary,
  CounterpartySummary,
  LibraryClause,
  LibraryContract,
  LibrarySection,
} from './nonnaApi'

const GROUPS: { type: ContractType; label: string }[] = [
  { type: 'MSA', label: 'Master agreements' },
  { type: 'SOW', label: 'Statements of work' },
  { type: 'amendment', label: 'Amendments' },
  { type: 'change_order', label: 'Change orders' },
  { type: 'NDA', label: 'NDAs' },
]

function clauseSummary(clause: LibraryClause): string {
  if (clause.presence === 'absent') return 'Not in this contract'
  if (clause.presence === 'incorporated_by_reference') return 'Follows the MSA'
  return describeTerms(clause.clause_type, clause.terms) ?? 'See wording'
}

interface Status {
  agreed: Set<number>
  superseded: Set<number>
}

function statusBadge(clause: LibraryClause, status: Status) {
  if (status.agreed.has(clause.id)) return <span className="badge badge-agreed">Agreed</span>
  if (status.superseded.has(clause.id)) return <span className="badge">Earlier version</span>
  if (clause.review_status === 'pending') return <span className="badge badge-pending">Waiting for review</span>
  if (clause.review_status === 'rejected') return <span className="badge">Rejected</span>
  if (clause.review_status === 'corrected') return <span className="badge">Corrected</span>
  return <span className="badge">Approved</span>
}

function ClauseRow({
  clause,
  agreed,
  title,
  onChanged,
}: {
  clause: LibraryClause
  agreed: Status
  title: string
  onChanged: () => void
}) {
  const [fixing, setFixing] = useState(false)
  const [saved, setSaved] = useState('')
  const reviewed = clause.review_status === 'approved' || clause.review_status === 'corrected'
  const fixable = reviewed && canCorrect(clause.clause_type, clause.presence)

  return (
    <li className="lib-clause">
      <div className="card-row">
        <span className="card-label">{title}</span>
        <span className="card-value">{clauseSummary(clause)}</span>
      </div>
      <div className="lib-clause-meta">
        <span className="quote">
          {clause.section_number ? `§${clause.section_number}` : 'No section'}
          {clause.heading ? ` · ${clause.heading}` : ''}
        </span>
        {statusBadge(clause, agreed)}
      </div>
      {clause.full_text && (
        <details className="lib-wording">
          <summary>Show exact wording</summary>
          <ClauseBlock text={clause.full_text} />
        </details>
      )}
      {saved && <p className="review-done">✓ {saved}</p>}
      {fixable && !fixing && (
        <button
          type="button"
          className="lib-fix"
          onClick={() => {
            setSaved('')
            setFixing(true)
          }}
        >
          Fix value
        </button>
      )}
      {fixing && (
        <CorrectionForm
          clauseId={clause.id}
          clauseType={clause.clause_type}
          terms={clause.terms}
          onSaved={(message) => {
            setFixing(false)
            setSaved(message)
            onChanged()
          }}
          onCancel={() => setFixing(false)}
        />
      )}
    </li>
  )
}

function ContractsTab({
  library,
  agreed,
  onChanged,
}: {
  library: CounterpartyLibrary
  agreed: Status
  onChanged: () => void
}) {
  const titles = new Map(library.contracts.map(({ contract }) => [contract.id, contract.title]))
  const parentNote = (c: LibraryContract) => {
    const parent = c.parent_contract_id ?? c.amends_contract_id
    if (parent === null) return null
    return `${c.amends_contract_id !== null ? 'Amends' : 'Falls under'} ${titles.get(parent) ?? 'another contract'}`
  }

  return (
    <>
      {GROUPS.map(({ type, label }) => {
        const items = library.contracts.filter(({ contract }) => contract.contract_type === type)
        if (items.length === 0) return null
        return (
          <section key={type} className="lib-group">
            <h3 className="lib-group-title">
              {label} <span className="lib-group-count">{items.length}</span>
            </h3>
            {items.map(({ contract, clauses }) => (
              <details key={contract.id} className="lib-contract">
                <summary>
                  <span className="lib-contract-title">{contract.title}</span>
                  <span className="card-meta">{formatDate(contract.effective_date)}</span>
                </summary>
                <p className="quote">
                  Signed by {contract.signed_by_entity}
                  {parentNote(contract) ? ` · ${parentNote(contract)}` : ''}
                  {contract.status !== 'active' ? ` · ${contract.status}` : ''}
                </p>
                <FullContract contractId={contract.id} />
                {clauses.length === 0 ? (
                  <p className="card-empty">No clauses extracted from this contract yet.</p>
                ) : (
                  <ul className="card-rows">
                    {clauses.map((clause) => (
                      <ClauseRow
                        key={clause.id}
                        clause={clause}
                        agreed={agreed}
                        title={clauseLabel(clause.clause_type)}
                        onChanged={onChanged}
                      />
                    ))}
                  </ul>
                )}
              </details>
            ))}
          </section>
        )
      })}
    </>
  )
}

function TrackedCategory({
  type,
  library,
  agreed,
  onChanged,
}: {
  type: ClauseType
  library: CounterpartyLibrary
  agreed: Status
  onChanged: () => void
}) {
  const versions = library.contracts
    .flatMap(({ contract, clauses }) =>
      clauses.filter((c) => c.clause_type === type).map((clause) => ({ contract, clause })),
    )
    .sort((a, b) => a.contract.effective_date.localeCompare(b.contract.effective_date))
  const current = versions.find(({ clause }) => agreed.agreed.has(clause.id))
  const meta = [
    current ? `Agreed: ${clauseSummary(current.clause)}` : null,
    versions.length === 0 ? 'Nothing on file' : `${versions.length} ${versions.length === 1 ? 'version' : 'versions'}`,
  ]
    .filter(Boolean)
    .join(' · ')

  return (
    <details className="lib-category">
      <summary>
        <span className="lib-category-title">{CLAUSE_LABELS[type]}</span>
        <span className="card-meta">{meta}</span>
      </summary>
      {versions.length === 0 ? (
        <p className="card-empty">Nothing on file yet.</p>
      ) : (
        <ol className="timeline">
          {versions.map(({ contract, clause }) => (
            <ClauseRow
              key={clause.id}
              clause={clause}
              agreed={agreed}
              title={`${contract.title} · ${formatDate(contract.effective_date)}`}
              onChanged={onChanged}
            />
          ))}
        </ol>
      )}
    </details>
  )
}

function CatalogCategory({
  category,
  sections,
  contracts,
}: {
  category: string
  sections: LibrarySection[]
  contracts: Map<number, LibraryContract>
}) {
  const contractCount = new Set(sections.map((s) => s.contract_id)).size
  return (
    <details className="lib-category">
      <summary>
        <span className="lib-category-title">{category}</span>
        <span className="card-meta">
          {contractCount} {contractCount === 1 ? 'contract' : 'contracts'}
        </span>
      </summary>
      <ol className="timeline">
        {sections.map((section) => {
          const contract = contracts.get(section.contract_id)
          return (
            <li key={section.id} className="lib-clause">
              <div className="card-row">
                <span className="card-label">
                  {contract ? `${contract.title} · ${formatDate(contract.effective_date)}` : 'Contract'}
                </span>
              </div>
              <p className="quote">
                {section.section_number ? `§${section.section_number}` : 'No section number'}
                {section.heading ? ` · ${section.heading}` : ''}
              </p>
              <ClauseBlock text={section.full_text} />
            </li>
          )
        })}
      </ol>
    </details>
  )
}

function ClausesTab({
  library,
  agreed,
  onChanged,
}: {
  library: CounterpartyLibrary
  agreed: Status
  onChanged: () => void
}) {
  const contracts = new Map(library.contracts.map(({ contract }) => [contract.id, contract]))

  // Group every section by category, in the order the backend gives
  const byCategory = new Map<string, LibrarySection[]>()
  for (const section of library.sections) {
    const list = byCategory.get(section.category) ?? []
    list.push(section)
    byCategory.set(section.category, list)
  }
  const rank = (c: string) => {
    const i = library.category_order.indexOf(c)
    return i === -1 ? library.category_order.length : i
  }
  const categories = [...byCategory.keys()].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b))

  return (
    <>
      <section className="lib-group">
        <h3 className="lib-group-title">Key terms Nonna tracks</h3>
        <p className="card-subtitle lib-group-note">Values pulled out, reviewed, and compared across contracts.</p>
        {(Object.keys(CLAUSE_LABELS) as ClauseType[]).map((type) => (
          <TrackedCategory key={type} type={type} library={library} agreed={agreed} onChanged={onChanged} />
        ))}
      </section>

      <section className="lib-group">
        <h3 className="lib-group-title">
          Every clause, as written <span className="lib-group-count">{categories.length}</span>
        </h3>
        <p className="card-subtitle lib-group-note">Exactly what each contract says, filed by topic. Not reviewed.</p>
        {categories.length === 0 ? (
          <p className="card-empty">No clauses filed yet. Upload a contract and Nonna will sort it.</p>
        ) : (
          categories.map((category) => (
            <CatalogCategory
              key={category}
              category={category}
              sections={byCategory.get(category) ?? []}
              contracts={contracts}
            />
          ))
        )}
      </section>
    </>
  )
}

export default function Library() {
  const [vendors, setVendors] = useState<CounterpartySummary[] | null>(null)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [library, setLibrary] = useState<CounterpartyLibrary | null>(null)
  const [tab, setTab] = useState<'contracts' | 'clauses'>('contracts')
  const [error, setError] = useState('')

  useEffect(() => {
    fetchCounterparties()
      .then((list) => {
        setVendors(list)
        if (list.length > 0) setSelectedId(list[0].id)
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Couldn't load your vendors."))
  }, [])

  useEffect(() => {
    if (selectedId === null) return
    let current = true
    setLibrary(null)
    fetchLibrary(selectedId)
      .then((data) => current && setLibrary(data))
      .catch((err: unknown) => current && setError(err instanceof Error ? err.message : "Couldn't load that vendor."))
    return () => {
      current = false
    }
  }, [selectedId])

  // Reload after a correction, without clearing the page
  function refresh() {
    if (selectedId === null) return
    fetchLibrary(selectedId)
      .then(setLibrary)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Couldn't reload that vendor."))
  }

  const agreed: Status = {
    agreed: new Set(library?.agreed_clause_ids ?? []),
    superseded: new Set(library?.superseded_clause_ids ?? []),
  }

  return (
    <div className="library">
      <nav className="lib-vendors" aria-label="Vendors">
        <p className="card-section">Vendors</p>
        {vendors === null && !error && <p className="card-empty">Loading…</p>}
        {vendors?.length === 0 && <p className="card-empty">No vendors yet. Upload a contract in the chat.</p>}
        <ul>
          {vendors?.map((vendor) => (
            <li key={vendor.id}>
              <button
                type="button"
                className={vendor.id === selectedId ? 'lib-vendor lib-vendor-active' : 'lib-vendor'}
                aria-current={vendor.id === selectedId ? 'true' : undefined}
                onClick={() => setSelectedId(vendor.id)}
              >
                <span>{vendor.name}</span>
                <span className="card-meta">{vendor.contract_count}</span>
              </button>
            </li>
          ))}
        </ul>
      </nav>

      <section className="lib-detail">
        {error && <p className="intake-error">⚠ {error}</p>}
        {selectedId !== null && library === null && !error && <p className="thinking">Loading…</p>}
        {library && (
          <>
            <p className="card-title lib-title">{library.counterparty.name}</p>
            <p className="card-subtitle">
              {library.contracts.length} {library.contracts.length === 1 ? 'contract' : 'contracts'} ·{' '}
              {library.counterparty.entities.map((e) => e.legal_name).join(', ')}
            </p>

            <div className="lib-tabs" role="tablist">
              <button
                type="button"
                role="tab"
                aria-selected={tab === 'contracts'}
                className={tab === 'contracts' ? 'lib-tab lib-tab-active' : 'lib-tab'}
                onClick={() => setTab('contracts')}
              >
                Contracts
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={tab === 'clauses'}
                className={tab === 'clauses' ? 'lib-tab lib-tab-active' : 'lib-tab'}
                onClick={() => setTab('clauses')}
              >
                Clauses
              </button>
            </div>

            {tab === 'contracts' ? (
              <ContractsTab library={library} agreed={agreed} onChanged={refresh} />
            ) : (
              <ClausesTab library={library} agreed={agreed} onChanged={refresh} />
            )}
          </>
        )}
      </section>
    </div>
  )
}