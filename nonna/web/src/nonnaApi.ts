// Talking to Nonna's backend. The Vite proxy sends /api/... to FastAPI on port 8000.
import type { ClauseType } from './format'

// ---------------------------------------------------------------------------
// Who's using the app
// ---------------------------------------------------------------------------

// No login yet: pick a demo user in the header (remembered in this browser).
// The server decides what each user can do and checks it on every change.
// This list only fills the switcher and hides buttons a read-only user can't use.
export const DEMO_USERS = [
  { name: 'demo.attorney', label: 'Attorney', role: 'attorney' },
  { name: 'demo.business', label: 'Business (read-only)', role: 'business' },
] as const

function storedUser(): string {
  try {
    const name = localStorage.getItem('nonna.user')
    if (DEMO_USERS.some((u) => u.name === name)) return name as string
  } catch {
    // Storage blocked: fall back to the default
  }
  return 'demo.attorney'
}

// Every action is recorded under this name
export const CURRENT_USER = storedUser()
// Attorneys can change things. Business users are read-only.
export const CAN_EDIT = DEMO_USERS.find((u) => u.name === CURRENT_USER)?.role === 'attorney'

// Switch demo user. The page reloads so nothing from the last user is left on screen.
export function switchUser(name: string) {
  try {
    localStorage.setItem('nonna.user', name)
  } catch {
    return // can't remember the choice, so don't pretend it changed
  }
  window.location.reload()
}

// Every request says who's asking, so the server can check what they're allowed to do
function apiFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers)
  headers.set('X-Nonna-User', CURRENT_USER)
  return fetch(input, { ...init, headers })
}

export type Role = 'user' | 'nonna'

export type CardType =
  | 'profile'
  | 'clause'
  | 'section'
  | 'positions'
  | 'history'
  | 'contracts'
  | 'review_queue'
  | 'vendors'
  | 'deadlines'
  | 'amended'
  | 'playbook'
  | 'draft'
  | 'precedence'
  | 'notes'
  | 'decisions'

export interface Card {
  type: CardType
  title: string
  data: unknown
}

export type ContractType = 'NDA' | 'MSA' | 'SOW' | 'amendment' | 'change_order'

export interface CounterpartyMatch {
  id: number
  name: string
  contract_count: number
}

export interface ProposedParty {
  legal_name: string
  defined_as: string | null
  quote: string | null
  is_our_company: boolean
  matches: CounterpartyMatch[]
}

export interface ParentOption {
  id: number
  title: string
  contract_type: ContractType
  effective_date: string
}

export interface IntakeProposal {
  file_hash: string
  filename: string
  page_count: number | null
  word_count: number
  redaction_count: number
  already_uploaded_contract_id: number | null
  title: string | null
  contract_type: ContractType | null
  effective_date: string | null
  parties: ProposedParty[]
  quotes: Record<string, string>
  unverified: string[]
  excerpt: string
  parent_options: ParentOption[]
  suggested_parent_id: number | null
  parent_quote: string | null
}

export interface Message {
  id: string
  role: Role
  text: string
  status?: string
  cards?: Card[]
  attachment?: string
  intake?: IntakeProposal
  pending?: boolean
}

export interface NonnaReply {
  text: string
  status?: string
  cards: Card[]
}

interface ChatResponse {
  reply: string
  status: string | null
  cards: Card[]
}
export type Corrections = Record<string, string | boolean>

// Turn a failed response into a readable message
async function errorDetail(response: Response, fallback: string): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown }
    if (typeof body.detail === 'string') return body.detail
    // Validation errors come back as a list, like [{ msg: "Value error, Add a short note..." }]
    if (Array.isArray(body.detail) && typeof body.detail[0]?.msg === 'string') {
      const first = body.detail[0] as { msg: string; loc?: unknown[] }
      const field = Array.isArray(first.loc) ? ` (${first.loc.join(' → ')})` : ''
      return first.msg.replace(/^Value error, /, '') + field
    }
    if (body.detail !== undefined) return `${fallback} ${JSON.stringify(body.detail)}`
  } catch {
    // The response wasn't JSON, use the fallback
  }
  return fallback
}

