// Talking to Nonna's backend. The Vite proxy sends /api/... to FastAPI on port 8000.

export type Role = 'user' | 'nonna'

export type CardType = 'positions' | 'history' | 'contracts' | 'review_queue'

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
    .filter((m) => !m.pending && m.text.trim() !== '')
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