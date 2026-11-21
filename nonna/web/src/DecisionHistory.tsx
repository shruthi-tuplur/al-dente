// Decision history: everything anyone decided about a vendor, in one timeline.
// Read-only. Every line comes straight from Nonna's permanent records, with no AI in between.
import { useEffect, useMemo, useState } from 'react'
import { todayISO } from './format'
import { fetchDecisionHistory } from './nonnaApi'
import type { DecisionHistory, HistoryEvent, HistoryGroup } from './nonnaApi'

const GROUPS: { value: HistoryGroup | 'all'; label: string }[] = [
  { value: 'all', label: 'Everything' },
  { value: 'reviews', label: 'Reviews' },
  { value: 'gc', label: 'GC exceptions' },
  { value: 'precedence', label: 'Which term controls' },
  { value: 'notes', label: 'Notes' },
  { value: 'contracts', label: 'Uploads and fixes' },
]

const ICONS: Record<HistoryEvent['kind'], string> = {
  uploaded: '↑',
  approved: '✓',
  approved_change: '✓',
  corrected: '✎',
  rejected: '✕',
  gc_exception: '✍',
  gc_exception_withdrawn: '↩',
  precedence_call: '⚖',
  note_added: '✚',
  note_archived: '↓',
  contract_fixed: '✎',
  contract_moved_in: '→',
  contract_moved_out: '←',
  contract_deleted: '✕',
}

// Dates and times in the reader's own time zone (the API sends UTC)
function dayOf(at: string): string {
  return new Date(at).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })
}
function timeOf(at: string): string {
  return new Date(at).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
}

function where(event: HistoryEvent): string | null {
  if (!event.source) return null
  return event.section ? `${event.source.title} §${event.section}` : event.source.title
}

function Event({ event }: { event: HistoryEvent }) {
  return (
    <li className={`history-event history-${event.group}`}>
      <span className={`history-icon history-icon-${event.kind}`} aria-hidden="true">
        {ICONS[event.kind]}
      </span>
      <div className="history-body">
        <p className="history-title">
          {event.title}
          {event.value && <span className="history-value"> · {event.value}</span>}
        </p>
        {event.detail && <p className="history-detail">{event.detail}</p>}
        {event.changes.length > 0 && (
          <ul className="history-changes">
            {event.changes.map((change) => (
              <li key={change.label}>
                {change.label}: <s>{change.before}</s> → <strong>{change.after}</strong>
              </li>
            ))}
          </ul>
        )}
        {event.note && (
          <p className="history-note" data-explain="">
            “{event.note}”
          </p>
        )}
        <p className="history-meta">
          {event.by} · {timeOf(event.at)}
          {where(event) && ` · ${where(event)}`}
        </p>
      </div>
    </li>
  )
}

// One CSV line per event, for an audit file or a spreadsheet
function toCsv(events: HistoryEvent[]): string {
  const cell = (value: string | null | undefined) => `"${(value ?? '').replace(/"/g, '""')}"`
  const header = ['When', 'Who', 'What', 'Value', 'Details', 'Changes', 'Why', 'Contract', 'Section']
  const rows = events.map((e) =>
    [
      new Date(e.at).toLocaleString('en-US'),
      e.by,
      e.title,
      e.value,
      e.detail,
      e.changes.map((c) => `${c.label}: ${c.before} -> ${c.after}`).join('; '),
      e.note,
      e.source?.title,
      e.section,
    ]
      .map(cell)
      .join(','),
  )
  return [header.map(cell).join(','), ...rows].join('\r\n')
}

function downloadCsv(data: DecisionHistory, events: HistoryEvent[]) {
  const blob = new Blob([toCsv(events)], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  const vendor = data.counterparty_name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
  link.href = url
  link.download = `nonna-decisions-${vendor}-${todayISO()}.csv`
  link.click()
  URL.revokeObjectURL(url)
}

// The timeline itself. filters turns on the chips and the CSV download (the Library, not chat).
export function HistoryTimeline({ data, filters = false }: { data: DecisionHistory; filters?: boolean }) {
  const [group, setGroup] = useState<HistoryGroup | 'all'>('all')
  const events = useMemo(
    () => (group === 'all' ? data.events : data.events.filter((e) => e.group === group)),
    [data, group],
  )
  const days = useMemo(() => {
    const byDay: { day: string; events: HistoryEvent[] }[] = []
    for (const event of events) {
      const day = dayOf(event.at)
      const last = byDay[byDay.length - 1]
      if (last && last.day === day) last.events.push(event)
      else byDay.push({ day, events: [event] })
    }
    return byDay
  }, [events])

  return (
    <div className="history">
      {filters && (
        <div className="history-toolbar">
          <div className="tc-options" role="radiogroup" aria-label="Show">
            {GROUPS.filter((g) => g.value === 'all' || data.counts[g.value]).map((g) => (
              <button
                key={g.value}
                type="button"
                role="radio"
                aria-checked={group === g.value}
                className={group === g.value ? 'tc-option tc-option-on' : 'tc-option'}
                onClick={() => setGroup(g.value)}
              >
                {g.label}
                <span className="history-count">
                  {g.value === 'all' ? data.events.length : data.counts[g.value]}
                </span>
              </button>
            ))}
          </div>
          <button
            type="button"
            className="btn btn-sm btn-quiet"
            disabled={events.length === 0}
            onClick={() => downloadCsv(data, events)}
          >
            Download CSV
          </button>
        </div>
      )}

      {days.length === 0 ? (
        <p className="card-empty">Nothing decided yet.</p>
      ) : (
        days.map(({ day, events: dayEvents }) => (
          <section key={day} className="history-day">
            <p className="history-date">{day}</p>
            <ol className="history-list">
              {dayEvents.map((event) => (
                <Event key={event.id} event={event} />
              ))}
            </ol>
          </section>
        ))
      )}
    </div>
  )
}

// The History tab in the Library
export default function DecisionHistoryTab({ counterpartyId, reloadKey }: { counterpartyId: number; reloadKey?: unknown }) {
  const [data, setData] = useState<DecisionHistory | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let current = true
    setError('')
    fetchDecisionHistory(counterpartyId)
      .then((result) => current && setData(result))
      .catch((err: unknown) => current && setError(err instanceof Error ? err.message : "Couldn't load the history."))
    return () => {
      current = false
    }
  }, [counterpartyId, reloadKey])

  if (error) return <p className="intake-error">⚠ {error}</p>
  if (!data || data.counterparty_id !== counterpartyId) return <p className="card-empty">Loading…</p>

  return (
    <div className="history-tab">
      <p className="playbook-intro">
        Everything anyone decided about {data.counterparty_name}: uploads, approvals, corrections, GC exceptions,
        which-term-controls calls, and notes. Nothing here can be edited or deleted, so this is the full record.
      </p>
      <HistoryTimeline data={data} filters />
    </div>
  )
}