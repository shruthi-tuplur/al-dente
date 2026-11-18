// Drafting from history: start a new SOW from what was already agreed with this vendor.
// Standard wording is copied as is, Claude adapts the deal parts from the brief, and code sets
// the exact things (SOW number, payment terms) and checks Claude's numbers.
import { useState } from 'react'
import { downloadDraft, makeDraft } from './nonnaApi'
import type { Draft, DraftSection } from './nonnaApi'

const LABELS: Record<DraftSection['label'], string> = {
  verbatim: 'Verbatim',
  adapted: 'Adapted',
  new: 'New',
}

function sectionTitle(section: DraftSection): string {
  if (section.kind === 'title') return 'Title'
  if (section.kind === 'preamble') return 'Opening paragraph'
  if (section.kind === 'signatures') return 'Signatures'
  return `${section.number}. ${section.heading}`
}

// [blanks] highlighted so they're easy to spot
function WithBlanks({ text }: { text: string }) {
  return (
    <>
      {text.split(/(\[[^\]]+\])/).map((piece, i) =>
        piece.startsWith('[') ? (
          <mark key={i} className="draft-blank">
            {piece}
          </mark>
        ) : (
          <span key={i}>{piece}</span>
        ),
      )}
    </>
  )
}

// Paragraphs, with " | " rows shown as a table
function SectionText({ text }: { text: string }) {
  const lines = text.split('\n').filter((line) => line.trim())
  const blocks: (string | string[][])[] = []
  for (const line of lines) {
    if (line.includes(' | ')) {
      const row = line.split(' | ').map((cell) => cell.trim())
      const last = blocks[blocks.length - 1]
      if (Array.isArray(last)) last.push(row)
      else blocks.push([row])
    } else {
      blocks.push(line)
    }
  }
  return (
    <div className="draft-text">
      {blocks.map((block, i) =>
        Array.isArray(block) ? (
          <table key={i} className="draft-table">
            <tbody>
              {block.map((row, r) => (
                <tr key={r}>
                  {row.map((cell, c) =>
                    r === 0 ? (
                      <th key={c}>{cell}</th>
                    ) : (
                      <td key={c}>
                        <WithBlanks text={cell} />
                      </td>
                    ),
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p key={i}>
            <WithBlanks text={block} />
          </p>
        ),
      )}
    </div>
  )
}

// Word-by-word comparison of the old wording and the new
function wordDiff(before: string, after: string): { word: string; kind: 'same' | 'added' | 'removed' }[] {
  const a = before.split(/\s+/).filter(Boolean)
  const b = after.split(/\s+/).filter(Boolean)
  const table: number[][] = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0))
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      table[i][j] = a[i] === b[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1])
    }
  }
  const out: { word: string; kind: 'same' | 'added' | 'removed' }[] = []
  let i = 0
  let j = 0
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      out.push({ word: a[i], kind: 'same' })
      i++
      j++
    } else if (table[i + 1][j] >= table[i][j + 1]) {
      out.push({ word: a[i++], kind: 'removed' })
    } else {
      out.push({ word: b[j++], kind: 'added' })
    }
  }
  while (i < a.length) out.push({ word: a[i++], kind: 'removed' })
  while (j < b.length) out.push({ word: b[j++], kind: 'added' })
  return out
}

// Compared line by line, so each paragraph or table row shows its own changes
function Changes({ before, after }: { before: string; after: string }) {
  const oldLines = before.split('\n').filter((line) => line.trim())
  const newLines = after.split('\n').filter((line) => line.trim())
  const count = Math.max(oldLines.length, newLines.length)
  return (
    <div className="draft-diff">
      {Array.from({ length: count }, (_, row) => (
        <p key={row}>
          {wordDiff(oldLines[row] ?? '', newLines[row] ?? '').map((part, i) => (
            <span key={i} className={`draft-diff-${part.kind}`}>
              {part.word === '|' ? <span className="draft-diff-bar">|</span> : part.word}{' '}
            </span>
          ))}
        </p>
      ))}
    </div>
  )
}

