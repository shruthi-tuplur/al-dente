// A one-page summary of a vendor relationship for someone who won't read the contract.
// Opens over the Library; "Print or save as PDF" prints just the page.
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { formatDate, todayISO } from './format'
import { fetchVendorDeadlines } from './nonnaApi'
import type { CounterpartyLibrary } from './nonnaApi'
import { buildOnePager } from './onePagerData'
import type { OnePagerData } from './onePagerData'
import { PlaybookBadge } from './Playbook'

export default function OnePager({ library, onClose }: { library: CounterpartyLibrary; onClose: () => void }) {
  const [data, setData] = useState<OnePagerData | null>(null)
  const [error, setError] = useState('')
  const today = todayISO()

  useEffect(() => {
    let current = true
    fetchVendorDeadlines(library.counterparty.id)
      .then((deadlines) => deadlines.rows)
      .catch(() => []) // still useful without dates, so carry on
      .then((rows) => current && setData(buildOnePager(library, rows)))
      .catch((err: unknown) => current && setError(err instanceof Error ? err.message : "Couldn't build the one-pager."))
    return () => {
      current = false
    }
  }, [library])

  // While it's open, printing prints only the one-pager. Escape closes it.
  useEffect(() => {
    document.body.classList.add('has-one-pager')
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => {
      document.body.classList.remove('has-one-pager')
      window.removeEventListener('keydown', onKey)
    }
  }, [onClose])

  return createPortal(
    <div className="one-pager-overlay" role="dialog" aria-modal="true" aria-label={`One-pager for ${library.counterparty.name}`}>
      <div className="one-pager-toolbar">
        <button type="button" className="btn btn-sm btn-primary" onClick={() => window.print()} disabled={!data}>
          Print or save as PDF
        </button>
        <button type="button" className="btn btn-sm btn-quiet one-pager-close" onClick={onClose}>
          Close
        </button>
      </div>

      <article className="one-pager">
        {error && <p className="intake-error">⚠ {error}</p>}
        {!data && !error && <p className="thinking">Putting it together…</p>}
        {data && (
          <>
            <header className="op-header">
              <p className="op-eyebrow">Relationship summary</p>
              <h1 className="op-vendor">{data.vendor}</h1>
              <p className="op-meta">
                {data.legalNames.join(' · ')} · Prepared {formatDate(today)}
              </p>
            </header>

            <section className="op-section">
              <h2 className="op-heading">The short version</h2>
              <ul className="op-bullets">
                {data.shortVersion.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </section>

            <section className="op-section">
              <h2 className="op-heading">Key terms</h2>
              {data.terms.length === 0 ? (
                <p className="op-empty">Nothing has been reviewed and agreed yet.</p>
              ) : (
                <table className="op-table">
                  <thead>
                    <tr>
                      <th scope="col">Term</th>
                      <th scope="col">What we agreed</th>
                      <th scope="col">Compared to our standard</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.terms.map((term) => (
                      <tr key={term.type}>
                        <th scope="row">
                          <span className="op-term">{term.label}</span>
                          <span className="op-meaning">{term.meaning}</span>
                        </th>
                        <td>
                          <span className="op-value">{term.value}</span>
                          {term.from && <span className="op-from">{term.from}</span>}
                        </td>
                        <td>{term.playbook ? <PlaybookBadge assessment={term.playbook} /> : <span className="op-from">Not checked</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>

            {data.headsUp.length > 0 && (
              <section className="op-section">
                <h2 className="op-heading">Good to know</h2>
                <ul className="op-bullets">
                  {data.headsUp.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </section>
            )}

            <section className="op-section">
              <h2 className="op-heading">Contracts on file</h2>
              <ul className="op-contracts">
                {data.contracts.map((c) => (
                  <li key={`${c.kind}-${c.title}-${c.date}`}>
                    <span className="op-kind">{c.kind}</span>
                    <span className="op-contract-title">{c.title}</span>
                    <span className="op-from">
                      {c.date}
                      {c.note ? ` · ${c.note}` : ''}
                    </span>
                  </li>
                ))}
              </ul>
            </section>

            <footer className="op-footer">
              Prepared by Nonna from contracts reviewed by Legal. This is a summary, not the contract, so check with
              Legal before relying on it.
            </footer>
          </>
        )}
      </article>
    </div>,
    document.body,
  )
}