// Send the whole conversation (Nonna doesn't remember between requests on her own)
export async function askNonna(conversation: Message[]): Promise<NonnaReply> {
  const messages = conversation
    .filter((m) => !m.pending && !m.attachment && !m.intake && m.text.trim() !== '')
    .map((m) => ({ role: m.role === 'nonna' ? 'assistant' : 'user', content: m.text }))

  const response = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages }),
  })

  if (!response.ok) {
    throw new Error(await errorDetail(response, `Nonna couldn't answer (error ${response.status}).`))
  }

  const body = (await response.json()) as ChatResponse
  return { text: body.reply, status: body.status ?? undefined, cards: body.cards }
}

// Upload a contract. Nonna reads it and proposes its details (nothing is saved yet).
export async function uploadContract(file: File): Promise<IntakeProposal> {
  const form = new FormData()
  form.append('file', file)

  const response = await fetch('/api/contracts/intake', { method: 'POST', body: form })

  if (!response.ok) {
    throw new Error(await errorDetail(response, `Nonna couldn't read that file (error ${response.status}).`))
  }

  return (await response.json()) as IntakeProposal
}



export interface SaveContractRequest {
  file_hash: string
  title: string
  contract_type: ContractType
  effective_date: string
  counterparty_legal_name: string
  counterparty_id: number | null
  parent_contract_id: number | null
  uploaded_by: string
}

export interface SavedContract {
  contract_id: number
  counterparty_id: number
  counterparty_name: string
  created_counterparty: boolean
  created_entity: boolean
}

// Save a contract after the attorney confirms its details
export async function saveContract(request: SaveContractRequest): Promise<SavedContract> {
  const response = await fetch('/api/contracts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })

  if (!response.ok) {
    throw new Error(await errorDetail(response, `Nonna couldn't save that contract (error ${response.status}).`))
  }

  return (await response.json()) as SavedContract
}


export interface ExtractedTerm {
  term_key: string
  value: string | boolean | null
  unit: string | null
}

export interface ExtractedClause {
  clause_type: ClauseType
  status: 'found' | 'redacted' | 'inherited' | 'unchanged' | 'not_found'
  clause_id: number | null
  section_number: string | null
  heading: string | null
  snippet: string | null
  method: string | null
  terms: ExtractedTerm[]
  note: string | null
}

export interface ExtractionResult {
  contract_id: number
  clauses: ExtractedClause[]
}

// Pull the key terms out of a saved contract (saved as pending review)
export async function extractContract(contractId: number): Promise<ExtractionResult> {
  const response = await fetch(`/api/contracts/${contractId}/extract`, { method: 'POST' })

  if (!response.ok) {
    throw new Error(await errorDetail(response, `Nonna couldn't pull the key terms (error ${response.status}).`))
  }

  return (await response.json()) as ExtractionResult

}



export type ReviewAction = 'approved' | 'rejected' | 'approved_change'

export interface ReviewOutcome {
  baseline: 'created' | 'moved' | 'unchanged' | 'none'
  message: string
}

// Thrown when a clause differs from the agreed baseline and needs a note to approve
export class BaselineConflictError extends Error {}

// The term is off Aurelia's playbook, so approving it needs the GC's sign-off first
export class GcSignOffError extends Error {}

// The GC's sign-off, as the attorney records it
export interface GcSignOff {
  approved_by: string // the GC's name
  approved_on: string // YYYY-MM-DD
  note: string // why the GC said yes
}

// Record an attorney's decision about one extracted clause
export async function reviewClause(
  clauseId: number,
  action: ReviewAction,
  note?: string,
  correction?: { values: Corrections; asChange?: boolean },
  gcSignOff?: GcSignOff,
): Promise<ReviewOutcome> {
  const response = await fetch(`/api/clauses/${clauseId}/reviews`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      action,
      reviewer: CURRENT_USER,
      note: note ?? null,
      corrections: correction?.values ?? null,
      as_change: correction?.asChange ?? false,
      gc_signoff: gcSignOff ?? null,
    }),
  })

  if (response.status === 409) {
    throw new BaselineConflictError(await errorDetail(response, "This doesn't match the agreed baseline."))
  }
  if (response.status === 428) {
    throw new GcSignOffError(await errorDetail(response, "This term is off the playbook, so it needs the GC's sign-off."))
  }
  if (!response.ok) {
    throw new Error(await errorDetail(response, `Nonna couldn't save that decision (error ${response.status}).`))
  }

  return (await response.json()) as ReviewOutcome
}

// ---------------------------------------------------------------------------
// Review dashboard
// ---------------------------------------------------------------------------

export interface QueueSource {
  id: number
  contract_type: string
  title: string
  effective_date: string
}