function SectionCard({
  section,
  edited,
  onEdit,
}: {
  section: DraftSection
  edited: boolean
  onEdit: (text: string) => void
}) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(section.text)

  return (
    <li className={`draft-section draft-${section.label}`}>
      <div className="draft-section-head">
        <span className={`badge draft-badge-${edited ? 'edited' : section.label}`}>
          {edited ? 'Edited by you' : LABELS[section.label]}
        </span>
        <span className="draft-section-title">{sectionTitle(section)}</span>
        <span className="draft-source">From {section.source}</span>
      </div>

      {section.note && <p className="draft-note">{section.note}</p>}
      {section.checks.length > 0 && (
        <ul className="draft-checks">
          {section.checks.map((check) => (
            <li key={check}>⚠ {check}</li>
          ))}
        </ul>
      )}

      {editing ? (
        <div className="draft-edit">
          <textarea
            className="review-note"
            rows={Math.min(14, Math.max(4, text.split('\n').length + 2))}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <p className="draft-hint">One paragraph per line. Table rows use " | " between cells.</p>
          <div className="playbook-actions">
            <button
              type="button"
              className="btn btn-sm btn-primary"
              onClick={() => {
                onEdit(text)
                setEditing(false)
              }}
            >
              Save
            </button>
            <button
              type="button"
              className="btn btn-sm btn-quiet"
              onClick={() => {
                setText(section.text)
                setEditing(false)
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <>
          <SectionText text={section.text} />
          <div className="draft-actions">
            <button type="button" className="lib-fix" onClick={() => setEditing(true)}>
              Edit
            </button>
          </div>
        </>
      )}

      {section.original && section.original !== section.text && (
        <details className="lib-wording">
          <summary>Show what changed</summary>
          <Changes before={section.original} after={section.text} />
        </details>
      )}
    </li>
  )
}

// The draft as a short card in the chat, with a button to open it in the Draft tab
export function DraftSummaryCard({ draft, onOpen }: { draft: Draft; onOpen?: (draft: Draft) => void }) {
  const [downloading, setDownloading] = useState(false)
  const [error, setError] = useState('')
  const verbatim = draft.sections.filter((s) => s.label === 'verbatim').length
  const checks = draft.sections.flatMap((s) => s.checks)
  const changes = draft.sections.filter((s) => s.note && s.note !== 'Adapted from your brief.')

  async function download() {
    setDownloading(true)
    setError('')
    try {
      await downloadDraft(draft)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't make the Word file.")
    } finally {
      setDownloading(false)
    }
  }

  return (
    <div className="draft-card">
      <p className="card-subtitle">
        Started from {draft.template} · {verbatim} verbatim · {draft.sections.length - verbatim} adapted ·{' '}
        {draft.blanks} {draft.blanks === 1 ? 'blank' : 'blanks'} to fill in
      </p>
      {changes.length > 0 && (
        <ul className="draft-card-notes">
          {changes.map((s, i) => (
            <li key={i}>
              <strong>{sectionTitle(s)}:</strong> {s.note}
            </li>
          ))}
        </ul>
      )}
      {checks.length > 0 && (
        <ul className="draft-checks">
          {checks.map((check) => (
            <li key={check}>⚠ {check}</li>
          ))}
        </ul>
      )}
      {error && <p className="intake-error">⚠ {error}</p>}
      <div className="playbook-actions">
        {onOpen && (
          <button type="button" className="btn btn-sm btn-primary" onClick={() => onOpen(draft)}>
            Open in Draft tab
          </button>
        )}
        <button type="button" className="btn btn-sm btn-quiet" onClick={download} disabled={downloading}>
          {downloading ? 'Making the file…' : 'Download .docx'}
        </button>
      </div>
    </div>
  )
}

export default function DraftTab({
  counterpartyId,
  vendorName,
  initialDraft = null,
}: {
  counterpartyId: number
  vendorName: string
  initialDraft?: Draft | null
}) {
  const [brief, setBrief] = useState(initialDraft?.brief ?? '')
  const [draft, setDraft] = useState<Draft | null>(initialDraft)
  const [edited, setEdited] = useState<Set<number>>(new Set())
  const [working, setWorking] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [error, setError] = useState('')

  async function start() {
    if (brief.trim().length < 10) {
      setError('Tell Nonna a little about the new project first.')
      return
    }
    setWorking(true)
    setError('')
    try {
      setDraft(await makeDraft(counterpartyId, brief))
      setEdited(new Set())
    } catch (err) {
      setError(err instanceof Error ? err.message : "Nonna couldn't make that draft.")
    } finally {
      setWorking(false)
    }
  }

  function editSection(index: number, text: string) {
    if (!draft) return
    const sections = draft.sections.map((s, i) => (i === index ? { ...s, text } : s))
    const blanks = sections.reduce((n, s) => n + (s.text.match(/\[[^\]]+\]/g)?.length ?? 0), 0)
    setDraft({ ...draft, sections, blanks })
    setEdited(new Set(edited).add(index))
  }

  async function download() {
    if (!draft) return
    setDownloading(true)
    setError('')
    try {
      await downloadDraft(draft)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't make the Word file.")
    } finally {
      setDownloading(false)
    }
  }

  if (!draft) {
    return (
      <div className="draft-start">
        <p className="draft-intro">
          Start the next SOW with {vendorName} from what you've already agreed. Standard wording is copied
          word for word, Claude adapts only the deal parts from your brief, and Nonna sets the payment terms
          to what was agreed in the MSA. Nothing is saved until you download it.
        </p>
        <label className="correction-field">
          What's the new project?
          <textarea
            className="review-note"
            rows={5}
            value={brief}
            onChange={(e) => setBrief(e.target.value)}
            placeholder="Phase 2 clinical manufacturing of AUR-104: three cGMP batches at 200 L, plus stability testing. Total $3.6M across four milestones. Done by December 2027."
          />
        </label>
        {error && <p className="intake-error">⚠ {error}</p>}
        <button type="button" className="btn btn-primary" onClick={start} disabled={working}>
          {working ? 'Nonna is drafting…' : 'Draft it'}
        </button>
      </div>
    )
  }

  const adapted = draft.sections.filter((s) => s.label !== 'verbatim').length
  const checks = draft.sections.reduce((n, s) => n + s.checks.length, 0)

  return (
    <div className="draft">
      <div className="draft-summary">
        <div>
          <p className="draft-summary-title">
            Draft SOW No. {draft.number} with {draft.counterparty_name}
          </p>
          <p className="card-subtitle">
            Started from {draft.template} · {draft.sections.length - adapted} verbatim · {adapted} adapted ·{' '}
            {draft.blanks} {draft.blanks === 1 ? 'blank' : 'blanks'} to fill in
            {checks > 0 ? ` · ${checks} ${checks === 1 ? 'thing' : 'things'} to check` : ''}
          </p>
        </div>
        <div className="playbook-actions">
          <button type="button" className="btn btn-sm btn-primary" onClick={download} disabled={downloading}>
            {downloading ? 'Making the file…' : 'Download .docx'}
          </button>
          <button type="button" className="btn btn-sm btn-quiet" onClick={() => setDraft(null)}>
            Start over
          </button>
        </div>
      </div>
      {error && <p className="intake-error">⚠ {error}</p>}

      <ul className="draft-sections">
        {draft.sections.map((section, i) => (
          <SectionCard
            key={`${draft.number}-${i}`}
            section={section}
            edited={edited.has(i)}
            onEdit={(text) => editSection(i, text)}
          />
        ))}
      </ul>
    </div>
  )
}