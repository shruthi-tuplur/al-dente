// Which term controls: where an SOW says something different from its MSA.
// Nonna lines up the pieces (both terms, the order-of-precedence clause, what the SOW says
// about the MSA section), all checked in code. The attorney makes the call. Nonna never does.
import { useEffect, useState } from 'react'
import ClauseBlock from './ClauseBlock'
import { SourceLink } from './LibraryLink'
import { formatDate } from './format'
import { CAN_EDIT, fetchPrecedence, recordPrecedenceCall } from './nonnaApi'
import type { Controls, PrecedenceReport, TermConflict, TermSide } from './nonnaApi'

function sideLabel(kind: 'MSA' | 'SOW', side: TermSide): string {
  const name = kind === 'MSA' ? 'MSA' : shortName(side.source.title, side.source.contract_type)
  return side.section_number ? `${name} §${side.section_number}` : name
}

// "Statement of Work No. 2: Tech Transfer" → "SOW No. 2"
function shortName(title: string, type: string): string {
  const number = title.match(/No\.\s*(\d+)/i)
  const kind = type === 'change_order' ? 'Change order' : 'SOW'
  return number ? `${kind} No. ${number[1]}` : title
}

function Side({ kind, side, wins }: { kind: 'MSA' | 'SOW'; side: TermSide; wins: boolean }) {
  return (
    <div className={wins ? 'tc-side tc-side-wins' : 'tc-side'}>
      <p className="tc-side-label">
        {sideLabel(kind, side)}
        {side.amended_by ? ' (as amended)' : ''}
        {wins && <span className="tc-wins">Controls</span>}
      </p>
      <p className="tc-side-value">{side.value}</p>
      <p className="tc-side-source">
        <SourceLink target={{ contractId: side.source.id, section: side.section_number, quote: null }}>
          {side.source.title}, {formatDate(side.source.effective_date)}
        </SourceLink>
        {side.amended_by ? ` · changed by ${side.amended_by.title}` : ''}
        {side.review_status === 'pending' ? ' · still waiting for review' : ''}
      </p>
    </div>
  )
}

function CallForm({ conflict, onSaved, onCancel }: { conflict: TermConflict; onSaved: () => void; onCancel?: () => void }) {
  const [controls, setControls] = useState<Controls | null>(null)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function save() {
    if (!controls) return setError('Pick which term controls.')
    if (!note.trim()) return setError('Say why, so the next person knows.')
    setBusy(true)
    setError('')
    try {
      await recordPrecedenceCall(conflict.sow.clause_id, controls, note.trim())
      onSaved()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save that call.")
    } finally {
      setBusy(false)
    }
  }

  const options: { value: Controls; label: string }[] = [
    { value: 'msa', label: `${sideLabel('MSA', conflict.msa)} controls (${conflict.msa.value})` },
    { value: 'sow', label: `${sideLabel('SOW', conflict.sow)} controls (${conflict.sow.value})` },
  ]

  return (
    <div className="tc-form">
      <p className="correction-title">Your call</p>
      <div className="tc-options" role="radiogroup" aria-label="Which term controls">
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={controls === option.value}
            className={controls === option.value ? 'tc-option tc-option-on' : 'tc-option'}
            onClick={() => {
              setControls(option.value)
              setError('')
            }}
          >
            {option.label}
          </button>
        ))}
      </div>
      <textarea
        className="review-note"
        rows={2}
        value={note}
        onChange={(e) => {
          setNote(e.target.value)
          setError('')
        }}
        placeholder="Your reading of the precedence clause and the SOW, and anything to follow up on."
        aria-label="Why this term controls"
      />
      {error && <p className="intake-error">{error}</p>}
      <div className="intake-actions">
        <button type="button" className="btn btn-sm btn-primary" disabled={busy} onClick={() => void save()}>
          {busy ? 'Saving…' : 'Save call'}
        </button>
        {onCancel && (
          <button type="button" className="btn btn-sm btn-quiet" disabled={busy} onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
    </div>
  )
}

function ConflictCard({
  conflict,
  onChanged,
  hideHead = false,
}: {
  conflict: TermConflict
  onChanged?: () => void
  hideHead?: boolean // the Library's compact row already shows the term and the badge
}) {
  const [changing, setChanging] = useState(false)
  const { msa, sow, rule, check, call } = conflict
  const msaName = check.msa_section ? `MSA §${check.msa_section}` : 'the MSA section'

  return (
    <li className="tc-card">
    {!hideHead && (
      <div className="tc-head">
        <span className={call ? 'badge tc-badge-done' : 'badge badge-tier-outside'}>{call ? 'Call made' : 'Needs a call'}</span>
        <span className="tc-term">{conflict.label}</span>
        <span className="tc-where">· {sow.source.title}</span>
      </div>
    )}

      <div className="tc-sides">
        <Side kind="MSA" side={msa} wins={call?.controls === 'msa'} />
        <span className="tc-vs" aria-hidden="true">vs</span>
        <Side kind="SOW" side={sow} wins={call?.controls === 'sow'} />
      </div>

      <div className="tc-checks">
        <p className="tc-subhead">What the SOW says about {msaName}</p>
        {check.msa_section ? (
          <ul>
            <li className={check.names_section ? 'tc-yes' : 'tc-no'}>
              {check.names_section ? '✓' : '✕'} Names {msaName}
            </li>
            <li className={check.says_supersedes ? 'tc-yes' : 'tc-no'}>
              {check.says_supersedes ? '✓' : '✕'} Says it supersedes or replaces it
            </li>
          </ul>
        ) : (
          <p className="tc-note">Nonna doesn't know which MSA section to look for, so read the SOW yourself.</p>
        )}
        {check.quote && (
          <blockquote className="tc-quote" data-explain="" data-contract-id={sow.source.id}>
            “{check.quote}” <cite>{check.quote_source}</cite>
          </blockquote>
        )}
      </div>

      {rule ? (
        <details className="lib-wording" open={!call}>
          <summary>
            MSA §{rule.section_number} {rule.heading}
            {rule.amended ? ' (as amended)' : ''}
          </summary>
          <ClauseBlock text={rule.text} contractId={rule.source.id} />
        </details>
      ) : (
        <p className="tc-note">
          Nonna couldn't find an order-of-precedence clause in the MSA. Check the MSA by hand before deciding.
        </p>
      )}

      {call && !changing ? (
        <div className="tc-call">
          <p>
            ⚖ {call.decided_by} decided{' '}
            <strong>
              {call.controls === 'msa' ? `${sideLabel('MSA', msa)} controls (${msa.value})` : `${sideLabel('SOW', sow)} controls (${sow.value})`}
            </strong>{' '}
            on {formatDate(call.decided_at.slice(0, 10))}. Why: {call.note}
          </p>
          {onChanged && (
            <button type="button" className="lib-fix" onClick={() => setChanging(true)}>
              Change call
            </button>
          )}
        </div>
      ) : onChanged ? (
        <CallForm
          conflict={conflict}
          onSaved={() => {
            setChanging(false)
            onChanged()
          }}
          onCancel={changing ? () => setChanging(false) : undefined}
        />
      ) : (
                <p className="tc-note">
          Waiting for an attorney's call.{CAN_EDIT ? ' Make it in the Library.' : ''}
        </p>
      )}
    </li>
  )
}

