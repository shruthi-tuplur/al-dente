import { useEffect, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import { askNonna } from './nonnaApi'
import type { Message } from './nonnaApi'
import './App.css'

export default function App() {
  const [messages, setMessages] = useState<Message[]>([])
  const [draft, setDraft] = useState('')
  const [waiting, setWaiting] = useState(false)
  const endRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  // Scroll to the newest message
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Grow the message box as you type (up to a limit), and shrink it after sending
  useEffect(() => {
    const el = inputRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`
  }, [draft])

  async function send() {
    const text = draft.trim()
    if (!text || waiting) return

    const userMessage: Message = { id: crypto.randomUUID(), role: 'user', text }
    const pendingId = crypto.randomUUID()
    const conversation = [...messages, userMessage]

    setMessages([...conversation, { id: pendingId, role: 'nonna', text: '', pending: true }])
    setDraft('')
    setWaiting(true)

    try {
      const reply = await askNonna(conversation)
      setMessages((prev) =>
        prev.map((m) =>
          m.id === pendingId
            ? { ...m, text: reply.text, status: reply.status, cards: reply.cards, pending: false }
            : m,
        ),
      )
    } catch (error) {
      const message = error instanceof Error ? error.message : "Nonna couldn't answer that."
      setMessages((prev) =>
        prev.map((m) => (m.id === pendingId ? { ...m, text: message, pending: false } : m)),
      )
    } finally {
      setWaiting(false)
      inputRef.current?.focus()
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void send()
  }

  // Enter sends, Shift + Enter makes a new line
  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      void send()
    }
  }

  return (
    <div className="app">
      <header className="header">
        <h1 className="logo">nonna</h1>
      </header>

      <main className="chat" aria-live="polite">
        <div className="thread">
          {messages.length === 0 && (
            <p className="empty">Pull up a chair. Ask nonna anything about your contracts.</p>
          )}

          {messages.map((m) =>
            m.role === 'user' ? (
              <div key={m.id} className="row row-user">
                <div className="bubble">{m.text}</div>
              </div>
            ) : (
              <div key={m.id} className="row row-nonna">
                {m.pending ? (
                  <p className="thinking">Thinking…</p>
                ) : (
                  <>
                    <p className="nonna-text">{m.text}</p>
                    {m.status && <p className="status">{m.status}</p>}
                  </>
                )}
              </div>
            ),
          )}

          <div ref={endRef} />
        </div>
      </main>

      <div className="composer-wrap">
        <form className="composer" onSubmit={handleSubmit}>
          <textarea
            ref={inputRef}
            className="composer-input"
            rows={1}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask nonna about a contract"
            aria-label="Message nonna"
          />
          <button type="submit" className="send" aria-label="Send">
            <svg width="22" height="12" viewBox="0 0 22 12" fill="none" aria-hidden="true">
              <path
                d="M1 6h19M15 1l5 5-5 5"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        </form>
      </div>
    </div>
  )
}