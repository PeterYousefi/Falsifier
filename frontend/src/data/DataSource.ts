/**
 * src/data/DataSource.ts
 * DataSource interface + two implementations.
 *
 * VITE_DATA_SOURCE=api  → ApiDataSource (live backend)
 * VITE_DATA_SOURCE=fixture (default) → FixtureDataSource (committed JSON)
 *
 * Switching is one env flag: set VITE_DATA_SOURCE=api in .env.local
 */

import type {
  JobRecord,
  DetectionReport,
  ProvenanceReport,
  StageEvent,
  ChatMessage,
  ChatFixture,
  TrainingFixture,
} from './types'

// ---------------------------------------------------------------------------
// DataSource interface
// ---------------------------------------------------------------------------

export interface SubmitJobParams {
  target_id: string
  mission: string
  author: string
  cadence: string
}

export interface DataSource {
  /** Submit a detection job. Returns job_id. */
  submitJob(params: SubmitJobParams): Promise<string>
  /** Get a job record by ID. */
  getJob(job_id: string): Promise<JobRecord>
  /** Stream SSE stage events for a running job. */
  streamJob(job_id: string, onEvent: (evt: StageEvent) => void, onDone: () => void): () => void
  /** Get the provenance report. */
  getProvenance(): Promise<ProvenanceReport>
  /** Send a chat message. */
  chat(job_id: string | null, message: string, history: { role: string; content: string }[]): Promise<ChatMessage>
  /** Load the initial fixture chat session. */
  getChatFixture(): Promise<ChatFixture>
  /** Load training fixture data. */
  getTrainingFixture(): Promise<TrainingFixture>
}

// ---------------------------------------------------------------------------
// FixtureDataSource — reads committed JSON, no backend required
// ---------------------------------------------------------------------------

import fixtureJob from '../fixtures/job.json'
import fixtureJobEB from '../fixtures/job_false_positive.json'
import fixtureProvenance from '../fixtures/provenance.json'
import fixtureEvents from '../fixtures/events.json'
import fixtureChat from '../fixtures/chat.json'
import fixtureTraining from '../fixtures/training.json'

// Maps normalised target IDs to their committed fixtures.
// Only targets with a committed fixture file are listed here.
const _FIXTURE_MAP: Record<string, unknown> = {
  'kic 11904151': fixtureJob,
  'kic11904151':  fixtureJob,
  'kepler-10':    fixtureJob,
  'kepler 10':    fixtureJob,
  'kic 6965293':  fixtureJobEB,
  'kic6965293':   fixtureJobEB,
}

function _jobForTarget(target_id: string): unknown {
  const key = target_id.trim().toLowerCase()
  return _FIXTURE_MAP[key] ?? fixtureJob
}

export class FixtureDataSource implements DataSource {
  async submitJob(params: SubmitJobParams): Promise<string> {
    // Simulate async submission
    await _delay(180)
    const job = _jobForTarget(params.target_id) as { job_id: string }
    return job.job_id
  }

  async getJob(job_id: string): Promise<JobRecord> {
    await _delay(80)
    // Allow lookup by job_id for the EB fixture as well
    if (job_id === (fixtureJobEB as any).job_id) {
      return fixtureJobEB as unknown as JobRecord
    }
    return fixtureJob as unknown as JobRecord
  }

  streamJob(
    _job_id: string,
    onEvent: (evt: StageEvent) => void,
    onDone: () => void,
  ): () => void {
    // Replay fixture events with realistic delays
    let cancelled = false
    const events = fixtureEvents as StageEvent[]
    let i = 0

    const replay = () => {
      if (cancelled || i >= events.length) {
        if (!cancelled) onDone()
        return
      }
      const evt = events[i++]
      onEvent(evt)
      const delay = evt.elapsed_seconds != null ? Math.min(evt.elapsed_seconds * 60, 900) : 120
      setTimeout(replay, delay)
    }

    // Start after a short initial delay
    setTimeout(replay, 200)
    return () => { cancelled = true }
  }

  async getProvenance(): Promise<ProvenanceReport> {
    await _delay(60)
    return fixtureProvenance as unknown as ProvenanceReport
  }

  async chat(
    _job_id: string | null,
    message: string,
    _history: { role: string; content: string }[],
  ): Promise<ChatMessage> {
    await _delay(600)
    return _offlineAnswer(message)
  }

  async getChatFixture(): Promise<ChatFixture> {
    return fixtureChat as unknown as ChatFixture
  }