export interface QueueItem {
  counterparty_id: number
  counterparty_name: string
  source: QueueSource
  clause: LibraryClause
  agreed: { applies_to: string[]; source: QueueSource; clause: LibraryClause } | null
  matches_agreed: boolean | null
  playbook: PlaybookAssessment | null
}

// Every extracted clause still waiting for an attorney, oldest upload first
export async function fetchReviewQueue(): Promise<QueueItem[]> {
  const response = await fetch('/api/review-queue')
  if (!response.ok) throw new Error(await errorDetail(response, "Nonna couldn't load the review queue."))
  return (await response.json()) as QueueItem[]
}

// ---------------------------------------------------------------------------
// Library view
// ---------------------------------------------------------------------------

export interface CounterpartySummary {
  id: number
  name: string
  contract_count: number
}

export interface LibraryClause {
  id: number
  clause_type: string
  section_number: string | null
  heading: string | null
  full_text: string | null
  presence: string
  extraction_method: string
  review_status: string
  terms: { term_key: string; value: string | boolean | null; unit: string | null }[]
}

export interface LibraryContract {
  id: number
  contract_type: ContractType
  title: string
  effective_date: string
  expiration_date: string | null
  status: string
  signed_by_entity: string
  parent_contract_id: number | null
  amends_contract_id: number | null
}

export interface CounterpartyLibrary {
  counterparty: {
    id: number
    name: string
    entities: { id: number; legal_name: string; jurisdiction: string | null }[]
    contracts: LibraryContract[]
  }
  contracts: { contract: LibraryContract; clauses: LibraryClause[] }[]
  agreed_clause_ids: number[]
  superseded_clause_ids: number[]
  sections: LibrarySection[]
  category_order: string[]
  playbook: Record<string, PlaybookAssessment> // by clause id
}

export interface LibrarySection {
  id: number
  contract_id: number
  category: string
  section_number: string | null
  heading: string | null
  full_text: string
}

export async function fetchCounterparties(): Promise<CounterpartySummary[]> {
  const response = await fetch('/api/counterparties')
  if (!response.ok) throw new Error(await errorDetail(response, "Nonna couldn't load your vendors."))
  return (await response.json()) as CounterpartySummary[]
}

// ---------------------------------------------------------------------------
// Fixing upload mistakes
// ---------------------------------------------------------------------------

export interface ContractFix {
  title: string
  contract_type: ContractType
  effective_date: string // YYYY-MM-DD
  counterparty_id: number
  linked_contract_id: number | null // the MSA an SOW falls under, or what an amendment amends
  note: string
}

export interface FixOutcome {
  contract_id: number | null
  counterparty_id: number
  message: string
  reread: boolean
}

