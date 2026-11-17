// Talking to Nonna's backend. The Vite proxy sends /api/... to FastAPI on port 8000.

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


// No login yet, so every action is recorded under this name
export const CURRENT_USER = 'demo.attorney'

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
  clause_type: 'liability_cap' | 'payment_terms' | 'governing_law' | 'indemnification' | 'term_renewal'
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

// Record an attorney's decision about one extracted clause
export async function reviewClause(
  clauseId: number,
  action: ReviewAction,
  note?: string,
  correction?: { values: Corrections; asChange?: boolean },
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
    }),
  })

  if (response.status === 409) {
    throw new BaselineConflictError(await errorDetail(response, "This doesn't match the agreed baseline."))
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

export async function fetchLibrary(counterpartyId: number): Promise<CounterpartyLibrary> {
  const response = await fetch(`/api/counterparties/${counterpartyId}/library`)
  if (!response.ok) throw new Error(await errorDetail(response, "Nonna couldn't load that vendor."))
  return (await response.json()) as CounterpartyLibrary
}


export interface ContractText {
  id: number
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
}

export interface PlaybookCheck {
  rules: PlaybookRule[]
  rows: { counterparty_id: number; counterparty_name: string; cells: Record<string, PlaybookCell | null> }[]
  outside_count: number
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