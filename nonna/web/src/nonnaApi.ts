// Talking to Nonna's backend. The Vite proxy sends /api/... to FastAPI on port 8000.

export type Role = 'user' | 'nonna'

export type CardType = 'positions' | 'history' | 'contracts' | 'review_queue'

export interface Card {
  type: CardType
  title: string
  data: unknown
}

export interface Message {
  id: string
  role: Role
  text: string
  status?: string
  cards?: Card[]
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
    let detail = `Nonna couldn't answer (error ${response.status}).`
    try {
      const body = (await response.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      // The response wasn't JSON, keep the generic message
    }
    throw new Error(detail)
  }

  const body = (await response.json()) as ChatResponse
  return { text: body.reply, status: body.status ?? undefined, cards: body.cards }
}
