/**
 * src/ConsolePanel.jsx
 * Live console showing real endpoint calls and response times.
 *
 * Displays every fetch/SSE call made by the store in chronological order:
 *   timestamp  method  url  status  latency
 *
 * Colour coding: green=ok, red=err, blue=SSE.
 * Auto-scrolls to bottom on new entries.
 */
import React, { useRef, useEffect } from 'react'
import { useStore } from './store.js'

export default function ConsolePanel() {
  const { consoleLines } = useStore()
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [consoleLines])

  return (
    <div className="panel panel--console">
      <div className="panel-header">
        Console
        <span className="tag">real calls</span>
        <span style={{ marginLeft: 'auto', color: 'var(--muted)' }}>{consoleLines.length} entries</span>
      </div>
      <div className="console-inner">
        {consoleLines.length === 0 && (
          <div style={{ color: 'var(--muted)', padding: '8px 0' }}>
            No API calls yet. Submit a target to begin.
          </div>
        )}
        {consoleLines.map((line, i) => {
          const isSSE    = line.method === 'SSE'
          const isOk     = line.status === 200 || line.status === '✓' || (typeof line.status === 'number' && line.status < 400)
          const isErr    = line.status === 'ERR' || line.status === '✗' || (typeof line.status === 'number' && line.status >= 400)
          const isPending = line.pending

          return (
            <div key={i} className="console-line">
              <span className="ts">{line.ts}</span>
              <span className="method" style={{ color: isSSE ? 'var(--warn)' : 'var(--accent)' }}>
                {line.method}
              </span>
              <span className="url">{line.url}</span>
              {isPending ? (
                <span className="status" style={{ color: 'var(--muted)' }}>…</span>
              ) : (
                <span className={`status ${isOk ? 'ok' : isErr ? 'err' : ''}`}>
                  {line.status ?? ''}
                </span>
              )}
              <span className="ms">{line.ms != null ? line.ms + 'ms' : ''}</span>
            </div>
          )
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
