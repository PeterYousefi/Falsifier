/**
 * src/App.jsx
 * Root application component.
 *
 * Layout:
 *   ┌─────────────────────────┬──────────┐
 *   │  3D Orbital Viewer      │ Detail   │
 *   │  (drag/zoom/click)      │ Panel    │
 *   ├─────────────────────────┴──────────┤
 *   │  Live Console                       │
 *   └─────────────────────────────────────┘
 *
 * Non-claim banner is pinned to the bottom of the viewer.
 * Planets never speak, have faces, or are animated as talking.
 * When the store fires setHighlightedPanel, DetailPanel highlights
 * the relevant section.
 */
import React, { useEffect, useRef, useState } from 'react'
import OrbitalViewer from './OrbitalViewer.jsx'
import DetailPanel   from './DetailPanel.jsx'
import ConsolePanel  from './ConsolePanel.jsx'
import { useStore }  from './store.js'

function TargetForm() {
  const { targetId, setTargetId, isSubmitting, submitJob, jobStatus } = useStore()
  const [mission, setMission] = useState('Kepler')
  const [cadence, setCadence] = useState('long')

  const busy = isSubmitting || jobStatus === 'running' || jobStatus === 'queued'

  const handleSubmit = (e) => {
    e.preventDefault()
    if (targetId.trim()) submitJob(targetId.trim(), mission, cadence)
  }

  return (
    <form className="search-bar" onSubmit={handleSubmit}>
      <input
        value={targetId}
        onChange={(e) => setTargetId(e.target.value)}
        placeholder="KIC 11904151 / TIC 261136679"
        disabled={busy}
        aria-label="Target identifier"
      />
      <select
        value={mission}
        onChange={(e) => setMission(e.target.value)}
        disabled={busy}
        style={{ background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', borderRadius: 4, padding: '4px 6px', font: 'inherit', fontSize: 12 }}
        aria-label="Mission"
      >
        <option>Kepler</option>
        <option>K2</option>
        <option>TESS</option>
      </select>
      <select
        value={cadence}
        onChange={(e) => setCadence(e.target.value)}
        disabled={busy}
        style={{ background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', borderRadius: 4, padding: '4px 6px', font: 'inherit', fontSize: 12 }}
        aria-label="Cadence"
      >
        <option value="long">long</option>
        <option value="short">short</option>
      </select>
      <button type="submit" disabled={busy || !targetId.trim()}>
        {busy ? '…' : 'Run'}
      </button>
    </form>
  )
}

function StatusBadge() {
  const { jobStatus } = useStore()
  if (!jobStatus) return null
  const colors = { queued: '#6b7280', running: '#3b82f6', done: '#22c55e', failed: '#ef4444' }
  return (
    <div style={{
      position: 'absolute', top: 36, right: 12, zIndex: 10,
      background: 'rgba(10,12,15,0.85)', border: `1px solid ${colors[jobStatus] ?? 'var(--border)'}`,
      borderRadius: 4, padding: '2px 8px', fontSize: 11, color: colors[jobStatus],
    }}>
      {jobStatus}
    </div>
  )
}

export default function App() {
  const { loadProvenance } = useStore()

  useEffect(() => {
    loadProvenance()
  }, [])

  return (
    <div className="layout">
      {/* 3D viewer panel */}
      <div className="panel panel--viewer">
        <div className="panel-header">
          Orbital system
          <span className="tag">3D · drag/scroll/click</span>
          <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--muted)' }}>
            sphere&thinsp;=&thinsp;depth·radius&ensp;colour&thinsp;=&thinsp;T<sub>eq</sub>&ensp;orbit&thinsp;=&thinsp;period
          </span>
        </div>
        <TargetForm />
        <StatusBadge />
        <OrbitalViewer />
        <div className="non-claim-banner">
          Not a biosignature detector · No exoplanet biosignature has ever been confirmed
        </div>
      </div>

      {/* Detail panel */}
      <DetailPanel />

      {/* Console */}
      <ConsolePanel />
    </div>
  )
}
