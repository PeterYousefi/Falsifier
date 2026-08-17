/**
 * src/store.js
 * Central Zustand store.
 *
 * All numeric values displayed to the user originate from API responses or
 * committed pipeline artifacts.  No scientific constants are hardcoded here
 * (AGENTS.md Rule 1).  The only physical constant allowed is the Stefan-
 * Boltzmann equilibrium temperature formula for computing habitable zone
 * boundaries — and those bounds are labelled "computed" in the UI, not
 * asserted as measured values.
 */
import { create } from 'zustand'

export const useStore = create((set, get) => ({
  // ── Target / job state ────────────────────────────────────────────────
  targetId: '',
  setTargetId: (v) => set({ targetId: v }),

  jobId: null,
  jobStatus: null,   // 'queued' | 'running' | 'done' | 'failed'
  report: null,      // DetectionReport from API
  isSubmitting: false,

  // ── Selected TCE in the 3D viewer ─────────────────────────────────────
  selectedTceId: null,
  setSelectedTceId: (id) => set({ selectedTceId: id }),

  // ── Highlighted panel (driven by chat/data references) ────────────────
  // Keys: 'vet', 'classify', 'lc', 'ingest', 'search', 'detrend' | null
  highlightedPanel: null,
  setHighlightedPanel: (panel) => {
    set({ highlightedPanel: panel })
    if (panel) setTimeout(() => set({ highlightedPanel: null }), 1800)
  },

  // ── SSE event log (for console panel) ─────────────────────────────────
  consoleLines: [],
  pushConsoleLine: (line) =>
    set((s) => ({
      consoleLines: [...s.consoleLines.slice(-199), line],
    })),

  // ── Provenance data ───────────────────────────────────────────────────
  provenance: null,

  // ── Actions ───────────────────────────────────────────────────────────

  submitJob: async (targetId, mission, cadence) => {
    const { pushConsoleLine } = get()
    set({ isSubmitting: true, jobId: null, jobStatus: null, report: null })

    const t0 = performance.now()
    pushConsoleLine({
      ts: _ts(), method: 'POST', url: '/jobs',
      status: null, ms: null, pending: true,
    })

    try {
      const res = await fetch('/jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_id: targetId, mission, cadence }),
      })
      const ms = Math.round(performance.now() - t0)
      const data = await res.json()
      _replaceLastConsole(set, get, { status: res.status, ms })

      if (!res.ok) throw new Error(data.detail ?? 'POST /jobs failed')

      set({ jobId: data.job_id, jobStatus: 'queued', isSubmitting: false })
      get()._streamJob(data.job_id)
    } catch (err) {
      const ms = Math.round(performance.now() - t0)
      _replaceLastConsole(set, get, { status: 'ERR', ms })
      set({ isSubmitting: false, jobStatus: 'failed' })
    }
  },

  _streamJob: (jobId) => {
    const { pushConsoleLine, setHighlightedPanel } = get()

    pushConsoleLine({
      ts: _ts(), method: 'GET', url: `/jobs/${jobId}/stream`,
      status: null, ms: null, pending: true,
    })

    const sse = new EventSource(`/jobs/${jobId}/stream`)
    const t0 = performance.now()

    sse.onmessage = (e) => {
      try {
        const evt = JSON.parse(e.data)
        pushConsoleLine({
          ts: _ts(), method: 'SSE', url: evt.stage,
          status: evt.status === 'ok' ? '✓' : '✗', ms: evt.elapsed_seconds != null ? `${(evt.elapsed_seconds * 1000).toFixed(0)}ms` : null,
          pending: false,
        })
        // Highlight the matching panel when a stage completes
        const panelMap = { ingest: 'ingest', detrend: 'detrend', search: 'search', vet: 'vet' }
        const panel = panelMap[evt.stage]
        if (panel && evt.event === 'stage_done') setHighlightedPanel(panel)

        if (evt.event === 'job_done' || evt.event === 'job_failed') {
          _replaceLastConsole(set, get, { status: evt.event === 'job_done' ? 200 : 500, ms: Math.round(performance.now() - t0) })
          sse.close()
          set({ jobStatus: evt.event === 'job_done' ? 'done' : 'failed' })
          if (evt.event === 'job_done') get()._fetchReport(jobId)
        }
      } catch (_) {}
    }

    sse.onerror = () => {
      sse.close()
      _replaceLastConsole(set, get, { status: 'ERR', ms: Math.round(performance.now() - t0) })
    }
  },

  _fetchReport: async (jobId) => {
    const { pushConsoleLine } = get()
    const t0 = performance.now()
    pushConsoleLine({ ts: _ts(), method: 'GET', url: `/jobs/${jobId}`, status: null, ms: null, pending: true })
    try {
      const res = await fetch(`/jobs/${jobId}`)
      const ms = Math.round(performance.now() - t0)
      _replaceLastConsole(set, get, { status: res.status, ms })
      if (res.ok) {
        const data = await res.json()
        set({ report: data.report })
      }
    } catch (_) {
      _replaceLastConsole(set, get, { status: 'ERR', ms: Math.round(performance.now() - t0) })
    }
  },

  loadProvenance: async () => {
    const { pushConsoleLine } = get()
    const t0 = performance.now()
    pushConsoleLine({ ts: _ts(), method: 'GET', url: '/provenance', status: null, ms: null, pending: true })
    try {
      const res = await fetch('/provenance')
      const ms = Math.round(performance.now() - t0)
      _replaceLastConsole(set, get, { status: res.status, ms })
      if (res.ok) {
        const data = await res.json()
        set({ provenance: data })
      }
    } catch (_) {
      _replaceLastConsole(set, get, { status: 'ERR', ms: Math.round(performance.now() - t0) })
    }
  },
}))

// ── helpers ──────────────────────────────────────────────────────────────────
function _ts() {
  const d = new Date()
  return `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}:${String(d.getSeconds()).padStart(2,'0')}.${String(d.getMilliseconds()).padStart(3,'0')}`
}

function _replaceLastConsole(set, get, patch) {
  const lines = [...get().consoleLines]
  if (lines.length > 0) {
    lines[lines.length - 1] = { ...lines[lines.length - 1], ...patch, pending: false }
    set({ consoleLines: lines })
  }
}
