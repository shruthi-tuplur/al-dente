import { useEffect, useState } from 'react'
import { formatDate } from './format'
import AsAmended from './AsAmended'
import DraftTab from './Draft'
import FullContract from './FullContract'
import OnePager from './OnePager'
import TermLabel from './TermLabel'
import { NotesTab } from './RelationshipNotes'
import DecisionHistoryTab from './DecisionHistory'
import FixContract from './FixContract'
import LibraryOverview from './LibraryOverview'
import { ClauseRow } from './LibraryRows'
import type { Status } from './LibraryRows'
import { fetchCounterparties, fetchLibrary, fetchNotes } from './nonnaApi'
import type {
  ContractType,
  CounterpartyLibrary,
  CounterpartySummary,
  LibraryContract,
  Draft,
  FixOutcome,
  RelationshipNotes,
} from './nonnaApi'

type Tab = 'overview' | 'contracts' | 'notes' | 'history' | 'draft'

const GROUPS: { type: ContractType; label: string }[] = [
  { type: 'MSA', label: 'Master agreements' },
  { type: 'SOW', label: 'Statements of work' },
  { type: 'amendment', label: 'Amendments' },
  { type: 'change_order', label: 'Change orders' },
  { type: 'NDA', label: 'NDAs' },
]

type Panel = 'full' | 'amended' | 'fix' | null

// One contract: title and date on top, a quiet toolbar, one panel open at a time, then its key terms
function ContractCard({
  contract,
  clauses,
  library,
  status,
  vendors,
  onChanged,
  onFixed,
}: {
  contract: LibraryContract
  clauses: CounterpartyLibrary['contracts'][number]['clauses']
  library: CounterpartyLibrary
  status: Status
  vendors: CounterpartySummary[]
  onChanged: () => void
  onFixed: (outcome: FixOutcome) => void
}) {
  const [panel, setPanel] = useState<Panel>(null)
  const titles = new Map(library.contracts.map(({ contract: c }) => [c.id, c.title]))
  const amendments = library.contracts.filter(({ contract: c }) => c.amends_contract_id === contract.id).length
  const parent = contract.parent_contract_id ?? contract.amends_contract_id
  const meta = [
    `Signed by ${contract.signed_by_entity}`,
    parent !== null
      ? `${contract.amends_contract_id !== null ? 'Amends' : 'Falls under'} ${titles.get(parent) ?? 'another contract'}`
      : null,
    contract.status !== 'active' ? contract.status : null,
  ]
    .filter(Boolean)
    .join(' · ')

  const toggle = (next: Panel) => setPanel((current) => (current === next ? null : next))

  return (
    <details className="lib-contract">
      <summary>
        <span className="lib-contract-title">{contract.title}</span>
        <span className="card-meta">{formatDate(contract.effective_date)}</span>
      </summary>
      <p className="lib-contract-meta">{meta}</p>

      <div className="lib-toolbar">
        <button type="button" className="lib-tool" aria-pressed={panel === 'full'} onClick={() => toggle('full')}>
          Read full contract
        </button>
        {amendments > 0 && (
          <button type="button" className="lib-tool" aria-pressed={panel === 'amended'} onClick={() => toggle('amended')}>
            Read as amended ({amendments})
          </button>
        )}
        <a className="lib-tool" href={`/api/contracts/${contract.id}/file`} target="_blank" rel="noreferrer">
          Original file ↗
        </a>
        <button type="button" className="lib-tool lib-tool-end" aria-pressed={panel === 'fix'} onClick={() => toggle('fix')}>
          Fix upload details
        </button>
      </div>

      {panel !== null && (
        <div className="lib-panel">
          {panel === 'full' && <FullContract contractId={contract.id} />}
          {panel === 'amended' && <AsAmended contractId={contract.id} />}
          {panel === 'fix' && (
            <FixContract
              contract={contract}
              library={library}
              vendors={vendors}
              onDone={(outcome) => {
                setPanel(null)
                onFixed(outcome)
              }}
              onCancel={() => setPanel(null)}
            />
          )}
        </div>
      )}

      {clauses.length === 0 ? (
        <p className="card-empty">No key terms pulled from this contract yet.</p>
      ) : (
        <>
          <p className="overview-label lib-contract-terms">Key terms in this contract</p>
          <ul className="lib-rows">
            {clauses.map((clause) => (
              <ClauseRow
                key={clause.id}
                clause={clause}
                contractId={contract.id}
                status={status}
                title={<TermLabel type={clause.clause_type} />}
                onChanged={onChanged}
              />
            ))}
          </ul>
        </>
      )}
    </details>
  )
}