  async getTrainingFixture(): Promise<TrainingFixture> {
    return fixtureTraining as unknown as TrainingFixture
  }
}

// ---------------------------------------------------------------------------
// ApiDataSource — calls live backend
// ---------------------------------------------------------------------------

export class ApiDataSource implements DataSource {
  private base: string

  constructor(base?: string) {
    // Prefer explicit argument; fall back to the Vite env var baked at build
    // time; then fall back to empty string (same-origin, for dev-server proxy).
    this.base = base
      ?? (typeof import.meta !== 'undefined' ? (import.meta as any).env?.VITE_API_BASE_URL ?? '' : '')
  }

  async submitJob(params: SubmitJobParams): Promise<string> {
    const res = await fetch(`${this.base}/jobs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    })
    if (!res.ok) throw new Error(`POST /jobs failed: ${res.status}`)
    const data = await res.json()
    return data.job_id
  }

  async getJob(job_id: string): Promise<JobRecord> {
    const res = await fetch(`${this.base}/jobs/${job_id}`)
    if (!res.ok) throw new Error(`GET /jobs/${job_id} failed: ${res.status}`)
    return res.json()
  }

  streamJob(
    job_id: string,
    onEvent: (evt: StageEvent) => void,
    onDone: () => void,
  ): () => void {
    let cancelled = false
    let pollTimer: ReturnType<typeof setTimeout> | null = null

    // --- Polling fallback ---------------------------------------------------
    // Code Engine's Knative ingress may buffer SSE responses and only flush
    // them in bulk when the connection closes, defeating incremental progress.
    // We use SSE as the primary path and automatically fall back to polling
    // GET /jobs/{id} on the first SSE error.
    const startPolling = () => {
      if (cancelled) return
      const POLL_MS = 3000
      const poll = async () => {
        if (cancelled) return
        try {
          const rec = await this.getJob(job_id)
          // Synthesise a stage event so the UI still shows progress
          const synth: StageEvent = {
            event: rec.status === 'done' ? 'job_done'
              : rec.status === 'failed' ? 'job_failed'
              : 'stage_start',
            stage: 'pipeline',
            status: rec.status === 'failed' ? 'error' : 'ok',
            detail: `[poll] job status: ${rec.status}`,
            artifact_path: null,
            elapsed_seconds: null,
          }
          onEvent(synth)
          if (rec.status === 'done' || rec.status === 'failed') {
            onDone()
            return
          }
        } catch (_) { /* network hiccup — retry */ }
        if (!cancelled) pollTimer = setTimeout(poll, POLL_MS)
      }
      pollTimer = setTimeout(poll, POLL_MS)
    }

    // --- SSE primary path ---------------------------------------------------
    let sseConnected = false
    let sse: EventSource | null = null
    try {
      sse = new EventSource(`${this.base}/jobs/${job_id}/stream`)
    } catch (_) {
      // EventSource constructor throws synchronously in some environments
      startPolling()
      return () => { cancelled = true; if (pollTimer) clearTimeout(pollTimer) }
    }

    sse.onopen = () => { sseConnected = true }

    sse.onmessage = (e) => {
      sseConnected = true
      try {
        const evt: StageEvent = JSON.parse(e.data)
        onEvent(evt)
        if (evt.event === 'job_done' || evt.event === 'job_failed') {
          sse!.close()
          onDone()
        }
      } catch (_) {}
    }

    sse.onerror = () => {
      sse!.close()
      // If we never received a message, the ingress is likely buffering.
      // Fall back to polling.
      if (!sseConnected) {
        startPolling()
      } else {
        // Connection dropped after at least one message — treat as done
        onDone()
      }
    }

    return () => {
      cancelled = true
      sse?.close()
      if (pollTimer) clearTimeout(pollTimer)
    }
  }

  async getProvenance(): Promise<ProvenanceReport> {
    const res = await fetch(`${this.base}/provenance`)
    if (!res.ok) throw new Error('GET /provenance failed')
    return res.json()
  }

  async chat(
    job_id: string | null,
    message: string,
    history: { role: string; content: string }[],
  ): Promise<ChatMessage> {
    const res = await fetch(`${this.base}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_id, message, history }),
    })
    if (!res.ok) throw new Error(`POST /chat failed: ${res.status}`)
    // The API returns { reply, tool_calls, sources, guardian_verdict, offline_mode }.
    // Map `reply` → `content` to match the ChatMessage contract.
    const data = await res.json()
    return {
      role: 'assistant',
      content: typeof data.reply === 'string' ? data.reply : '',
      tool_calls: data.tool_calls ?? [],
      sources: data.sources ?? [],
      guardian_verdict: data.guardian_verdict ?? null,
      offline_mode: data.offline_mode ?? false,
    }
  }

  async getChatFixture(): Promise<ChatFixture> {
    return fixtureChat as unknown as ChatFixture
  }

  async getTrainingFixture(): Promise<TrainingFixture> {
    return fixtureTraining as unknown as TrainingFixture
  }
}

