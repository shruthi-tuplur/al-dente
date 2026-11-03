// Talking to Nonna's backend. The Vite proxy sends /api/... to FastAPI on port 8000.

export type Role = 'user' | 'nonna'

export type CardType = 'profile' | 'positions' | 'history' | 'contracts' | 'review_queue'

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

// Turn a failed response into a readable message
async function errorDetail(response: Response, fallback: string): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown }
    if (typeof body.detail === 'string') return body.detail
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
  clause_type: 'liability_cap' | 'payment_terms' | 'governing_law' | 'indemnification'
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
): Promise<ReviewOutcome> {
  const response = await fetch(`/api/clauses/${clauseId}/reviews`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, reviewer: CURRENT_USER, note: note ?? null }),
  })

  if (response.status === 409) {
    throw new BaselineConflictError(await errorDetail(response, "This doesn't match the agreed baseline."))
  }
  if (!response.ok) {
    throw new Error(await errorDetail(response, `Nonna couldn't save that decision (error ${response.status}).`))
  }

  return (await response.json()) as ReviewOutcome
}