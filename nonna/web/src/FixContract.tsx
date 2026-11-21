// Fix an upload mistake: the wrong title, type, date, vendor, or the contract it falls under.
// Or delete an upload that shouldn't be there. Every fix needs a note and goes in the history.
// The backend decides what's still allowed (nothing reviewed from it yet, nothing under it).
import { useEffect, useState } from 'react'
import { deleteContract, fetchLibrary, fixContract } from './nonnaApi'
import type { ContractType, CounterpartyLibrary, CounterpartySummary, FixOutcome, LibraryContract } from './nonnaApi'

const TYPES: { value: ContractType; label: string }[] = [
  { value: 'MSA', label: 'MSA' },
  { value: 'SOW', label: 'SOW' },
  { value: 'amendment', label: 'Amendment' },
  { value: 'change_order', label: 'Change order' },
  { value: 'NDA', label: 'NDA' },
]

// Which contracts each type can fall under (or amend)
function canLinkTo(type: ContractType, other: LibraryContract): boolean {
  if (type === 'SOW') return other.contract_type === 'MSA'
  if (type === 'change_order') return other.contract_type === 'MSA' || other.contract_type === 'SOW'
  if (type === 'amendment') return true
  return false
}

function linkLabel(type: ContractType): string {
  return type === 'amendment' ? 'Amends' : 'Falls under'
}

interface Props {
  contract: LibraryContract
  library: CounterpartyLibrary // the vendor it's under now
  vendors: CounterpartySummary[]
  onDone: (outcome: FixOutcome) => void
  onCancel: () => void
}

export default function FixContract({ contract, library, vendors, onDone, onCancel }: Props) {
  const [title, setTitle] = useState(contract.title)
  const [type, setType] = useState<ContractType>(contract.contract_type)
  const [effectiveDate, setEffectiveDate] = useState(contract.effective_date.slice(0, 10))
  const [vendorId, setVendorId] = useState(library.counterparty.id)
  const [linkedId, setLinkedId] = useState<number | null>(contract.parent_contract_id ?? contract.amends_contract_id)
  const [note, setNote] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  // The other vendor's contracts, when moving it somewhere else
  const [otherLibrary, setOtherLibrary] = useState<CounterpartyLibrary | null>(null)

  useEffect(() => {
    if (vendorId === library.counterparty.id) return
    let current = true
    fetchLibrary(vendorId)
      .then((data) => current && setOtherLibrary(data))
      .catch(() => current && setOtherLibrary(null))
    return () => {
      current = false
    }
  }, [vendorId, library.counterparty.id])

  const target = vendorId === library.counterparty.id ? library : otherLibrary?.counterparty.id === vendorId ? otherLibrary : null
  const linkOptions = (target?.contracts ?? [])
    .map(({ contract: c }) => c)
    .filter((c) => c.id !== contract.id && canLinkTo(type, c))
  const showLink = type === 'SOW' || type === 'change_order' || type === 'amendment'
  // Drop a link that doesn't fit anymore (a new type, or a new vendor)
  const link = showLink && linkOptions.some((c) => c.id === linkedId) ? linkedId : null

  async function save() {
    if (!title.trim()) return setError('The title can’t be blank.')
    if (!note.trim()) return setError('Add a short note saying what was wrong.')
    setBusy(true)
    setError('')
    try {
      const outcome = await fixContract(contract.id, {
        title: title.trim(),
        contract_type: type,
        effective_date: effectiveDate,
        counterparty_id: vendorId,
        linked_contract_id: link,
        note: note.trim(),
      })
      onDone(outcome)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save that fix.")
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    if (!note.trim()) return setError('Add a short note saying why this upload is being deleted.')
    setBusy(true)
    setError('')
    try {
      onDone(await deleteContract(contract.id, note.trim()))
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't delete that upload.")
      setDeleting(false)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="correction-form fix-contract">
      <p className="correction-title">Fix this upload</p>
      <div className="correction-fields">
        <label className="correction-field fix-title">
          <span>Title</span>
          <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label className="correction-field">
          <span>Type</span>
          <select value={type} onChange={(e) => setType(e.target.value as ContractType)}>
            {TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </label>
        <label className="correction-field">
          <span>Effective date</span>
          <input type="date" value={effectiveDate} onChange={(e) => setEffectiveDate(e.target.value)} />
        </label>
        <label className="correction-field">
          <span>Vendor</span>
          <select value={vendorId} onChange={(e) => setVendorId(Number(e.target.value))}>
            {vendors.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name}
              </option>
            ))}
          </select>
        </label>
        {showLink && (
          <label className="correction-field">
            <span>{linkLabel(type)}</span>
            <select
              value={link ?? ''}
              onChange={(e) => setLinkedId(e.target.value === '' ? null : Number(e.target.value))}
            >
              <option value="">Nothing</option>
              {linkOptions.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.title}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      <textarea
        className="review-note"
        rows={2}
        value={note}
        onChange={(e) => {
          setNote(e.target.value)
          setError('')
        }}
        placeholder="What was wrong? For example: uploaded as an MSA, it's SOW No. 2 under the Lucca MSA."
        aria-label="Why this fix"
      />
      <p className="note-hint">
        Type and vendor can only change before any term from this contract is reviewed. Changing them makes Nonna
        re-read it.
      </p>

      {error && <p className="intake-error">{error}</p>}

      {deleting ? (
        <div className="fix-delete-confirm">
          <p className="review-conflict">
            ⚠ Delete this upload? Its pending terms go too. The history keeps a record that it was deleted, with
            your note.
          </p>
          <div className="intake-actions">
            <button type="button" className="btn btn-sm btn-danger" disabled={busy} onClick={() => void remove()}>
              {busy ? 'Deleting…' : 'Yes, delete it'}
            </button>
            <button type="button" className="btn btn-sm btn-quiet" disabled={busy} onClick={() => setDeleting(false)}>
              Keep it
            </button>
          </div>
        </div>
      ) : (
        <div className="intake-actions fix-actions">
          <button type="button" className="btn btn-sm btn-primary" disabled={busy} onClick={() => void save()}>
            {busy ? 'Saving…' : 'Save fix'}
          </button>
          <button type="button" className="btn btn-sm btn-quiet" disabled={busy} onClick={onCancel}>
            Cancel
          </button>
          <button type="button" className="lib-fix fix-delete" disabled={busy} onClick={() => setDeleting(true)}>
            Delete this upload
          </button>
        </div>
      )}
    </div>
  )
}