// The list of conflicts. onChanged turns on making calls (the Library), leave it out in chat.
export function PrecedenceList({ report, onChanged }: { report: PrecedenceReport; onChanged?: () => void }) {
  if (report.conflicts.length === 0) {
    return <p className="card-empty">Every SOW matches the MSA on the key terms Nonna tracks.</p>
  }
  return (
    <ul className="tc-list">
      {report.conflicts.map((conflict) => (
        <ConflictCard key={conflict.sow.clause_id} conflict={conflict} onChanged={onChanged} />
      ))}
    </ul>
  )
}

// One conflict as a single line: term, the two values, and the call. Click for the full card.
function ConflictRow({ conflict, onChanged }: { conflict: TermConflict; onChanged: () => void }) {
    const { msa, sow, call } = conflict
    const [open, setOpen] = useState(!call) // open ones start open, so the call is right there
    const outcome = call
      ? `${call.controls === 'msa' ? 'MSA' : shortName(sow.source.title, sow.source.contract_type)} controls`
      : 'Needs your call'
  
    return (
      <li className={open ? 'term-line term-line-open' : 'term-line'}>
        <button type="button" className="term-line-row tc-row" aria-expanded={open} onClick={() => setOpen(!open)}>
          <span className="term-line-value">
            <span className="term-line-name">{conflict.label}</span>
            <span className="term-line-source">{sideLabel('SOW', sow)}</span>
          </span>
          <span className="tc-row-values">
            <span className={call?.controls === 'msa' ? 'tc-row-win' : ''}>MSA: {msa.value}</span>
            <span className="tc-row-vs">vs</span>
            <span className={call?.controls === 'sow' ? 'tc-row-win' : ''}>SOW: {sow.value}</span>
          </span>
          <span className="term-line-badge">
            <span className={call ? 'badge tc-badge-done' : 'badge badge-tier-outside'}>{outcome}</span>
          </span>
          <span className="term-line-count">
            {call ? formatDate(call.decided_at.slice(0, 10)) : ''}
            <span className="term-line-chevron" aria-hidden="true">
              {open ? '▾' : '▸'}
            </span>
          </span>
        </button>
        {open && (
          <ul className="tc-list tc-row-detail">
                      <ConflictCard conflict={conflict} onChanged={CAN_EDIT ? onChanged : undefined} hideHead />
          </ul>
        )}
      </li>
    )
  }
  
  // The section on a vendor's Overview: one line per SOW term that disagrees with the MSA.
  // Hidden when nothing conflicts. onReport lets the page show the open count elsewhere.
  export default function WhichTermControls({
    counterpartyId,
    reloadKey,
    onReport,
  }: {
    counterpartyId: number
    reloadKey?: unknown
    onReport?: (report: PrecedenceReport) => void
  }) {
    const [report, setReport] = useState<PrecedenceReport | null>(null)
    const [error, setError] = useState('')
    const [loadCount, setLoadCount] = useState(0)
  
    useEffect(() => {
      let current = true
      setError('')
      fetchPrecedence(counterpartyId)
        .then((data) => {
          if (!current) return
          setReport(data)
          onReport?.(data)
        })
        .catch((err: unknown) => current && setError(err instanceof Error ? err.message : "Couldn't check the SOWs."))
      return () => {
        current = false
      }
      // onReport is left out on purpose: a new function each render would reload forever
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [counterpartyId, reloadKey, loadCount])
  
    if (error) return <p className="intake-error">⚠ {error}</p>
    if (!report || report.counterparty_id !== counterpartyId || report.conflicts.length === 0) return null
  
    return (
      <section className="overview-section">
        <p className="overview-label">
          Which term controls <span className="lib-group-count">{report.conflicts.length}</span>
        </p>
        <p className="overview-hint">
          Where an SOW says something different from the MSA. Nonna lines up the evidence,{' '}
        {CAN_EDIT ? 'you make the call.' : 'and an attorney makes the call.'}
        </p>
        <ul className="term-table">
          {report.conflicts.map((conflict) => (
            <ConflictRow key={conflict.sow.clause_id} conflict={conflict} onChanged={() => setLoadCount((n) => n + 1)} />
          ))}
        </ul>
      </section>
    )
  }