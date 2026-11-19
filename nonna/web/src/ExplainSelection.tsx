// Highlight any contract wording, click "Explain", and Nonna explains it in plain English.
// Works on text marked with data-explain (clause text, full contracts, drafts). If the
// text has a data-contract-id, Nonna also quotes the contract's own definitions.
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { explainPhrase } from './nonnaApi'
import type { Explanation } from './nonnaApi'

interface Picked {
  phrase: string
  context: string
  contractId: number | null
  x: number // where the highlight starts, left to right
  top: number // the highlight's top and bottom on screen, to open the panel above or below it
  bottom: number
}

const GAP = 8
const EDGE = 12
const PANEL_WIDTH = 380

const MAX_PHRASE = 600
const CONTEXT_AROUND = 700 // characters on each side, so Claude sees the sentence, not the whole contract

function pickFromSelection(): Picked | null {
  const selection = window.getSelection()
  if (!selection || selection.isCollapsed || selection.rangeCount === 0) return null
  const phrase = selection
    .toString()
    .replace(/\s+/g, ' ')
    .trim()
    // A highlight of "Deliverables" often grabs the contract's quote marks too
    .replace(/^["'\u201c\u201d\u2018\u2019(]+|["'\u201c\u201d\u2018\u2019),.;:]+$/g, '')
    .trim()
  if (phrase.length < 2 || phrase.length > MAX_PHRASE) return null

  const range = selection.getRangeAt(0)
  const start = range.startContainer instanceof Element ? range.startContainer : range.startContainer.parentElement
  const container = start?.closest<HTMLElement>('[data-explain]')
  if (!container || !container.contains(range.endContainer)) return null

  // The passage around the phrase
  const whole = (container.textContent ?? '').replace(/\s+/g, ' ')
  const at = Math.max(0, whole.indexOf(phrase))
  const context = whole.slice(Math.max(0, at - CONTEXT_AROUND), at + phrase.length + CONTEXT_AROUND)

  const rect = range.getBoundingClientRect()
  const id = Number(container.dataset.contractId)
  return {
    phrase,
    context,
    contractId: Number.isFinite(id) && id > 0 ? id : null,
    x: Math.min(Math.max(EDGE, rect.left), window.innerWidth - PANEL_WIDTH - EDGE),
    top: rect.top,
    bottom: rect.bottom,
  }
}

export default function ExplainSelection() {
  const [picked, setPicked] = useState<Picked | null>(null)
  const [open, setOpen] = useState(false)
  const [result, setResult] = useState<Explanation | null>(null)
  const [error, setError] = useState('')
  const panel = useRef<HTMLDivElement>(null)
  const [panelTop, setPanelTop] = useState<number | null>(null)

  // Open below the highlight if it fits, above it if not, and always fully on screen
  useLayoutEffect(() => {
    if (!open || !picked || !panel.current) return
    const height = panel.current.offsetHeight
    const below = picked.bottom + GAP
    const above = picked.top - GAP - height
    if (below + height <= window.innerHeight - EDGE) setPanelTop(below)
    else if (above >= EDGE) setPanelTop(above)
    else setPanelTop(Math.max(EDGE, window.innerHeight - EDGE - height))
  }, [open, picked, result, error])

  useEffect(() => {
    function onSelect(event: Event) {
      // Clicks on the Explain button or inside the panel shouldn't reset it
      if (event.target instanceof Element && event.target.closest('.explain-button, .explain-panel')) return
      setTimeout(() => {
        setOpen(false)
        setResult(null)
        setError('')
        setPicked(pickFromSelection())
      }, 0)
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setOpen(false)
        setPicked(null)
      } else if (event.shiftKey) {
        onSelect(event)
      }
    }
    const hide = () => !open && setPicked(null)
    document.addEventListener('mouseup', onSelect)
    document.addEventListener('keyup', onKey)
    window.addEventListener('scroll', hide, true)
    return () => {
      document.removeEventListener('mouseup', onSelect)
      document.removeEventListener('keyup', onKey)
      window.removeEventListener('scroll', hide, true)
    }
  }, [open])

  async function ask() {
    if (!picked) return
    setPanelTop(null)
    setOpen(true)
    setError('')
    setResult(null)
    try {
      setResult(await explainPhrase(picked.phrase, picked.context, picked.contractId))
    } catch (err) {
      setError(err instanceof Error ? err.message : "Nonna couldn't explain that.")
    }
  }

  if (!picked) return null

  if (!open) {
    return (
      <button
        type="button"
        className="explain-button"
        style={{ left: picked.x, top: Math.min(picked.bottom + GAP, window.innerHeight - 48) }}
        // Keep the highlight while clicking
        onMouseDown={(event) => event.preventDefault()}
        onClick={() => void ask()}
      >
        ✨ Ask Nonna to explain
      </button>
    )
  }

  return (
    <div
      ref={panel}
      className="explain-panel"
      style={{ left: picked.x, top: panelTop ?? picked.bottom + GAP, visibility: panelTop === null ? 'hidden' : 'visible' }}
      role="dialog"
      aria-label="Plain-English explanation"
    >
      <div className="explain-head">
        <p className="explain-phrase">{picked.phrase.length > 140 ? `${picked.phrase.slice(0, 140)}…` : picked.phrase}</p>
        <button
          type="button"
          className="explain-close"
          aria-label="Close"
          onClick={() => {
            setOpen(false)
            setPicked(null)
          }}
        >
          ×
        </button>
      </div>

      {!result && !error && <p className="thinking">Nonna is reading it…</p>}
      {error && <p className="intake-error">⚠ {error}</p>}
      {result && (
        <>
          <p className="explain-text">{result.explanation}</p>
          {result.definitions.map((d) => (
            <div key={d.term} className="explain-definition">
              <p className="explain-definition-label">
                How this contract defines “{d.term}”{d.section ? ` (§${d.section})` : ''}
              </p>
              <blockquote>{d.text}</blockquote>
            </div>
          ))}
          <p className="explain-note">
            {result.definitions.length > 0
              ? 'Definitions are quoted word for word from the contract. '
              : ''}
            Plain-English explanation by Claude, not legal advice.
          </p>
        </>
      )}
    </div>
  )
}