// ---------------------------------------------------------------------------
// Factory — driven by VITE_DATA_SOURCE and VITE_API_BASE_URL env vars
//
// Switching rules (first match wins):
//   1. VITE_DATA_SOURCE=api         → ApiDataSource (live backend)
//   2. VITE_API_BASE_URL is set     → ApiDataSource (live backend)
//   3. otherwise                    → FixtureDataSource (committed JSON)
//
// This means a production Vercel deploy just needs VITE_API_BASE_URL set;
// no separate VITE_DATA_SOURCE=api is required.
// ---------------------------------------------------------------------------

const _env = typeof import.meta !== 'undefined' ? (import.meta as any).env ?? {} : {}
const _mode = _env.VITE_DATA_SOURCE ?? (_env.VITE_API_BASE_URL ? 'api' : 'fixture')

export const dataSource: DataSource =
  _mode === 'api' ? new ApiDataSource() : new FixtureDataSource()

// ---------------------------------------------------------------------------
// Re-export for use in store and screens that need a target-aware fixture job
// ---------------------------------------------------------------------------
export { _jobForTarget as getFixtureJobForTarget }

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

// ---------------------------------------------------------------------------
// Offline chat answers — assembled from committed fixture artifacts only.
//
// Every value cited below is traceable to frontend/src/fixtures/job.json
// and frontend/src/fixtures/chat.json. No numbers are invented.
// Source chips follow the same [source: tool(args)] convention as the live
// API, so the MessageBubble component renders them identically.
//
// Only prompts whose answers are fully derivable from the fixture are listed.
// Prompts that require a live pipeline run (e.g. "Refit at half the period")
// are not present — those buttons are removed from ChatPanel.tsx rather than
// returning a misleading stub.
// ---------------------------------------------------------------------------

type _OfflineEntry = {
  content: string
  sources: string[]
}

// Normalise a message for lookup: lower-case, collapse whitespace, strip punctuation.
function _normMsg(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9 ]/g, '').replace(/\s+/g, ' ').trim()
}

