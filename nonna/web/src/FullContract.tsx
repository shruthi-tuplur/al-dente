import { useEffect, useRef, useState } from 'react'
import { tidyClauseText } from './format'
import type { LibraryTarget } from './LibraryLink'
import { fetchContractText } from './nonnaApi'
import type { ContractText } from './nonnaApi'

// Lowercase, one space between words, and a map back to where each character came from
function squash(text: string): { out: string; map: number[] } {
  let out = ''
  const map: number[] = []
  let space = false
  for (let i = 0; i < text.length; i++) {
    if (/\s/.test(text[i])) {
      if (!space && out.length > 0) {
        out += ' '
        map.push(i)
      }
      space = true
    } else {
      out += text[i].toLowerCase()
      map.push(i)
      space = false
    }
  }
  return { out, map }
}

// The paragraph's own number: "11.2 Cap on Liability" → "11.2", "Section 4. Fees" → "4"
function leadingNumber(paragraph: string): string | null {
  const match = paragraph.match(/^\s*(?:section\s+|§\s*)?(\d+(?:\.\d+)*)[.)]?\s/i)
  return match ? match[1] : null
}

// Where the target sits in the contract text, as [start, end], found in code.
// First by the clause's exact wording, then by its section number. Null if neither is there.
export function findTarget(text: string, target: LibraryTarget): [number, number] | null {
  if (target.quote) {
    const hay = squash(text)
    const quote = squash(tidyClauseText(target.quote)).out.trim()
    const probe = quote.slice(0, 120)
    const at = probe.length >= 20 ? hay.out.indexOf(probe) : -1
    if (at !== -1) {
      const last = at + quote.length - 1
      const whole = hay.out.slice(at, at + quote.length) === quote
      const end = whole ? hay.map[last] + 1 : text.indexOf('\n\n', hay.map[at])
      return [hay.map[at], end === -1 ? text.length : end]
    }
  }

  if (target.section) {
    const starts = [0]
    for (let i = text.indexOf('\n\n'); i !== -1; i = text.indexOf('\n\n', i + 2)) starts.push(i + 2)
    const first = starts.findIndex((s) => leadingNumber(text.slice(s, s + 40)) === target.section)
    if (first !== -1) {
      // Keep going through its subsections and unnumbered paragraphs, stop at the next section
      let next = first + 1
      while (next < starts.length) {
        const number = leadingNumber(text.slice(starts[next], starts[next] + 40))
        if (number !== null && !number.startsWith(`${target.section}.`)) break
        next++
      }
      const end = next < starts.length ? starts[next] - 2 : text.length
      return [starts[first], end]
    }
  }
  return null
}
// The whole contract, read inside the library. Loads when it opens.
// With a target (a link from chat), that part is highlighted and scrolled into view.
export default function FullContract({
    contractId,
    target = null,
    onLoaded,
  }: {
    contractId: number
    target?: LibraryTarget | null
    onLoaded?: (contract: ContractText) => void // the chat drawer uses this for its title
  }) {
    const [contract, setContract] = useState<ContractText | null>(null)
    const [error, setError] = useState('')
    const markRef = useRef<HTMLElement>(null)
  
    useEffect(() => {
      let current = true
      setContract(null)
      setError('')
      fetchContractText(contractId)
        .then((data) => {
          if (!current) return
          setContract(data)
          onLoaded?.(data)
        })
        .catch((err: unknown) => current && setError(err instanceof Error ? err.message : "Nonna couldn't load that contract."))
      return () => {
        current = false
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [contractId])
  
    const text = contract?.full_text ? tidyClauseText(contract.full_text) : null
    const range = text && target ? findTarget(text, target) : null
  
    useEffect(() => {
      if (range) markRef.current?.scrollIntoView({ block: 'center', behavior: 'smooth' })
    }, [range?.[0], range?.[1]]) // eslint-disable-line react-hooks/exhaustive-deps
  
    if (error) return <p className="intake-error">⚠ {error}</p>
    if (contract === null) return <p className="thinking">Loading…</p>
  
    const where = target?.section ? `§${target.section}` : 'that clause'
    return (
      <>
        {target && text && (target.section || target.quote) && (
          <p className="jump-note">
            {range
              ? `${where === 'that clause' ? 'The clause' : where} is highlighted below.`
              : `Nonna couldn't find ${where} in the text on file, so here's the whole contract.`}
          </p>
        )}
        <div
          className="full-contract-text"
          tabIndex={0}
          aria-label={`Full text of ${contract.title}`}
          data-explain=""
          data-contract-id={contractId}
        >
          {text === null ? (
            'No text on file for this contract.'
          ) : range ? (
            <>
              {text.slice(0, range[0])}
              <mark ref={markRef} className="jump-mark">
                {text.slice(range[0], range[1])}
              </mark>
              {text.slice(range[1])}
            </>
          ) : (
            text
          )}
        </div>
      </>
    )
  }