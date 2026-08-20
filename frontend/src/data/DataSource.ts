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
import fixtureProvenance from '../fixtures/provenance.json'
import fixtureEvents from '../fixtures/events.json'
import fixtureChat from '../fixtures/chat.json'
import fixtureTraining from '../fixtures/training.json'

export class FixtureDataSource implements DataSource {
  async submitJob(_params: SubmitJobParams): Promise<string> {
    // Simulate async submission
    await _delay(180)
    return fixtureJob.job_id
  }

  async getJob(_job_id: string): Promise<JobRecord> {
    await _delay(80)
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

  constructor(base = '') {
    this.base = base
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
    const sse = new EventSource(`${this.base}/jobs/${job_id}/stream`)
    sse.onmessage = (e) => {
      try {
        const evt: StageEvent = JSON.parse(e.data)
        onEvent(evt)
        if (evt.event === 'job_done' || evt.event === 'job_failed') {
          sse.close()
          onDone()
        }
      } catch (_) {}
    }
    sse.onerror = () => { sse.close(); onDone() }
    return () => sse.close()
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
// Factory — driven by VITE_DATA_SOURCE env var
// ---------------------------------------------------------------------------

const _mode = typeof import.meta !== 'undefined'
  ? (import.meta as any).env?.VITE_DATA_SOURCE ?? 'fixture'
  : 'fixture'

export const dataSource: DataSource =
  _mode === 'api' ? new ApiDataSource() : new FixtureDataSource()

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
        '[source: get_vetting_results(fixture-job-001, KIC-11904151-00)]\n' +
        '  • Secondary eclipse test: PASS — no secondary event detected at phase 0.5. ' +
        '[source: get_vetting_results(fixture-job-001, KIC-11904151-00)]\n' +
        '  • Centroid displacement: 0.21 arcsec — below the 0.5 arcsec threshold. ' +
        'The brightness centroid did not shift during transit, ruling out a contaminating background star. ' +
        '[source: get_vetting_results(fixture-job-001, KIC-11904151-00)]\n' +
        '  • Classifier ranking score: 81.2% ± 4.1%. This is a ranking signal only — ' +
        'it does not determine disposition. Disposition is set exclusively by the vetting tests. ' +
        '[source: get_planet_params(fixture-job-001, KIC-11904151-00)]',
      sources: [
        '[source: get_vetting_results(fixture-job-001, KIC-11904151-00)]',
        '[source: get_planet_params(fixture-job-001, KIC-11904151-00)]',
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
        '  • Photometric stellar density: 1.07 ρ☉ — consistent with the Gaia DR3 ' +
        'spectroscopic estimate, confirming the transit geometry is self-consistent. ' +
        'Outcome: PASS. ' +
        '[source: get_vetting_results(fixture-job-001, KIC-11904151-00)]\n\n' +
        'A large discrepancy between photometric and spectroscopic density would indicate ' +
        'that the transiting object is not in front of this star (e.g. a blended background EB). ' +
        'No such discrepancy is present here.',
      sources: [
        '[source: get_vetting_results(fixture-job-001, KIC-11904151-00)]',
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
        '[source: get_vetting_results(fixture-job-001, KIC-11904151-00)]\n\n' +
        '  2. Secondary eclipse test: no significant dimming was detected at phase 0.5 ' +
        '(half an orbit). A detached EB would show a secondary eclipse at this phase. Outcome: PASS. ' +
        '[source: get_vetting_results(fixture-job-001, KIC-11904151-00)]\n\n' +
        '  3. Transit shape test: the profile χ² ratio is 0.94 — consistent with a ' +
        'limb-darkened planetary transit rather than a V-shaped stellar eclipse. Outcome: PASS. ' +
        '[source: get_vetting_results(fixture-job-001, KIC-11904151-00)]\n\n' +
        'Taken together, these three tests establish that the data is inconsistent with ' +
        'the most common EB false-positive scenarios. The data can distinguish this signal ' +
        'from the major EB configurations given the available photometry.',
      sources: [
        '[source: get_vetting_results(fixture-job-001, KIC-11904151-00)]',
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
        'orbital period (0.8375 d) [source: get_planet_params(fixture-job-001, KIC-11904151-00)] ' +
        'would determine the companion mass. A planetary mass (< 13 M_Jup) would confirm the candidate. ' +
        'This is the definitive test.\n\n' +
        '  2. High-resolution imaging: ruling out a blended background star within 1–2 arcsec. ' +
        'The centroid test shows 0.21 arcsec displacement — within threshold — but ' +
        'a background star closer than the Kepler PSF resolution would not shift the centroid. ' +
        '[source: get_vetting_results(fixture-job-001, KIC-11904151-00)]\n\n' +
        '  3. High-resolution spectroscopy: checking for a spectroscopic binary companion ' +
        'at the orbital period.\n\n' +
        'Note: this project is not a biosignature detector and makes no habitability claims. ' +
        'Confirmation of planetary nature is the appropriate next step for this candidate.',
      sources: [
        '[source: get_planet_params(fixture-job-001, KIC-11904151-00)]',
        '[source: get_vetting_results(fixture-job-001, KIC-11904151-00)]',
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