export async function fixContract(contractId: number, fix: ContractFix): Promise<FixOutcome> {
  const response = await fetch(`/api/contracts/${contractId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...fix, changed_by: CURRENT_USER }),
  })
  if (!response.ok) throw new Error(await errorDetail(response, "Nonna couldn't save that fix."))
  return (await response.json()) as FixOutcome
}

export async function deleteContract(contractId: number, note: string): Promise<FixOutcome> {
  const response = await fetch(`/api/contracts/${contractId}/delete`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ note, changed_by: CURRENT_USER }),
  })
  if (!response.ok) throw new Error(await errorDetail(response, "Nonna couldn't delete that upload."))
  return (await response.json()) as FixOutcome
}

export async function fetchLibrary(counterpartyId: number): Promise<CounterpartyLibrary> {
  const response = await fetch(`/api/counterparties/${counterpartyId}/library`)
  if (!response.ok) throw new Error(await errorDetail(response, "Nonna couldn't load that vendor."))
  return (await response.json()) as CounterpartyLibrary
}


export interface ContractText {
  id: number
  counterparty_id: number
  title: string
  contract_type: ContractType
  effective_date: string
  full_text: string | null
  has_file: boolean
}

export async function fetchContractText(contractId: number): Promise<ContractText> {
  const response = await fetch(`/api/contracts/${contractId}/text`)
  if (!response.ok) throw new Error(await errorDetail(response, "Nonna couldn't load that contract."))
  return (await response.json()) as ContractText
}


// ---------------------------------------------------------------------------
// The "as amended" view
// ---------------------------------------------------------------------------

export interface ContractRef {
  id: number
  contract_type: string
  title: string
  effective_date: string
}

export interface AmendedSection {
  number: string
  heading: string
  text: string
  status: 'original' | 'replaced' | 'added' | 'deleted'
  changed_by: ContractRef | null
  original_text: string | null
}

export interface AmendedContract {
  contract: ContractRef
  amendments: ContractRef[]
  sections: AmendedSection[]
  unresolved: { amendment: ContractRef; section: string | null; wording: string }[]
  changed_count: number
  note?: string
}

// A contract as it reads today, with its amendments applied
export async function fetchAsAmended(contractId: number): Promise<AmendedContract> {
  const response = await fetch(`/api/contracts/${contractId}/as-amended`)
  if (!response.ok) throw new Error(await errorDetail(response, "Nonna couldn't apply the amendments."))
  return (await response.json()) as AmendedContract
}


// ---------------------------------------------------------------------------
// Aurelia's playbook
// ---------------------------------------------------------------------------

export type Tier = 'standard' | 'fallback' | 'outside' | 'not_comparable'

export interface PlaybookAssessment {
  tier: Tier
  reason: string
  value: string // the term as Nonna reads it, like "$500,000"
  needs_sign_off: boolean // off playbook and still waiting for review
  guidance: string | null // the playbook's advice for this term
  exception: PlaybookException | null // the GC signed off on this exact term
}

// The GC's sign-off on one off-playbook term. A permanent record, only ever withdrawn.
export interface PlaybookException {
  id: number
  approved_value: string
  approved_by: string
  approved_on: string
  note: string
  recorded_by: string
  recorded_at: string
}

export interface PlaybookRule {
  clause_type: string
  label: string
  standard: Record<string, unknown>
  fallback: Record<string, unknown>
  standard_text: string
  fallback_text: string
  guidance: string
  note: string | null
  set_by: string
  set_at: string
  version: number
}

export interface PlaybookCell extends PlaybookAssessment {
  source: ContractRef
  clause_id: number
}

export interface PlaybookCheck {
  rules: PlaybookRule[]
  rows: { counterparty_id: number; counterparty_name: string; cells: Record<string, PlaybookCell | null> }[]
  outside_count: number // off playbook with no GC exception
  exception_count: number // off playbook, but the GC signed off
}

export async function fetchPlaybook(): Promise<PlaybookCheck> {
  const response = await fetch('/api/playbook')
  if (!response.ok) throw new Error(await errorDetail(response, "Nonna couldn't load the playbook."))
  return (await response.json()) as PlaybookCheck
}

// Save a new version of one rule. A note saying why is required.
export async function updatePlaybookRule(
  clauseType: string,
  change: {
    standard: Record<string, string | boolean>
    fallback: Record<string, string | boolean>
    guidance: string
    note: string
    set_by: string
  },
): Promise<PlaybookRule> {
  const response = await fetch(`/api/playbook/${clauseType}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(change),
  })
  if (!response.ok) throw new Error(await errorDetail(response, "Nonna couldn't save that rule."))
  return (await response.json()) as PlaybookRule
}

// Record the GC's sign-off on an off-playbook term in a signed contract
export async function recordPlaybookException(clauseId: number, signOff: GcSignOff): Promise<PlaybookException> {
  const response = await fetch(`/api/clauses/${clauseId}/playbook-exception`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...signOff, recorded_by: CURRENT_USER }),
  })
  if (!response.ok) throw new Error(await errorDetail(response, "Nonna couldn't save that exception."))
  return (await response.json()) as PlaybookException
}

// Withdraw a GC exception. It stays in the history, and the term is flagged again.
export async function withdrawPlaybookException(exceptionId: number, note: string): Promise<void> {
  const response = await fetch(`/api/playbook-exceptions/${exceptionId}/withdraw`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ withdrawn_by: CURRENT_USER, note }),
  })
  if (!response.ok) throw new Error(await errorDetail(response, "Nonna couldn't withdraw that exception."))
}


// ---------------------------------------------------------------------------
// Decision history: everything anyone decided about a vendor, newest first
// ---------------------------------------------------------------------------

export type HistoryGroup = 'contracts' | 'reviews' | 'gc' | 'precedence' | 'notes'

export interface HistoryEvent {
  id: string
  kind:
    | 'uploaded'
    | 'approved'
    | 'approved_change'
    | 'corrected'
    | 'rejected'
    | 'gc_exception'
    | 'gc_exception_withdrawn'
    | 'precedence_call'
    | 'note_added'
    | 'note_archived'
  group: HistoryGroup
  at: string
  by: string
  title: string
  clause_type: string | null
  value: string | null
  detail: string | null
  changes: { label: string; before: string; after: string }[]
  note: string | null
  source: ContractRef | null
  section: string | null
}

