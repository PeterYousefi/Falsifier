/**
 * src/screens/ChatPanel.tsx
 * Chat panel in newspaper style.
 * Answers in serif prose on a tinted panel.
 * Monospace artifact-source chips beneath each answer.
 * Suggested prompts as buttons. Model may say "can't distinguish" — correct answer.
 */
import React, { useState, useRef, useEffect } from 'react'
import { useStore } from '../store'
import { dataSource } from '../data/DataSource'
import type { ChatMessage } from '../data/types'

const SUGGESTED_PROMPTS = [
  'What would settle it?',
  'Refit at half the period',
  'Why was this classified as a candidate?',
  'What does the stellar density test show?',
  'Could the data distinguish this from an eclipsing binary?',
]

// ── Source chip ────────────────────────────────────────────────────────────
function SourceChip({ text, onHighlight }: { text: string; onHighlight: (text: string) => void }) {
  const [active, setActive] = useState(false)
  const handleClick = () => {
    setActive(true)
    onHighlight(text)
    setTimeout(() => setActive(false), 1500)
  }
  const label = text.replace(/^\[source:\s*/, '').replace(/\]$/, '')
  return (
    <button
      className={`source-chip${active ? ' highlighted' : ''}`}
      onClick={handleClick}
      title={`Source: ${text}`}
      aria-label={`Source chip: ${label}`}
    >
      {label}
    </button>
  )
}

// ── Message bubble ─────────────────────────────────────────────────────────
function MessageBubble({ msg }: { msg: ChatMessage }) {
  const { setHighlightedPanel } = useStore()

  const handleSourceHighlight = (sourceText: string) => {
    const lower = sourceText.toLowerCase()
    if (lower.includes('vet')) setHighlightedPanel('vet')
    else if (lower.includes('planet') || lower.includes('search')) setHighlightedPanel('search')
    else if (lower.includes('classify')) setHighlightedPanel('classify')
    else if (lower.includes('ingest')) setHighlightedPanel('ingest')
  }

  const isOffline = msg.offline_mode === true

  return (
    <div className={`chat-bubble ${msg.role}${isOffline ? ' offline' : ''}`}>
      {isOffline && (
        <div className="offline-badge">⚠ offline mode — no API key configured</div>
      )}
      <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.65 }}>{msg.content}</div>
      {msg.sources && msg.sources.length > 0 && (
        <div className="chat-sources" aria-label="Source citations">
          {msg.sources.map((s, i) => (
            <SourceChip key={i} text={s} onHighlight={handleSourceHighlight} />
          ))}
        </div>
      )}
      {msg.guardian_verdict && !msg.guardian_verdict.safe && (
        <div style={{
          marginTop: 6, padding: '4px 8px', background: 'var(--fail-dim)',
          border: '1px solid rgba(139,26,26,0.2)', borderRadius: 'var(--r)',
          fontSize: 11, color: 'var(--fail)', fontFamily: 'var(--font-mono)',
        }}>
          Guardian: blocked · {msg.guardian_verdict.risk_label}
        </div>
      )}
    </div>
  )
}

// ── Main export ─────────────────────────────────────────────────────────────
export default function ChatPanel() {
  const { report, jobId, chatHistory, setChatHistory } = useStore()
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [loadedFixture, setLoadedFixture] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!loadedFixture && chatHistory.length === 0) {
      dataSource.getChatFixture().then((fixture) => {
        setChatHistory(fixture.messages)
        setLoadedFixture(true)
      }).catch(() => setLoadedFixture(true))
    }
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chatHistory])

  const send = async (message: string) => {
    if (!message.trim() || sending) return
    setSending(true)
    const userMsg: ChatMessage = { role: 'user', content: message }
    const history = chatHistory.map((m) => ({ role: m.role, content: m.content }))
    setChatHistory([...chatHistory, userMsg])
    setInput('')
    try {
      const reply = await dataSource.chat(
        jobId ?? report?.job_id ?? null,
        message,
        history,
      )
      setChatHistory((prev: ChatMessage[]) => [...prev, reply])
    } catch (err) {
      const errMsg: ChatMessage = {
        role: 'assistant',
        content: `[Chat request failed: ${err instanceof Error ? err.message : 'unknown error'}]`,
        offline_mode: true,
      }
      setChatHistory((prev: ChatMessage[]) => [...prev, errMsg])
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="screen chat-layout" style={{ minHeight: 0 }}>
      {/* Header strip */}
      <div style={{
        padding: '12px 32px', borderBottom: '1px solid var(--np-rule)',
        background: 'var(--np-surface)', display: 'flex', alignItems: 'center',
        gap: 12, flexShrink: 0,
      }}>
        <div>
          <h2 style={{ fontSize: 18, marginBottom: 2 }}>Ask the pipeline</h2>
          <p style={{ fontSize: 13, color: 'var(--np-muted)', fontFamily: 'var(--font-serif)', lineHeight: 1.4 }}>
            Answers are assembled from committed pipeline artifacts only.
            The model can say the data cannot distinguish something — treat that as a correct answer.
          </p>
        </div>
        {jobId && (
          <span className="tag" style={{ marginLeft: 'auto', color: 'var(--rust)', borderColor: 'var(--rust)', flexShrink: 0 }}>
            {jobId}
          </span>
        )}
      </div>

      {/* Message history */}
      <div className="chat-messages" aria-live="polite" aria-label="Chat messages">
        {chatHistory.length === 0 && (
          <div className="no-data" style={{ padding: '32px 0', height: 'auto', fontStyle: 'normal' }}>
            <div>
              <p style={{ marginBottom: 10 }}>Ask anything about a target, vetting result, or classification.</p>
              <p style={{ fontSize: 13 }}>Values come exclusively from pipeline artifacts — never invented.</p>
            </div>
          </div>
        )}
        {chatHistory.map((msg, i) => <MessageBubble key={i} msg={msg} />)}
        {sending && (
          <div className="chat-bubble assistant" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span className="spinner" aria-label="Assistant is responding" />
            <span style={{ color: 'var(--np-muted)', fontStyle: 'italic', fontSize: 14 }}>Thinking…</span>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Suggested prompts */}
      <div className="chat-suggestions" aria-label="Suggested prompts">
        {SUGGESTED_PROMPTS.map((p) => (
          <button
            key={p}
            className="suggestion-btn"
            onClick={() => send(p)}
            disabled={sending}
            aria-label={`Send suggested prompt: ${p}`}
          >
            {p}
          </button>
        ))}
      </div>

      {/* Input row */}
      <div className="chat-input-row">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input) } }}
          placeholder="Ask about a TCE, vetting result, or classification…"
          disabled={sending}
          aria-label="Chat input"
        />
        <button onClick={() => send(input)} disabled={sending || !input.trim()} aria-label="Send message">
          {sending ? <span className="spinner" /> : 'Send'}
        </button>
      </div>
    </div>
  )
}
