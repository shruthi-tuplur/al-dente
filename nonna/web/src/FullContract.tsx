import { useState } from 'react'
import { tidyClauseText } from './format'
import { fetchContractText } from './nonnaApi'
import type { ContractText } from './nonnaApi'

// Read the whole contract inside the library, or open the original file
export default function FullContract({ contractId }: { contractId: number }) {
  const [open, setOpen] = useState(false)
  const [contract, setContract] = useState<ContractText | null>(null)
  const [error, setError] = useState('')

  async function toggle() {
    const next = !open
    setOpen(next)
    if (next && contract === null) {
      try {
        setContract(await fetchContractText(contractId))
      } catch (err) {
        setError(err instanceof Error ? err.message : "Nonna couldn't load that contract.")
      }
    }
  }

  return (
    <div className="full-contract">
      <div className="intake-actions">
        <button type="button" className="btn btn-sm btn-quiet" aria-expanded={open} onClick={() => void toggle()}>
          {open ? 'Hide full contract' : 'Read full contract'}
        </button>
        <a className="btn btn-sm btn-quiet" href={`/api/contracts/${contractId}/file`} target="_blank" rel="noreferrer">
          Open original file ↗
        </a>
      </div>

      {open && (
        <>
          {error && <p className="intake-error">⚠ {error}</p>}
          {!error && contract === null && <p className="thinking">Loading…</p>}
          {contract && (
            <div className="full-contract-text" tabIndex={0} aria-label={`Full text of ${contract.title}`}>
              {contract.full_text ? tidyClauseText(contract.full_text) : 'No text on file for this contract.'}
            </div>
          )}
        </>
      )}
    </div>
  )
}