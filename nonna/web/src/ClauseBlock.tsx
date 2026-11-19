import { useState } from 'react'
import { tidyClauseText } from './format'

// The exact text of a clause, straight from the stored contract, with a copy button
// contractId lets "Ask Nonna to explain" quote the contract's own definitions
export default function ClauseBlock({ text, contractId }: { text: string; contractId?: number }) {
  const [copied, setCopied] = useState(false)
  const tidy = tidyClauseText(text)

  async function copy() {
    try {
      await navigator.clipboard.writeText(tidy)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      setCopied(false)
    }
  }

  return (
    <div className="clause-block">
      <blockquote className="clause-text" data-explain="" data-contract-id={contractId}>
        {tidy}
      </blockquote>
      <button type="button" className="btn btn-sm btn-quiet clause-copy" onClick={() => void copy()}>
        {copied ? 'Copied ✓' : 'Copy'}
      </button>
    </div>
  )
}