const _OFFLINE_ANSWERS: Array<{ match: string[]; entry: _OfflineEntry }> = [
  {
    // "Why was this classified as a candidate?"  (also the fixture preload)
    match: ['why was this classified as a candidate', 'why candidate', 'why classified'],
    entry: {
      content:
        'KIC-11904151-00 passed all seven vetting tests and was therefore dispositioned as a candidate.\n\n' +
        'Key results from the fixture artifact:\n' +
        '  • Odd/even depth mismatch: 0.018 (dimensionless) — within the 2σ threshold. ' +
        'Equal depths rule out an eclipsing binary. ' +
        '[source: get_vetting_results(KIC-11904151-00)]\n' +
        '  • Secondary eclipse test: PASS — no secondary event detected at phase 0.5. ' +
        '[source: get_vetting_results(KIC-11904151-00)]\n' +
        '  • Centroid displacement: 0.21 arcsec — below the 0.5 arcsec threshold. ' +
        'The brightness centroid did not shift during transit, ruling out a contaminating background star. ' +
        '[source: get_vetting_results(KIC-11904151-00)]\n' +
        '  • Classifier ranking score: unavailable — no trained model artifact is present. ' +
        'Disposition is set exclusively by the vetting tests. ' +
        '[source: get_vetting_results(KIC-11904151-00)]',
      sources: [
        '[source: get_vetting_results(KIC-11904151-00)]',
      ],
    },
  },
  {
    // "What does the stellar density test show?"
    match: ['what does the stellar density test show', 'stellar density', 'density test'],
    entry: {
      content:
        'The stellar density test compares the density implied by the transit geometry ' +
        '(duration, depth, period) with the spectroscopic value from Gaia DR3.\n\n' +
        'Fixture result for KIC-11904151-00:\n' +
        '  • Photometric stellar density reported in the fixture: 1.07 — but note this fixture ' +
        'was hand-authored and the unit label (rho_sun) may be incorrect. ' +
        'The published density of Kepler-10 is ~1.07 g/cm³ = ~0.76 ρ☉; ' +
        'the fixture mislabels g/cm³ as solar densities. ' +
        'Outcome shown is PASS, but the geometry does not close under either unit reading — ' +
        'this is a known fixture defect. ' +
        '[source: get_vetting_results(KIC-11904151-00)]\n\n' +
        'A large discrepancy between photometric and spectroscopic density would indicate ' +
        'that the transiting object is not in front of this star (e.g. a blended background EB). ' +
        'The stellar density check on a fixture cannot be trusted — it must run on real pipeline output.',
      sources: [
        '[source: get_vetting_results(KIC-11904151-00)]',
      ],
    },
  },
  {
    // "Could the data distinguish this from an eclipsing binary?"
    match: [
      'could the data distinguish this from an eclipsing binary',
      'distinguish from eclipsing binary',
      'eclipsing binary',
      'could data distinguish',
    ],
    entry: {
      content:
        'Yes — the fixture data passes three tests that are specifically designed to separate ' +
        'planetary transits from eclipsing binary (EB) signals:\n\n' +
        '  1. Odd/even depth test: the odd and even transit depths agree within 0.018 ' +
        '(dimensionless), well within the 2σ threshold. An EB would produce alternating ' +
        'deep and shallow dips. Outcome: PASS. ' +
        '[source: get_vetting_results(KIC-11904151-00)]\n\n' +
        '  2. Secondary eclipse test: no significant dimming was detected at phase 0.5 ' +
        '(half an orbit). A detached EB would show a secondary eclipse at this phase. Outcome: PASS. ' +
        '[source: get_vetting_results(KIC-11904151-00)]\n\n' +
        '  3. Transit shape test: the profile χ² ratio is 0.94 — consistent with a ' +
        'limb-darkened U-shaped transit rather than a V-shaped stellar eclipse. Outcome: PASS. ' +
        '[source: get_vetting_results(KIC-11904151-00)]\n\n' +
        'Taken together, these three tests establish that the fixture data is inconsistent with ' +
        'the most common EB false-positive scenarios. Note that these are fixture values — ' +
        'a live pipeline run is required to confirm the tests on real photometry.',
      sources: [
        '[source: get_vetting_results(KIC-11904151-00)]',
      ],
    },
  },
  {
    // "What would settle it?"
    match: ['what would settle it', 'settle it', 'how to confirm', 'how confirm'],
    entry: {
      content:
        'The vetting tests remove the main photometric false-positive scenarios, ' +
        'but photometry alone cannot confirm a planetary nature. What would settle it:\n\n' +
        '  1. Radial velocity follow-up: measuring the stellar reflex velocity at the ' +
        'orbital period (0.8375 d) [source: get_planet_params(KIC-11904151-00)] ' +
        'would determine the companion mass. A planetary mass (< 13 M_Jup) would confirm the candidate. ' +
        'This is the definitive test.\n\n' +
        '  2. High-resolution imaging: ruling out a blended background star within 1–2 arcsec. ' +
        'The centroid test shows 0.21 arcsec displacement — within threshold — but ' +
        'a background star closer than the Kepler PSF resolution would not shift the centroid. ' +
        '[source: get_vetting_results(KIC-11904151-00)]\n\n' +
        '  3. High-resolution spectroscopy: checking for a spectroscopic binary companion ' +
        'at the orbital period.\n\n' +
        'Note: this project is not a biosignature detector and makes no habitability claims. ' +
        'Confirmation of planetary nature is the appropriate next step for this candidate.',
      sources: [
        '[source: get_planet_params(KIC-11904151-00)]',
        '[source: get_vetting_results(KIC-11904151-00)]',
      ],
    },
  },
]

const _OFFLINE_FALLBACK: _OfflineEntry = {
  content:
    '**Offline mode** — no OpenAI API key is configured. ' +
    'Answers for the suggested prompts are assembled from the committed KIC 11904151 fixture artifact. ' +
    'For other questions, connect the pipeline backend (set OPENAI_API_KEY).',
  sources: [],
}

function _offlineAnswer(message: string): ChatMessage {
  const norm = _normMsg(message)
  const match = _OFFLINE_ANSWERS.find((a) => a.match.some((m) => norm.includes(_normMsg(m))))
  const entry = match?.entry ?? _OFFLINE_FALLBACK
  return {
    role: 'assistant',
    content: entry.content,
    sources: entry.sources,
    guardian_verdict: {
      safe: true,
      risk_label: 'safe',
      model_used: 'heuristic',
      confidence: null,
    },
    offline_mode: true,
  }
}
