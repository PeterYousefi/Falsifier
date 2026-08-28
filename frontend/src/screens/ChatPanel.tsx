/**
 * src/screens/ChatPanel.tsx
 * Chat panel in newspaper style.
 * Answers in serif prose on a tinted panel.
 * Monospace artifact-source chips beneath each answer.
 * Suggested prompts as buttons. Model may say "can't distinguish" — correct answer.
 */
import React, { useState, useRef, useEffect, Component, type ReactNode, type ErrorInfo } from 'react'
import { useStore } from '../store'
import { dataSource, getLiveRemaining } from '../data/DataSource'
import type { ChatMessage } from '../data/types'
import { FixtureProvenanceBadge } from './CandidateDetail'

// ── Error Boundary ─────────────────────────────────────────────────────────
interface ErrorBoundaryState { hasError: boolean; message: string }

class ChatErrorBoundary extends Component<{ children: ReactNode }, ErrorBoundaryState> {
  constructor(props: { children: ReactNode }) {
    super(props)
    this.state = { hasError: false, message: '' }
  }

  static getDerivedStateFromError(err: unknown): ErrorBoundaryState {
    const message = err instanceof Error ? err.message : String(err)
    return { hasError: true, message }
  }

  componentDidCatch(err: Error, info: ErrorInfo) {
    // Log to console so developers can diagnose the failure.
    console.error('[ChatPanel] Uncaught render error:', err, info.componentStack)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="screen" style={{ padding: '32px', color: 'var(--fail, #8b1a1a)' }}>
          <strong>Chat panel error</strong>
          <p style={{ marginTop: 8, fontSize: 13, fontFamily: 'var(--font-mono, monospace)' }}>
            {this.state.message || 'An unexpected error occurred.'}
          </p>
          <button
            style={{ marginTop: 12 }}
            onClick={() => this.setState({ hasError: false, message: '' })}
          >
            Retry
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

// Prompts that have committed offline answers assembled from fixture artifacts.
// "Refit at half the period" is omitted — it requires the pipeline to actually
// run a new search and has no committed fixture answer. Shipping a stub for it
// is worse than not shipping the button at all.
const SUGGESTED_PROMPTS = [
  'Why was this classified as a candidate?',
  'What does the stellar density test show?',
  'Could the data distinguish this from an eclipsing binary?',
  'What would settle it?',
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
      {msg.guardian_verdict && msg.guardian_verdict.safe === false && (
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
  // Use active job_id; fall back to report job_id; never fall back to a fixture id
  // (binding chat to fixture-job-001 would surface the fixture id in citations).
  const activeJobId = jobId ?? (report?.fixture_provenance ? null : report?.job_id ?? null)
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [loadedFixture, setLoadedFixture] = useState(false)
  // Remaining live-chat budget — null means no live-chat mode or not yet used.
  const [remaining, setRemaining] = useState<number | null>(getLiveRemaining)
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
        activeJobId,
        message,
        history,
      )
      setChatHistory((prev: ChatMessage[]) => [...prev, reply])
      // Sync remaining count after each live call.
      const r = getLiveRemaining()
      if (r !== null) setRemaining(r)
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
    <ChatErrorBoundary>
    <div className="screen chat-layout" style={{ minHeight: 0 }}>
      {/* Header strip with article dateline */}
      <div style={{
        padding: '12px 32px', borderBottom: '1px solid var(--np-rule)',
        background: 'var(--np-surface)', display: 'flex', alignItems: 'center',
        gap: 12, flexShrink: 0,
      }}>
        <div>
          {/* Fixture provenance badge when chat is operating on fixture data */}
          {report && <FixtureProvenanceBadge report={report} />}
          <div className="article-dateline" style={{ textAlign: 'left', marginBottom: 4 }}>
            ASK · PIPELINE CHAT{activeJobId ? ` · ${activeJobId}` : ''}
          </div>
          <h2 style={{ fontSize: 18, marginBottom: 2 }}>Ask the pipeline</h2>
          <p className="standfirst" style={{ fontSize: 13, marginBottom: 0 }}>
            Answers are assembled from committed pipeline artifacts only.
            The model can say the data cannot distinguish something — that is a correct answer.
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
      {remaining !== null && (
        <div
          style={{
            padding: '4px 16px 8px',
            fontSize: 12,
            color: remaining === 0 ? 'var(--fail, #8b1a1a)' : 'var(--np-muted, #57606a)',
            fontFamily: 'var(--font-mono, monospace)',
            textAlign: 'right',
          }}
          aria-live="polite"
        >
          {remaining === 0
            ? 'Live question limit reached for this session'
            : `${remaining} of ${3} live question${remaining !== 1 ? 's' : ''} remaining this session`}
        </div>
      )}
    </div>
    </ChatErrorBoundary>
  )
}
