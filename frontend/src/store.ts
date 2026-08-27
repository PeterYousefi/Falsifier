/**
 * src/store.ts
 * Central Zustand store — no scientific literals allowed (AGENTS.md Rule 1).
 * All displayed values come from API responses / fixture artifacts.
 *
 * Job-id persistence
 * ------------------
 * The active jobId is written to sessionStorage under SESSION_JOB_KEY
 * whenever it changes, and cleared when a new job starts or when the job
 * completes with an error.  On mount (App.tsx useEffect) the persisted value
 * is read back via rehydrateJob(), which calls GET /jobs/{id} and, if the job
 * is still running, attaches a new SSE stream.
 */
import { create } from 'zustand'
import { dataSource, isFixtureMode } from './data/DataSource'
import type { DetectionReport, ProvenanceReport, StageEvent, ChatMessage } from './data/types'

export const SESSION_JOB_KEY = 'falsifier_active_job_id'

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
  mission: string
  setMission: (v: string) => void
  cadence: string
  setCadence: (v: string) => void
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
  /**
   * On mount: if sessionStorage has a persisted jobId, fetch its current state
   * from GET /jobs/{id} and reattach a stream when the job is still in-flight.
   * Called once from App.tsx useEffect — idempotent if jobId is already set.
   */
  rehydrateJob: () => Promise<void>
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
  mission: 'Kepler',
  setMission: (v) => set({ mission: v }),
  cadence: 'long',
  setCadence: (v) => set({ cadence: v }),
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
    // Clear any persisted job before starting a new one
    try { sessionStorage.removeItem(SESSION_JOB_KEY) } catch (_) {}
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
      const jobId = await dataSource.submitJob({ target_id: targetId, mission, cadence })
      replaceLastConsole({ status: 202, ms: Math.round(performance.now() - t0) })
      // Persist job_id so a page reload can resume streaming
      try { sessionStorage.setItem(SESSION_JOB_KEY, jobId) } catch (_) {}
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
            // Job is complete — no need to persist the id further
            try { sessionStorage.removeItem(SESSION_JOB_KEY) } catch (_) {}
          }
          if (evt.event === 'job_failed') {
            // Extract the error detail from the event for user-facing display
            set({ jobStatus: 'failed', jobError: evt.detail, progressStage: null })
            try { sessionStorage.removeItem(SESSION_JOB_KEY) } catch (_) {}
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
      try { sessionStorage.removeItem(SESSION_JOB_KEY) } catch (_) {}
    }
  },

  rehydrateJob: async () => {
    // Do not rehydrate if a job is already loaded in this session
    if (get().jobId) return
    // In fixture mode there is no live backend — skip silently
    if (isFixtureMode) return

    let storedId: string | null = null
    try { storedId = sessionStorage.getItem(SESSION_JOB_KEY) } catch (_) {}
    if (!storedId) return

    try {
      const record = await dataSource.getJob(storedId)
      if (record.status === 'done') {
        // Job finished while we were away — restore the report silently
        try { sessionStorage.removeItem(SESSION_JOB_KEY) } catch (_) {}
        set({
          jobId: record.job_id,
          jobStatus: 'done',
          report: record.report ?? null,
          targetId: record.request?.target_id ?? '',
          mission: record.request?.mission ?? 'Kepler',
          cadence: record.request?.cadence ?? 'long',
        })
        return
      }
      if (record.status === 'failed') {
        try { sessionStorage.removeItem(SESSION_JOB_KEY) } catch (_) {}
        set({
          jobId: record.job_id,
          jobStatus: 'failed',
          jobError: record.error ?? 'Pipeline run failed.',
          targetId: record.request?.target_id ?? '',
          mission: record.request?.mission ?? 'Kepler',
          cadence: record.request?.cadence ?? 'long',
        })
        return
      }

      // Job is still running (queued / running) — restore state and reattach stream
      set({
        jobId: record.job_id,
        jobStatus: record.status,
        targetId: record.request?.target_id ?? '',
        mission: record.request?.mission ?? 'Kepler',
        cadence: record.request?.cadence ?? 'long',
        // Replay any events already stored in the job record
        stageEvents: record.events ?? [],
        progressStage: (() => {
          const evts = record.events ?? []
          const last = [...evts].reverse().find(e => e.event === 'stage_start' || e.event === 'stage_done')
          return last?.stage ?? null
        })(),
      })

      const { pushConsoleLine, replaceLastConsole } = get()
      const sseT0 = performance.now()
      pushConsoleLine({ ts: ts(), method: 'SSE', url: `/jobs/${record.job_id}/stream`, status: null, ms: null, pending: true })

      dataSource.streamJob(
        record.job_id,
        (evt) => {
          set((s) => ({ stageEvents: [...s.stageEvents, evt] }))
          if (evt.event === 'stage_start') {
            set({ progressStage: evt.stage, progressElapsed: null })
          } else if (evt.event === 'stage_done') {
            set({ progressStage: evt.stage, progressElapsed: evt.elapsed_seconds })
          } else if (evt.event === 'stage_error') {
            set({ progressStage: evt.stage, progressElapsed: evt.elapsed_seconds })
          }
          if (evt.event === 'job_done') {
            set({ jobStatus: 'done', progressStage: null })
            try { sessionStorage.removeItem(SESSION_JOB_KEY) } catch (_) {}
          }
          if (evt.event === 'job_failed') {
            set({ jobStatus: 'failed', jobError: evt.detail, progressStage: null })
            try { sessionStorage.removeItem(SESSION_JOB_KEY) } catch (_) {}
          }
        },
        async () => {
          replaceLastConsole({ status: 200, ms: Math.round(performance.now() - sseT0) })
          try {
            const rec = await dataSource.getJob(record.job_id)
            if (rec.report) set({ report: rec.report })
            if (rec.error) set({ jobError: rec.error })
          } catch (_) {}
        },
      )
    } catch (_) {
      // Backend unreachable or job id stale — clear the persisted key silently
      try { sessionStorage.removeItem(SESSION_JOB_KEY) } catch (_) {}
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
