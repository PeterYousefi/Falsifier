/**
 * src/store.ts
 * Central Zustand store — no scientific literals allowed (AGENTS.md Rule 1).
 * All displayed values come from API responses / fixture artifacts.
 */
import { create } from 'zustand'
import { dataSource } from './data/DataSource'
import type { DetectionReport, ProvenanceReport, StageEvent, ChatMessage } from './data/types'

interface ConsoleEntry {
  ts: string
  method: string
  url: string
  status: string | number | null
  ms: string | number | null
  pending: boolean
}

interface AppState {
  // Navigation
  activeScreen: string
  setActiveScreen: (s: string) => void

  // Target / job state
  targetId: string
  setTargetId: (v: string) => void
  jobId: string | null
  jobStatus: string | null
  report: DetectionReport | null
  isSubmitting: boolean
  jobError: string | null

  // Live progress (stage name + elapsed time from SSE / poll)
  progressStage: string | null
  progressElapsed: number | null

  // Selected TCE
  selectedTceId: string | null
  setSelectedTceId: (id: string | null) => void

  // Highlighted panel
  highlightedPanel: string | null
  setHighlightedPanel: (panel: string | null) => void

  // Console lines
  consoleLines: ConsoleEntry[]
  pushConsoleLine: (line: ConsoleEntry) => void
  replaceLastConsole: (patch: Partial<ConsoleEntry>) => void

  // Provenance
  provenance: ProvenanceReport | null

  // SSE event log for console screen
  stageEvents: StageEvent[]

  // Chat history (per screen session)
  chatHistory: ChatMessage[]
  setChatHistory: (msgs: ChatMessage[] | ((prev: ChatMessage[]) => ChatMessage[])) => void

  // Actions
  submitJob: (targetId: string, mission: string, cadence: string) => Promise<void>
  loadProvenance: () => Promise<void>
  /** @deprecated loadFixtureJob is no longer called automatically.
   *  Kept for backward compatibility; call explicitly to pre-load fixture data. */
  loadFixtureJob: () => Promise<void>
}

function ts(): string {
  const d = new Date()
  return [
    String(d.getHours()).padStart(2, '0'),
    ':',
    String(d.getMinutes()).padStart(2, '0'),
    ':',
    String(d.getSeconds()).padStart(2, '0'),
    '.',
    String(d.getMilliseconds()).padStart(3, '0'),
  ].join('')
}

export const useStore = create<AppState>((set, get) => ({
  activeScreen: 'system',
  setActiveScreen: (s) => set({ activeScreen: s }),

  targetId: '',
  setTargetId: (v) => set({ targetId: v }),
  jobId: null,
  jobStatus: null,
  report: null,
  isSubmitting: false,
  jobError: null,

  progressStage: null,
  progressElapsed: null,

  selectedTceId: null,
  setSelectedTceId: (id) => set({ selectedTceId: id }),

  highlightedPanel: null,
  setHighlightedPanel: (panel) => {
    set({ highlightedPanel: panel })
    if (panel) setTimeout(() => set({ highlightedPanel: null }), 1800)
  },

  consoleLines: [],
  pushConsoleLine: (line) =>
    set((s) => ({ consoleLines: [...s.consoleLines.slice(-299), line] })),
  replaceLastConsole: (patch) =>
    set((s) => {
      const lines = [...s.consoleLines]
      if (lines.length > 0) lines[lines.length - 1] = { ...lines[lines.length - 1], ...patch, pending: false }
      return { consoleLines: lines }
    }),

  stageEvents: [],
  chatHistory: [],
  setChatHistory: (msgs) =>
    typeof msgs === 'function'
      ? set((s) => ({ chatHistory: (msgs as (prev: ChatMessage[]) => ChatMessage[])(s.chatHistory) }))
      : set({ chatHistory: msgs }),

  provenance: null,

  submitJob: async (targetId, mission, cadence) => {
    const { pushConsoleLine, replaceLastConsole } = get()
    set({
      isSubmitting: true,
      jobId: null,
      jobStatus: null,
      report: null,
      stageEvents: [],
      jobError: null,
      progressStage: null,
      progressElapsed: null,
    })
    const t0 = performance.now()
    pushConsoleLine({ ts: ts(), method: 'POST', url: '/jobs', status: null, ms: null, pending: true })

    try {
      const jobId = await dataSource.submitJob({ target_id: targetId, mission, author: mission, cadence })
      replaceLastConsole({ status: 202, ms: Math.round(performance.now() - t0) })
      set({ jobId, jobStatus: 'queued', isSubmitting: false })

      pushConsoleLine({ ts: ts(), method: 'SSE', url: `/jobs/${jobId}/stream`, status: null, ms: null, pending: true })
      const sseT0 = performance.now()

      dataSource.streamJob(
        jobId,
        (evt) => {
          set((s) => ({ stageEvents: [...s.stageEvents, evt] }))

          // Update live progress display
          if (evt.event === 'stage_start') {
            set({ progressStage: evt.stage, progressElapsed: null })
          } else if (evt.event === 'stage_done') {
            set({ progressStage: evt.stage, progressElapsed: evt.elapsed_seconds })
          } else if (evt.event === 'stage_error') {
            set({ progressStage: evt.stage, progressElapsed: evt.elapsed_seconds })
          }

          get().pushConsoleLine({
            ts: ts(),
            method: 'SSE',
            url: evt.stage,
            status: evt.status === 'ok' ? '✓' : '✗',
            ms: evt.elapsed_seconds != null ? `${(evt.elapsed_seconds * 1000).toFixed(0)}ms` : null,
            pending: false,
          })
          const panelMap: Record<string, string> = { ingest: 'ingest', detrend: 'detrend', search: 'search', vet: 'vet' }
          const panel = panelMap[evt.stage]
          if (panel && evt.event === 'stage_done') get().setHighlightedPanel(panel)
          if (evt.event === 'job_done') {
            set({ jobStatus: 'done', progressStage: null })
          }
          if (evt.event === 'job_failed') {
            // Extract the error detail from the event for user-facing display
            set({ jobStatus: 'failed', jobError: evt.detail, progressStage: null })
          }
        },
        async () => {
          replaceLastConsole({ status: 200, ms: Math.round(performance.now() - sseT0) })
          // Fetch full report
          try {
            const record = await dataSource.getJob(jobId)
            if (record.report) set({ report: record.report })
            if (record.error) set({ jobError: record.error })
          } catch (_) {}
        },
      )
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      replaceLastConsole({ status: 'ERR', ms: Math.round(performance.now() - t0) })
      set({ isSubmitting: false, jobStatus: 'failed', jobError: msg, progressStage: null })
    }
  },

  loadProvenance: async () => {
    const { pushConsoleLine, replaceLastConsole } = get()
    const t0 = performance.now()
    pushConsoleLine({ ts: ts(), method: 'GET', url: '/provenance', status: null, ms: null, pending: true })
    try {
      const data = await dataSource.getProvenance()
      replaceLastConsole({ status: 200, ms: Math.round(performance.now() - t0) })
      set({ provenance: data })
    } catch (_) {
      replaceLastConsole({ status: 'ERR', ms: Math.round(performance.now() - t0) })
    }
  },

  loadFixtureJob: async () => {
    try {
      const record = await dataSource.getJob('fixture-job-001')
      if (record.report) {
        set({ report: record.report, jobId: record.job_id, jobStatus: 'done' })
      }
    } catch (_) {}
  },
}))
