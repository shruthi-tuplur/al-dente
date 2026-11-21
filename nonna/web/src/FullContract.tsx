import { useEffect, useState } from 'react'
import { tidyClauseText } from './format'
import { fetchContractText } from './nonnaApi'
import type { ContractText } from './nonnaApi'

// The whole contract, read inside the library. Loads when it opens.
// (The button that opens it lives in the contract's toolbar in the Library.)
export default function FullContract({ contractId }: { contractId: number }) {
  const [contract, setContract] = useState<ContractText | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let current = true
    setContract(null)
    setError('')
    fetchContractText(contractId)
      .then((data) => current && setContract(data))
      .catch((err: unknown) => current && setError(err instanceof Error ? err.message : "Nonna couldn't load that contract."))
    return () => {
      current = false
    }
  }, [contractId])

  if (error) return <p className="intake-error">⚠ {error}</p>
  if (contract === null) return <p className="thinking">Loading…</p>
  return (
    <div
      className="full-contract-text"
      tabIndex={0}
      aria-label={`Full text of ${contract.title}`}
      data-explain=""
      data-contract-id={contractId}
    >
      {contract.full_text ? tidyClauseText(contract.full_text) : 'No text on file for this contract.'}
    </div>
  )
}