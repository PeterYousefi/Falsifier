/**
 * src/screens/LiveConsole.tsx
 * Full-screen live console in newspaper style.
 * SSE stage events with timestamps and elapsed times.
 * Replays from fixture events when no live job is running.
 */
import React, { useEffect, useRef, useState } from 'react'
import { useStore } from '../store'
import type { StageEvent } from '../data/types'
import fixtureEventsData from '../fixtures/events.json'

function formatElapsed(s: number | null | undefined): string {
  if (s == null) return '—'
  if (s < 1) return `${(s * 1000).toFixed(0)} ms`
  return `${s.toFixed(2)} s`
}

const STAGE_COLORS: Record<string, string> = {
  ingest:   'var(--rust)',
  detrend:  'var(--np-muted)',
  search:   'var(--pass)',
  vet:      'var(--warn)',
  classify: 'var(--fail)',
  pipeline: 'var(--np-faint)',
}

const EVENT_COLORS: Record<string, string> = {
  stage_start: 'var(--np-muted)',
  stage_done:  'var(--pass)',
  stage_error: 'var(--fail)',
  job_done:    'var(--pass)',
  job_failed:  'var(--fail)',
}

export default function LiveConsole() {
  const { stageEvents, jobId } = useStore()
  const [fixtureEvents, setFixtureEvents] = useState<StageEvent[]>(fixtureEventsData as StageEvent[])
  const [replaying, setReplaying] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [stageEvents, fixtureEvents])

  const eventsToShow = stageEvents.length > 0 ? stageEvents : fixtureEvents
  const isLive = stageEvents.length > 0

  const replayFixture = () => {
    if (replaying) return
    setReplaying(true)
    setFixtureEvents([])
    const events = fixtureEventsData as StageEvent[]
    let i = 0
    const step = () => {
      if (i >= events.length) { setReplaying(false); return }
      setFixtureEvents((prev) => [...prev, events[i++]])
      setTimeout(step, 200)
    }
    step()
  }

  return (
    <div className="screen" style={{ overflowY: 'hidden', display: 'flex', flexDirection: 'column', minHeight: 0 }}>

      {/* Header with article dateline */}
      <div style={{
        padding: '10px 32px', borderBottom: '2px solid var(--np-text)',
        background: 'var(--np-surface)', display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0,
      }}>
        <div>
          <div className="article-dateline" style={{ textAlign: 'left', marginBottom: 4 }}>
            CONSOLE · {isLive ? 'LIVE SSE' : 'FIXTURE REPLAY'}{jobId ? ` · ${jobId}` : ''}
          </div>
          <h2 style={{ fontSize: 16, marginBottom: 2 }}>Pipeline Console</h2>
          <p style={{ fontFamily: 'var(--font-serif)', fontSize: 13, color: 'var(--np-muted)', lineHeight: 1.4 }}>
            {isLive ? 'Live SSE events from the running job.' : 'Fixture replay — no live job running.'}
            {' '}{eventsToShow.length} events.
          </p>
        </div>
        {jobId && (
          <span className="tag" style={{ color: 'var(--rust)', borderColor: 'var(--rust)' }}>{jobId}</span>
        )}
        {!isLive && (
          <button
            className="btn-secondary"
            style={{ marginLeft: 'auto', fontSize: 12, padding: '4px 12px' }}
            onClick={replayFixture}
            disabled={replaying}
            aria-label="Replay fixture events"
          >
            {replaying ? <><span className="spinner" style={{ width: 10, height: 10 }} /> Replaying…</> : '⟳ Replay fixture'}
          </button>
        )}
      </div>

      {/* Column headers */}
      <div style={{
        display: 'flex', gap: 10, padding: '4px 32px',
        borderBottom: '1px solid var(--np-border)',
        fontFamily: 'var(--font-mono)', fontSize: 10,
        color: 'var(--np-faint)', letterSpacing: '0.07em', flexShrink: 0,
        background: 'var(--np-surface)',
      }}>
        <span style={{ minWidth: 80 }}>TIMESTAMP</span>
        <span style={{ minWidth: 90 }}>STAGE</span>
        <span style={{ minWidth: 90 }}>EVENT</span>
        <span style={{ flex: 1 }}>DETAIL</span>
        <span style={{ minWidth: 70, textAlign: 'right' }}>ELAPSED</span>
      </div>

      <div className="console-inner" style={{ flex: 1, overflowY: 'auto', padding: '4px 32px' }}>
        {eventsToShow.length === 0 && (
          <div style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', color: 'var(--np-muted)', padding: '16px 0' }}>
            No events yet. Submit a job from the Investigate screen, or click "Replay fixture".
          </div>
        )}
        {eventsToShow.map((evt, i) => (
          <div key={i} className="console-line">
            <span className="con-ts">{evt.ts ?? '—'}</span>
            <span style={{
              minWidth: 90, flexShrink: 0,
              color: STAGE_COLORS[evt.stage] ?? 'var(--np-muted)',
              fontFamily: 'var(--font-mono)', fontSize: 11,
            }}>
              {evt.stage}
            </span>
            <span style={{
              minWidth: 90, flexShrink: 0,
              color: EVENT_COLORS[evt.event] ?? 'var(--np-muted)',
              fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 500,
            }}>
              {evt.event.replace(/_/g, ' ')}
            </span>
            <span className="con-url">{evt.detail}</span>
            <span className="con-ms">{formatElapsed(evt.elapsed_seconds)}</span>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