export interface DecisionHistory {
  counterparty_id: number
  counterparty_name: string
  events: HistoryEvent[] // newest first
  counts: Partial<Record<HistoryGroup, number>>
}

export async function fetchDecisionHistory(counterpartyId: number): Promise<DecisionHistory> {
  const response = await fetch(`/api/counterparties/${counterpartyId}/decisions`)
  if (!response.ok) throw new Error(await errorDetail(response, "Nonna couldn't load the decision history."))
  return (await response.json()) as DecisionHistory
}

// ---------------------------------------------------------------------------
// Relationship notes: what the team knows that isn't in any contract
// ---------------------------------------------------------------------------

export type NoteTopic = 'negotiation' | 'people' | 'timing' | 'other'

export interface RelationshipNote {
  id: number
  topic: NoteTopic
  topic_label: string
  body: string
  written_by: string
  written_at: string
  archived_at: string | null
  archived_by: string | null
}

export interface RelationshipNotes {
  counterparty_id: number
  counterparty_name: string
  notes: RelationshipNote[] // active, newest first
  archived: RelationshipNote[]
}

export async function fetchNotes(counterpartyId: number): Promise<RelationshipNotes> {
  const response = await fetch(`/api/counterparties/${counterpartyId}/notes`)
  if (!response.ok) throw new Error(await errorDetail(response, "Nonna couldn't load the team's notes."))
  return (await response.json()) as RelationshipNotes
}

export async function addNote(counterpartyId: number, topic: NoteTopic, body: string): Promise<RelationshipNote> {
  const response = await fetch(`/api/counterparties/${counterpartyId}/notes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ topic, body, written_by: CURRENT_USER }),
  })
  if (!response.ok) throw new Error(await errorDetail(response, "Nonna couldn't save that note."))
  return (await response.json()) as RelationshipNote
}

// Archive a note. It stays in the history, it just stops showing as current.
export async function archiveNote(noteId: number): Promise<RelationshipNote> {
  const response = await fetch(`/api/notes/${noteId}/archive`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ archived_by: CURRENT_USER }),
  })
  if (!response.ok) throw new Error(await errorDetail(response, "Nonna couldn't archive that note."))
  return (await response.json()) as RelationshipNote
}


// ---------------------------------------------------------------------------
// Which term controls (an SOW and its MSA disagree)
// ---------------------------------------------------------------------------

export interface TermSide {
  clause_id: number
  value: string
  section_number: string | null
  source: ContractRef
  amended_by: ContractRef | null // an amendment changed the MSA's term
  review_status: string
}

export interface PrecedenceRule {
  section_number: string
  heading: string
  text: string // word for word, as amended
  source: ContractRef
  amended: boolean
}

export interface SupersedeCheck {
  msa_section: string | null
  names_section: boolean
  says_supersedes: boolean
  quote: string | null // the SOW's own sentence
  quote_source: string | null // like "SOW No. 1 §5.3"
}

export type Controls = 'msa' | 'sow'

export interface ControlCall {
  id: number
  controls: Controls
  note: string
  decided_by: string
  decided_at: string
}

export interface TermConflict {
  clause_type: string
  label: string
  msa: TermSide
  sow: TermSide
  rule: PrecedenceRule | null
  check: SupersedeCheck
  call: ControlCall | null
}

export interface PrecedenceReport {
  counterparty_id: number
  counterparty_name: string
  conflicts: TermConflict[]
  open_count: number // no attorney call yet
}

export async function fetchPrecedence(counterpartyId: number): Promise<PrecedenceReport> {
  const response = await fetch(`/api/counterparties/${counterpartyId}/precedence`)
  if (!response.ok) throw new Error(await errorDetail(response, "Nonna couldn't line up the SOWs and the MSA."))
  return (await response.json()) as PrecedenceReport
}

// The attorney's call on which term controls. Append-only: a new call replaces the old one in effect.
export async function recordPrecedenceCall(sowClauseId: number, controls: Controls, note: string): Promise<ControlCall> {
  const response = await fetch(`/api/clauses/${sowClauseId}/precedence-call`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ controls, note, decided_by: CURRENT_USER }),
  })
  if (!response.ok) throw new Error(await errorDetail(response, "Nonna couldn't save that call."))
  return (await response.json()) as ControlCall
}

// ---------------------------------------------------------------------------
// Drafting from history
// ---------------------------------------------------------------------------

export interface DraftSection {
  kind: 'title' | 'preamble' | 'article' | 'signatures'
  number: string
  heading: string
  text: string // one paragraph per line; table rows use " | " between cells
  label: 'verbatim' | 'adapted' | 'new'
  source: string
  original: string | null
  note: string | null
  checks: string[]
}

export interface Draft {
  counterparty_id: number
  counterparty_name: string
  contract_type: string
  number: number
  brief: string
  template: string
  sections: DraftSection[]
  blanks: number
}

// Start a new SOW from this vendor's last one and a short brief. Nothing is saved.
export async function makeDraft(counterpartyId: number, brief: string): Promise<Draft> {
  const response = await fetch(`/api/counterparties/${counterpartyId}/drafts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ brief, contract_type: 'SOW' }),
  })
  if (!response.ok) throw new Error(await errorDetail(response, "Nonna couldn't make that draft."))
  return (await response.json()) as Draft
}

