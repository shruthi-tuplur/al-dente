import { useEffect, useRef, useState } from 'react'
import type { ChangeEvent, FormEvent, KeyboardEvent } from 'react'
import CardView from './CardView'
import IntakeCard from './IntakeCard'
import RichText from './RichText'
import { askNonna, uploadContract } from './nonnaApi'
import type { Message } from './nonnaApi'
import './App.css'

export default function App() {
  const [messages, setMessages] = useState<Message[]>([])
  const [draft, setDraft] = useState('')
  const [waiting, setWaiting] = useState(false)
  const endRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)

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

  // Replace Nonna's "thinking" placeholder with her real reply
  function finish(pendingId: string, update: Partial<Message>) {
    setMessages((prev) =>
      prev.map((m) => (m.id === pendingId ? { ...m, ...update, pending: false } : m)),
    )
  }

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
      finish(pendingId, { text: reply.text, status: reply.status, cards: reply.cards })
    } catch (error) {
      finish(pendingId, {
        text: error instanceof Error ? error.message : "Nonna couldn't answer that.",
      })
    } finally {
      setWaiting(false)
      inputRef.current?.focus()
    }
  }

  async function handleFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = '' // so the same file can be picked again later
    if (!file || waiting) return

    const pendingId = crypto.randomUUID()
    setMessages((prev) => [
      ...prev,
      { id: crypto.randomUUID(), role: 'user', text: `Uploaded ${file.name}`, attachment: file.name },
      { id: pendingId, role: 'nonna', text: '', pending: true },
    ])
    setWaiting(true)

    try {
      const proposal = await uploadContract(file)
      finish(pendingId, { text: "I read it. Here's what I found:", intake: proposal })
    } catch (error) {
      finish(pendingId, {
        text: error instanceof Error ? error.message : "Nonna couldn't read that file.",
      })
    } finally {
      setWaiting(false)
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
                {m.attachment ? (
                  <div className="bubble file-bubble">
                    <PaperclipIcon />
                    {m.attachment}
                  </div>
                ) : (
                  <div className="bubble">{m.text}</div>
                )}
              </div>
            ) : (
              <div key={m.id} className="row row-nonna">
                {m.pending ? (
                  <p className="thinking">Thinking…</p>
                ) : (
                  <>
                    <div className="nonna-text">
  <RichText text={m.text} />
</div>
                    {m.status && <p className="status">{m.status}</p>}
                    {m.cards?.map((card, i) => <CardView key={i} card={card} />)}
                    {m.intake && <IntakeCard proposal={m.intake} />}
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
          <input
            ref={fileRef}
            type="file"
            accept=".pdf,.docx"
            onChange={handleFile}
            hidden
          />
          <button
            type="button"
            className="attach"
            aria-label="Upload a contract"
            title="Upload a contract (PDF or Word)"
            onClick={() => fileRef.current?.click()}
          >
            <PaperclipIcon />
          </button>
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

function PaperclipIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M21 11.5l-8.6 8.6a5.5 5.5 0 01-7.8-7.8l8.6-8.6a3.7 3.7 0 015.2 5.2l-8.6 8.6a1.8 1.8 0 01-2.6-2.6l7.9-7.9"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}