function ContractsTab({
  library,
  status,
  vendors,
  onChanged,
  onFixed,
}: {
  library: CounterpartyLibrary
  status: Status
  vendors: CounterpartySummary[]
  onChanged: () => void
  onFixed: () => void
}) {
  const [fixMessage, setFixMessage] = useState('')

  return (
    <>
      {fixMessage && <p className="review-done fix-message">✓ {fixMessage}</p>}
      {GROUPS.map(({ type, label }) => {
        const items = library.contracts.filter(({ contract }) => contract.contract_type === type)
        if (items.length === 0) return null
        return (
          <section key={type} className="lib-group">
            <h3 className="lib-group-title">
              {label} <span className="lib-group-count">{items.length}</span>
            </h3>
            {items.map(({ contract, clauses }) => (
              <ContractCard
                key={contract.id}
                contract={contract}
                clauses={clauses}
                library={library}
                status={status}
                vendors={vendors}
                onChanged={onChanged}
                onFixed={(outcome) => {
                  setFixMessage(outcome.message)
                  onFixed()
                }}
              />
            ))}
          </section>
        )
      })}
    </>
  )
}

export default function Library({
  openDraft = null,
  onDraftOpened,
}: {
  openDraft?: Draft | null // a draft from chat to open straight away
  onDraftOpened?: () => void
} = {}) {
  const [incoming] = useState(openDraft)
  const [vendors, setVendors] = useState<CounterpartySummary[] | null>(null)
  const [selectedId, setSelectedId] = useState<number | null>(openDraft?.counterparty_id ?? null)
  const [library, setLibrary] = useState<CounterpartyLibrary | null>(null)
  const [tab, setTab] = useState<Tab>(openDraft ? 'draft' : 'overview')
  const [notesData, setNotesData] = useState<RelationshipNotes | null>(null)
  const [notesVersion, setNotesVersion] = useState(0)
  const [error, setError] = useState('')
  const [showOnePager, setShowOnePager] = useState(false)
  // The vendor list folds away for more room. Remembered in this browser, if it allows.
  const [vendorsOpen, setVendorsOpen] = useState(() => {
    try {
      return localStorage.getItem('nonna.vendorsOpen') !== 'no'
    } catch {
      return true
    }
  })

  function toggleVendors() {
    const next = !vendorsOpen
    setVendorsOpen(next)
    try {
      localStorage.setItem('nonna.vendorsOpen', next ? 'yes' : 'no')
    } catch {
      // private mode or blocked storage: it just won't be remembered
    }
  }

  // The draft is handed over once, so coming back to the Library later starts fresh
  useEffect(() => {
    if (openDraft) onDraftOpened?.()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    fetchCounterparties()
      .then((list) => {
        setVendors(list)
        if (list.length > 0) setSelectedId((id) => id ?? list[0].id)
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

  // The team's notes about this vendor (reloaded after adding or archiving one)
  useEffect(() => {
    if (selectedId === null) return
    let current = true
    fetchNotes(selectedId)
      .then((data) => current && setNotesData(data))
      .catch(() => current && setNotesData(null))
    return () => {
      current = false
    }
  }, [selectedId, notesVersion])

  // Reload the vendor list (counts change when a contract moves or is deleted)
  function reloadVendors() {
    fetchCounterparties()
      .then(setVendors)
      .catch(() => undefined)
  }

  // Reload after a correction, without clearing the page
  function refresh() {
    if (selectedId === null) return
    fetchLibrary(selectedId)
      .then(setLibrary)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Couldn't reload that vendor."))
  }

  const status: Status = {
    agreed: new Set(library?.agreed_clause_ids ?? []),
    superseded: new Set(library?.superseded_clause_ids ?? []),
    playbook: library?.playbook ?? {},
  }

  // Only vendors with an SOW on file can have a new one drafted
  const canDraft = library?.contracts.some(({ contract }) => contract.contract_type === 'SOW') ?? false
  const shownTab: Tab = tab === 'draft' && !canDraft ? 'overview' : tab
  // Only show notes that belong to the vendor on screen (not the last one, mid-switch)
  const notes = notesData && library && notesData.counterparty_id === library.counterparty.id ? notesData : null
  const noteCount = notes?.notes.length ?? 0
  const tabs: { id: Tab; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'contracts', label: `Contracts (${library?.contracts.length ?? 0})` },
    { id: 'notes', label: noteCount > 0 ? `Notes (${noteCount})` : 'Notes' },
    { id: 'history', label: 'History' },
    ...(canDraft ? [{ id: 'draft' as Tab, label: 'Draft a new SOW' }] : []),
  ]

  return (
    <div className={vendorsOpen ? 'library' : 'library library-collapsed'}>
    <nav className="lib-vendors" aria-label="Vendors">
      <div className="lib-vendors-head">
        {vendorsOpen && <p className="card-section">Vendors</p>}
        <button
          type="button"
          className="lib-vendors-toggle"
          aria-expanded={vendorsOpen}
          aria-label={vendorsOpen ? 'Hide the vendor list' : 'Show the vendor list'}
          title={vendorsOpen ? 'Hide vendors' : 'Show vendors'}
          onClick={toggleVendors}
        >
          {vendorsOpen ? '«' : '»'}
        </button>
      </div>
      {vendorsOpen && (
        <>
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
        </>
      )}
    </nav>

      <section className="lib-detail">
        {error && <p className="intake-error">⚠ {error}</p>}
        {selectedId !== null && library === null && !error && <p className="thinking">Loading…</p>}
        {library && (
          <>
            <div className="lib-header">
              <div>
                <p className="card-title lib-title">{library.counterparty.name}</p>
                <p className="card-subtitle">{library.counterparty.entities.map((e) => e.legal_name).join(', ')}</p>
              </div>
              <button type="button" className="btn btn-sm btn-quiet" onClick={() => setShowOnePager(true)}>
                One-pager
              </button>
            </div>
            {showOnePager && <OnePager library={library} onClose={() => setShowOnePager(false)} />}

            <div className="lib-tabs" role="tablist">
              {tabs.map(({ id, label }) => (
                <button
                  key={id}
                  type="button"
                  role="tab"
                  aria-selected={shownTab === id}
                  className={shownTab === id ? 'lib-tab lib-tab-active' : 'lib-tab'}
                  onClick={() => setTab(id)}
                >
                  {label}
                </button>
              ))}
            </div>

            {shownTab === 'overview' && (
              <LibraryOverview
                key={library.counterparty.id}
                library={library}
                status={status}
                notes={notes}
                onChanged={refresh}
                onOpenNotes={() => setTab('notes')}
              />
            )}
            {shownTab === 'contracts' && (
              <ContractsTab
                key={library.counterparty.id}
                library={library}
                status={status}
                vendors={vendors ?? []}
                onChanged={refresh}
                onFixed={() => {
                  refresh()
                  reloadVendors()
                }}
              />
            )}
            {shownTab === 'notes' && notes && <NotesTab data={notes} onChanged={() => setNotesVersion((n) => n + 1)} />}
            {shownTab === 'history' && <DecisionHistoryTab counterpartyId={library.counterparty.id} reloadKey={library} />}
            {/* Kept mounted so a draft isn't lost when switching tabs */}
            {canDraft && (
              <div hidden={shownTab !== 'draft'}>
                <DraftTab
                  key={library.counterparty.id}
                  counterpartyId={library.counterparty.id}
                  vendorName={library.counterparty.name}
                  initialDraft={incoming?.counterparty_id === library.counterparty.id ? incoming : null}
                />
              </div>
            )}
          </>
        )}
      </section>
    </div>
  )
}