/**
 * src/screens/ChatPanel.tsx
 * Chat panel: messages with artifact-source chips, suggested prompts,
 * offline fallback indicator.
 */
import React, { useState, useRef, useEffect } from 'react'
import { useStore } from '../store'
import { dataSource } from '../data/DataSource'
import type { ChatMessage } from '../data/types'

const SUGGESTED_PROMPTS = [
  'Why was this rejected?',
  'What would settle it?',
  'Refit at 2× period',
  'What is the transit depth?',
  'What does the stellar density test show?',
]

// ── Source chip ────────────────────────────────────────────────────────────
function SourceChip({ text, onHighlight }: { text: string; onHighlight: (text: string) => void }) {
  const [active, setActive] = useState(false)

  const handleClick = () => {
    setActive(true)
    onHighlight(text)
    setTimeout(() => setActive(false), 1500)
  }

  // Extract clean label from "[source: tool(args)]"
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
    // Map source tool names to panel keys
    const lower = sourceText.toLowerCase()
    if (lower.includes('vet')) setHighlightedPanel('vet')
    else if (lower.includes('planet') || lower.includes('search')) setHighlightedPanel('search')
    else if (lower.includes('classify')) setHighlightedPanel('classify')
    else if (lower.includes('ingest')) setHighlightedPanel('ingest')
  }

  const isOffline = msg.offline_mode === true

  return (
    <div className={`chat-bubble ${msg.role}${isOffline ? ' offline' : ''}`}>
      {isOffline && <div className="offline-badge" style={{ marginBottom: 5 }}>⚠ offline mode — no API key configured</div>}
      <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.55 }}>{msg.content}</div>
      {msg.sources && msg.sources.length > 0 && (
        <div className="chat-sources" aria-label="Source citations">
          {msg.sources.map((s, i) => (
            <SourceChip key={i} text={s} onHighlight={handleSourceHighlight} />
          ))}
        </div>
      )}
      {msg.guardian_verdict && !msg.guardian_verdict.safe && (
        <div style={{
          marginTop: 5, padding: '3px 7px', background: 'var(--fail-dim)',
          border: '1px solid rgba(239,68,68,0.2)', borderRadius: 'var(--r)',
          fontSize: 10, color: 'var(--fail)',
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

  // Load fixture chat history on mount
  useEffect(() => {
    if (!loadedFixture && chatHistory.length === 0) {
      dataSource.getChatFixture().then((fixture) => {
        setChatHistory(fixture.messages)
        setLoadedFixture(true)
      }).catch(() => setLoadedFixture(true))
    }
  }, [])

  // Auto-scroll to bottom
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
    <div className="screen chat-layout">
      <div className="panel-header">
        Chat
        <span className="tag">artifact-grounded</span>
        {jobId && <span className="tag" style={{ color: 'var(--accent)' }}>{jobId}</span>}
        <span className="spacer" />
        <span style={{ fontSize: 10, color: 'var(--muted)' }}>
          Clicking a source chip highlights the value in the detail panel
        </span>
      </div>

      {/* Message history */}
      <div className="chat-messages" aria-live="polite" aria-label="Chat messages">
        {chatHistory.length === 0 && (
          <div className="no-data" style={{ height: 'auto', padding: '20px 0' }}>
            Ask about a TCE. Values come only from pipeline artifacts.
          </div>
        )}
        {chatHistory.map((msg, i) => <MessageBubble key={i} msg={msg} />)}
        {sending && (
          <div className="chat-bubble assistant" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span className="spinner" aria-label="Assistant is responding" />
            <span style={{ color: 'var(--muted)', fontSize: 11 }}>thinking…</span>
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
