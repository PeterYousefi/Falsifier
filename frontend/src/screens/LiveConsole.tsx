/**
 * src/screens/LiveConsole.tsx
 * Full-screen live console: SSE stage events with real endpoint names and
 * response times. Replays from fixture events when no live job is running.
 */
import React, { useEffect, useRef, useState } from 'react'
import { useStore } from '../store'
import { dataSource } from '../data/DataSource'
import type { StageEvent } from '../data/types'

function formatElapsed(s: number | null | undefined): string {
  if (s == null) return '—'
  if (s < 1) return `${(s * 1000).toFixed(0)} ms`
  return `${s.toFixed(2)} s`
}

function eventBadge(evt: string): { label: string; color: string } {
  switch (evt) {
    case 'stage_start': return { label: 'START', color: 'var(--accent)' }
    case 'stage_done':  return { label: 'DONE',  color: 'var(--pass)' }
    case 'stage_error': return { label: 'ERROR', color: 'var(--fail)' }
    case 'job_done':    return { label: 'JOB OK', color: 'var(--pass)' }
    case 'job_failed':  return { label: 'JOB ERR', color: 'var(--fail)' }
    default:            return { label: evt,    color: 'var(--muted)' }
  }
}

export default function LiveConsole() {
  const { stageEvents, jobId } = useStore()
  const [fixtureEvents, setFixtureEvents] = useState<StageEvent[]>([])
  const [replaying, setReplaying] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  // Load fixture events on mount
  useEffect(() => {
    import('../fixtures/events.json').then((m) => {
      setFixtureEvents(m.default as StageEvent[])
    })
  }, [])

  // Auto-scroll
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [stageEvents, fixtureEvents])

  const eventsToShow = stageEvents.length > 0 ? stageEvents : fixtureEvents
  const isLive = stageEvents.length > 0

  const replayFixture = () => {
    if (replaying) return
    setReplaying(true)
    setFixtureEvents([])
    dataSource.getChatFixture().then(() => {}).catch(() => {})
    // Re-import and replay
    import('../fixtures/events.json').then((m) => {
      const events = m.default as StageEvent[]
      let i = 0
      const step = () => {
        if (i >= events.length) { setReplaying(false); return }
        setFixtureEvents((prev) => [...prev, events[i++]])
        setTimeout(step, 200)
      }
      step()
    })
  }

  return (
    <div className="screen console-full">
      <div className="panel-header">
        Live Console
        <span className="tag">{isLive ? 'live SSE' : 'fixture replay'}</span>
        {jobId && <span className="tag" style={{ color: 'var(--accent)' }}>{jobId}</span>}
        <span className="spacer" />
        <span style={{ fontSize: 10, color: 'var(--muted)', marginRight: 8 }}>
          {eventsToShow.length} events
        </span>
        {!isLive && (
          <button
            style={{
              background: 'none', border: '1px solid var(--border)', borderRadius: 'var(--r)',
              color: 'var(--muted)', cursor: replaying ? 'default' : 'pointer',
              font: 'inherit', fontSize: 10, padding: '1px 8px',
            }}
            onClick={replayFixture}
            disabled={replaying}
            aria-label="Replay fixture events"
          >
            {replaying ? <><span className="spinner" /> replaying…</> : '⟳ replay fixture'}
          </button>
        )}
      </div>

      {/* Column headers */}
      <div style={{
        display: 'flex', gap: 8, padding: '3px 10px',
        borderBottom: '1px solid var(--border)',
        fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--muted)',
      }}>
        <span style={{ minWidth: 80 }}>timestamp</span>
        <span style={{ minWidth: 90 }}>stage</span>
        <span style={{ minWidth: 80 }}>event</span>
        <span style={{ flex: 1 }}>detail</span>
        <span style={{ minWidth: 64, textAlign: 'right' }}>elapsed</span>
      </div>

      <div className="console-inner" style={{ flex: 1, overflowY: 'auto' }}>
        {eventsToShow.length === 0 && (
          <div style={{ color: 'var(--muted)', padding: '8px 0' }}>
            No events yet. Submit a job from the System screen, or click "replay fixture".
          </div>
        )}
        {eventsToShow.map((evt, i) => {
          const badge = eventBadge(evt.event)
          return (
            <div key={i} className="event-row">
              <span className="evt-ts">{evt.ts ?? '—'}</span>
              <span className={`evt-stage ${evt.stage}`}>{evt.stage}</span>
              <span className="evt-event">
                <span style={{ color: badge.color, fontWeight: 500 }}>{badge.label}</span>
              </span>
              <span className="evt-detail">{evt.detail}</span>
              <span className="evt-elapsed">{formatElapsed(evt.elapsed_seconds)}</span>
            </div>
          )
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