// Download the reviewed draft (with any edits) as a Word file
export async function downloadDraft(draft: Draft): Promise<void> {
  const response = await fetch('/api/drafts/docx', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(draft),
  })
  if (!response.ok) throw new Error(await errorDetail(response, "Nonna couldn't make the Word file."))
  const name =
    response.headers.get('Content-Disposition')?.match(/filename="([^"]+)"/)?.[1] ??
    `${draft.counterparty_name} SOW No. ${draft.number} draft.docx`
  const url = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = url
  link.download = name
  link.click()
  URL.revokeObjectURL(url)
}


// ---------------------------------------------------------------------------
// Google Calendar (optional)
// ---------------------------------------------------------------------------

export interface CalendarStatus {
  configured: boolean // the Google client ID and secret are in .env
  connected: boolean // someone has signed in with Google
  calendar_name: string
}

export interface CalendarSyncResult {
  calendar_name: string
  created: number
  updated: number
  removed: number
  unchanged: number
  message: string
}

// Opened in a popup, so the chat stays put while you sign in with Google
export const GOOGLE_CALENDAR_CONNECT_URL = '/api/google-calendar/connect'

export async function fetchCalendarStatus(): Promise<CalendarStatus> {
  const response = await fetch('/api/google-calendar/status')
  if (!response.ok) throw new Error(await errorDetail(response, "Couldn't check Google Calendar."))
  return (await response.json()) as CalendarStatus
}

export async function syncGoogleCalendar(): Promise<CalendarSyncResult> {
  const response = await fetch('/api/google-calendar/sync', { method: 'POST' })
  if (!response.ok) throw new Error(await errorDetail(response, "Couldn't sync Google Calendar."))
  return (await response.json()) as CalendarSyncResult
}

export async function disconnectGoogleCalendar(): Promise<CalendarStatus> {
  const response = await fetch('/api/google-calendar/disconnect', { method: 'POST' })
  if (!response.ok) throw new Error(await errorDetail(response, "Couldn't disconnect Google Calendar."))
  return (await response.json()) as CalendarStatus
}



// ---------------------------------------------------------------------------
// Vendor one-pager
// ---------------------------------------------------------------------------

export interface OnePagerDeadline {
  source: { id: number }
  status: string
  notice_deadline: string | null
  term_end: string | null
  action_date: string | null
  summary: string
}

// One vendor's deadlines, worked out in code, for the one-pager's "next date to watch"
export async function fetchVendorDeadlines(counterpartyId: number): Promise<{ rows: OnePagerDeadline[] }> {
  const response = await fetch(`/api/deadlines?counterparty_id=${counterpartyId}`)
  if (!response.ok) throw new Error(await errorDetail(response, "Couldn't load deadlines."))
  return (await response.json()) as { rows: OnePagerDeadline[] }
}



// ---------------------------------------------------------------------------
// Explain a highlighted phrase
// ---------------------------------------------------------------------------

export interface Explanation {
  phrase: string
  explanation: string // plain English, written by Claude
  definitions: { term: string; section: string | null; text: string }[] // word for word from the contract
}

export async function explainPhrase(phrase: string, context: string, contractId: number | null): Promise<Explanation> {
  const response = await fetch('/api/explain', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ phrase, context, contract_id: contractId }),
  })
  if (!response.ok) throw new Error(await errorDetail(response, "Nonna couldn't explain that."))
  return (await response.json()) as Explanation
}