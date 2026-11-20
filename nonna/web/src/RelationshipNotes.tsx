// Relationship notes: what the team knows about a vendor that isn't in any contract.
// "They always fight us on IP." "Business owner is in CMC." "Renegotiating in Q2."
// Notes are never edited or deleted. Archive one when it's out of date, then add a new one.
import { useState } from 'react'
import { formatDate } from './format'
import { addNote, archiveNote } from './nonnaApi'
import type { NoteTopic, RelationshipNote, RelationshipNotes } from './nonnaApi'

const TOPICS: { value: NoteTopic; label: string; placeholder: string }[] = [
  { value: 'negotiation', label: 'How they negotiate', placeholder: 'They always push back on IP ownership. Expect a redline on §9.' },
  { value: 'people', label: 'People', placeholder: 'Business owner is in CMC. Their counsel prefers calls over email.' },
  { value: 'timing', label: 'Timing and plans', placeholder: 'Renegotiating the MSA in Q2. Budget freezes every December.' },
  { value: 'other', label: 'Other', placeholder: 'Anything the next person should know before working with them.' },
]
const MAX_LENGTH = 1000

function byline(note: RelationshipNote): string {
  return `${note.written_by} · ${formatDate(note.written_at.slice(0, 10))}`
}

function NoteItem({ note, onArchived }: { note: RelationshipNote; onArchived?: () => void }) {
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function archive() {
    setBusy(true)
    setError('')
    try {
      await archiveNote(note.id)
      onArchived?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't archive that note.")
      setBusy(false)
    }
  }

  return (
    <li className={note.archived_at ? 'note-item note-archived' : 'note-item'}>
      <span className={`note-topic note-topic-${note.topic}`}>{note.topic_label}</span>
      <p className="note-body" data-explain="">
        {note.body}
      </p>
      <p className="note-meta">
        {byline(note)}
        {note.archived_at && ` · archived by ${note.archived_by} on ${formatDate(note.archived_at.slice(0, 10))}`}
      </p>
      {onArchived && !note.archived_at && (
        <div className="note-actions">
          {confirming ? (
            <>
              <span className="note-confirm">Archive this note? It stays in the history.</span>
              <button type="button" className="lib-fix" disabled={busy} onClick={() => void archive()}>
                {busy ? 'Archiving…' : 'Yes, archive'}
              </button>
              <button type="button" className="lib-fix note-cancel" disabled={busy} onClick={() => setConfirming(false)}>
                Cancel
              </button>
            </>
          ) : (
            <button type="button" className="lib-fix" onClick={() => setConfirming(true)}>
              Archive
            </button>
          )}
        </div>
      )}
      {error && <p className="intake-error">{error}</p>}
    </li>
  )
}

function AddNote({ counterpartyId, onAdded }: { counterpartyId: number; onAdded: () => void }) {
  const [topic, setTopic] = useState<NoteTopic>('negotiation')
  const [body, setBody] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const placeholder = TOPICS.find((t) => t.value === topic)?.placeholder

  async function save() {
    if (!body.trim()) return setError('Write something first.')
    setBusy(true)
    setError('')
    try {
      await addNote(counterpartyId, topic, body.trim())
      setBody('')
      onAdded()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save that note.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="note-add">
      <div className="tc-options" role="radiogroup" aria-label="Topic">
        {TOPICS.map((t) => (
          <button
            key={t.value}
            type="button"
            role="radio"
            aria-checked={topic === t.value}
            className={topic === t.value ? 'tc-option tc-option-on' : 'tc-option'}
            onClick={() => setTopic(t.value)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <textarea
        className="review-note"
        rows={3}
        maxLength={MAX_LENGTH}
        value={body}
        onChange={(e) => {
          setBody(e.target.value)
          setError('')
        }}
        placeholder={placeholder}
        aria-label="Note"
      />
      <p className="note-hint">
        Keep it to what the team needs to work with them. No privileged advice or personal details.
        <span className="note-count">
          {body.length}/{MAX_LENGTH}
        </span>
      </p>
      {error && <p className="intake-error">{error}</p>}
      <div className="intake-actions">
        <button type="button" className="btn btn-sm btn-primary" disabled={busy} onClick={() => void save()}>
          {busy ? 'Saving…' : 'Add note'}
        </button>
      </div>
    </div>
  )
}

// The full Notes tab in the Library
export function NotesTab({ data, onChanged }: { data: RelationshipNotes; onChanged: () => void }) {
  return (
    <div className="notes-tab">
      <p className="playbook-intro">
        What the team knows about {data.counterparty_name} that isn't in any contract. Notes can't be edited:
        archive one when it's out of date and add a new one, so the history stays.
      </p>
      <AddNote counterpartyId={data.counterparty_id} onAdded={onChanged} />

      {data.notes.length === 0 ? (
        <p className="card-empty">No notes yet.</p>
      ) : (
        <ul className="note-list">
          {data.notes.map((note) => (
            <NoteItem key={note.id} note={note} onArchived={onChanged} />
          ))}
        </ul>
      )}

      {data.archived.length > 0 && (
        <details className="lib-wording note-archive">
          <summary>Archived ({data.archived.length})</summary>
          <ul className="note-list">
            {data.archived.map((note) => (
              <NoteItem key={note.id} note={note} />
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

// A peek at the newest notes under the vendor's name, so nobody misses them
export function NotesStrip({ data, onOpen }: { data: RelationshipNotes; onOpen: () => void }) {
  const newest = data.notes.slice(0, 2)
  if (newest.length === 0) {
    return (
      <p className="notes-strip notes-strip-empty">
        📝 No team notes yet.{' '}
        <button type="button" className="lib-fix" onClick={onOpen}>
          Add one
        </button>
      </p>
    )
  }
  return (
    <div className="notes-strip">
      <ul>
        {newest.map((note) => (
          <li key={note.id}>
            <span className={`note-topic note-topic-${note.topic}`}>{note.topic_label}</span>
            <span className="notes-strip-body">{note.body}</span>
          </li>
        ))}
      </ul>
      <button type="button" className="lib-fix" onClick={onOpen}>
        {data.notes.length > newest.length ? `See all ${data.notes.length} notes` : 'See notes'}
      </button>
    </div>
  )
}

// Read-only list for a chat card
export function NotesCard({ data }: { data: RelationshipNotes }) {
  if (data.notes.length === 0) {
    return <p className="card-empty">No team notes for {data.counterparty_name} yet. Add them in the Library.</p>
  }
  return (
    <ul className="note-list">
      {data.notes.map((note) => (
        <NoteItem key={note.id} note={note} />
      ))}
    </ul>
  )
}