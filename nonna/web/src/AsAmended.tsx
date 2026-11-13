import { useState } from 'react'
import { formatDate, tidyClauseText } from './format'
import { fetchAsAmended } from './nonnaApi'
import type { AmendedContract, AmendedSection } from './nonnaApi'

const STATUS_LABEL: Record<AmendedSection['status'], string> = {
  original: '',
  replaced: 'Amended',
  added: 'Added',
  deleted: 'Deleted',
}

// One section of a contract as it reads today. Changed sections say which amendment changed them.
export function AmendedSectionView({ section }: { section: AmendedSection }) {
  const changed = section.status !== 'original'
  return (
    <div className={changed ? `amended-section amended-${section.status}` : 'amended-section'}>
      {changed && section.changed_by && (
        <p className="amended-tag">
          <span className="badge badge-pending">{STATUS_LABEL[section.status]}</span>
          by {section.changed_by.title} · {formatDate(section.changed_by.effective_date)}
        </p>
      )}
      {section.status === 'deleted' ? (
        <p className="amended-gone">Section {section.number} was deleted.</p>
      ) : (
        <div className="amended-text">{tidyClauseText(section.text)}</div>
      )}
      {section.original_text && (
        <details className="lib-wording">
          <summary>{section.status === 'deleted' ? 'Show what it said' : 'Show original wording'}</summary>
          <div className="amended-text amended-original">{tidyClauseText(section.original_text)}</div>
        </details>
      )}
    </div>
  )
}

// Things an amendment says that Nonna couldn't apply with confidence
export function Unresolved({ items }: { items: AmendedContract['unresolved'] }) {
  if (items.length === 0) return null
  return (
    <div className="amended-unresolved">
      <p className="vendor-note-label">Check these by hand:</p>
      <ul>
        {items.map((u, i) => (
          <li key={i}>
            {u.amendment.title}
            {u.section ? `, Section ${u.section}` : ''}: “{u.wording}”
          </li>
        ))}
      </ul>
    </div>
  )
}

// The whole contract as it reads today, for the library
export default function AsAmended({ contractId, amendmentCount }: { contractId: number; amendmentCount: number }) {
  const [open, setOpen] = useState(false)
  const [data, setData] = useState<AmendedContract | null>(null)
  const [error, setError] = useState('')

  async function toggle() {
    const next = !open
    setOpen(next)
    if (next && data === null) {
      try {
        setData(await fetchAsAmended(contractId))
      } catch (err) {
        setError(err instanceof Error ? err.message : "Nonna couldn't apply the amendments.")
      }
    }
  }

  return (
    <div className="full-contract">
      <button type="button" className="btn btn-sm btn-primary" aria-expanded={open} onClick={() => void toggle()}>
        {open ? 'Hide as amended' : `Read as amended (${amendmentCount} ${amendmentCount === 1 ? 'amendment' : 'amendments'})`}
      </button>

      {open && (
        <>
          {error && <p className="intake-error">⚠ {error}</p>}
          {!error && data === null && <p className="thinking">Loading…</p>}
          {data && (
            <div className="amended-view">
              <p className="card-subtitle">
                How this contract reads today, with {data.amendments.map((a) => a.title).join(', ')} applied.{' '}
                {data.changed_count} {data.changed_count === 1 ? 'section changed' : 'sections changed'}. Built by
                Nonna from the signed documents, so confirm against them before relying on it.
              </p>
              <Unresolved items={data.unresolved} />
              <div className="full-contract-text amended-doc" tabIndex={0} aria-label="Contract as amended">
                {data.sections.map((section) => (
                  <AmendedSectionView key={`${section.number}-${section.status}`} section={section} />
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}