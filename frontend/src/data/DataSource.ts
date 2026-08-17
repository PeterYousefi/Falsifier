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
    // Offline-mode response assembled from fixture
    return {
      role: 'assistant',
      content: `**Offline mode** — no API key configured. You asked: "${message}"\n\nThis response is assembled from committed fixture artifacts only.`,
      sources: [],
      guardian_verdict: {
        safe: true,
        risk_label: 'safe',
        model_used: 'heuristic',
        confidence: null,
      },
      offline_mode: true,
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
    if (!res.ok) throw new Error('POST /chat failed')
    return res.json()
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
