/**
 * src/data/DataSource.test.ts
 * Tests for FixtureDataSource and NoFixtureError.
 *
 * Covers:
 *   1. submitJob rejects with NoFixtureError for a target with no fixture
 *   2. The thrown message names the requested target identifier
 *   3. submitJob for KIC 11904151 and its aliases resolves to the Kepler-10 job_id
 *   4. submitJob for KIC 6965293 resolves to the EB fixture job_id (not Kepler-10)
 *   5. getJob with an unrecognised job_id rejects
 *   6. Whitespace and case variants resolve to the same fixture
 *
 * Also includes a store-level test: a failed submitJob leaves report === null
 * and sets jobStatus === 'failed' with a non-empty jobError.
 */

import { describe, it, expect, beforeEach } from 'vitest'
import { FixtureDataSource, NoFixtureError } from './DataSource'
import { useStore } from '../store'

// Fixture job_ids taken from committed artifacts (no literals invented here;
// these are the same values the fixture JSON files declare).
const KEPLER10_JOB_ID = 'fixture-job-001'
const EB_JOB_ID       = 'fixture-job-eb-001'

const BASE_PARAMS = { mission: 'Kepler', cadence: 'long' }

describe('FixtureDataSource.submitJob', () => {
  const ds = new FixtureDataSource()

  // ── 1 & 2: unknown target throws NoFixtureError with the target name ──────
  it('rejects with NoFixtureError for TIC 150428135', async () => {
    await expect(
      ds.submitJob({ target_id: 'TIC 150428135', ...BASE_PARAMS }),
    ).rejects.toThrow(NoFixtureError)
  })

  it('error message contains the requested identifier', async () => {
    const err = await ds
      .submitJob({ target_id: 'TIC 150428135', ...BASE_PARAMS })
      .catch((e) => e)
    expect(err).toBeInstanceOf(NoFixtureError)
    expect(err.message).toContain('TIC 150428135')
  })

  // ── 3: KIC 11904151 and all its aliases → Kepler-10 fixture ──────────────
  const kepler10Aliases = [
    'KIC 11904151',
    'kic 11904151',
    'KIC11904151',
    'kic11904151',
    'kepler-10',
    'Kepler-10',
    'kepler 10',
    'Kepler 10',
  ]

  for (const alias of kepler10Aliases) {
    it(`"${alias}" resolves to Kepler-10 fixture job_id`, async () => {
      const jobId = await ds.submitJob({ target_id: alias, ...BASE_PARAMS })
      expect(jobId).toBe(KEPLER10_JOB_ID)
    })
  }

  // ── 4: KIC 6965293 → EB fixture, NOT the Kepler-10 fixture ──────────────
  it('KIC 6965293 resolves to the EB fixture job_id', async () => {
    const jobId = await ds.submitJob({ target_id: 'KIC 6965293', ...BASE_PARAMS })
    expect(jobId).toBe(EB_JOB_ID)
  })

  it('KIC 6965293 job_id differs from Kepler-10 job_id (regression guard)', async () => {
    const ebId     = await ds.submitJob({ target_id: 'KIC 6965293',  ...BASE_PARAMS })
    const keplerId = await ds.submitJob({ target_id: 'KIC 11904151', ...BASE_PARAMS })
    expect(ebId).not.toBe(keplerId)
  })

  // ── 6: whitespace and case variants resolve consistently ─────────────────
  it('"kic  11904151" (double space) resolves to Kepler-10 fixture', async () => {
    const jobId = await ds.submitJob({ target_id: 'kic  11904151', ...BASE_PARAMS })
    expect(jobId).toBe(KEPLER10_JOB_ID)
  })

  it('"KIC 11904151 " (trailing space) resolves to Kepler-10 fixture', async () => {
    const jobId = await ds.submitJob({ target_id: 'KIC 11904151 ', ...BASE_PARAMS })
    expect(jobId).toBe(KEPLER10_JOB_ID)
  })
})

describe('FixtureDataSource.getJob', () => {
  const ds = new FixtureDataSource()

  // ── 5: unrecognised job_id rejects ────────────────────────────────────────
  it('rejects for an unrecognised job_id', async () => {
    await expect(
      ds.getJob('completely-unknown-job-xyz'),
    ).rejects.toThrow()
  })

  it('resolves the Kepler-10 fixture by its job_id', async () => {
    const record = await ds.getJob(KEPLER10_JOB_ID)
    expect((record as any).job_id).toBe(KEPLER10_JOB_ID)
  })

  it('resolves the EB fixture by its job_id', async () => {
    const record = await ds.getJob(EB_JOB_ID)
    expect((record as any).job_id).toBe(EB_JOB_ID)
  })
})

// ---------------------------------------------------------------------------
// Store-level test: failed submitJob must null report and set failed status
// ---------------------------------------------------------------------------

describe('store.submitJob failure path', () => {
  beforeEach(() => {
    // Reset store to a clean state before each test
    useStore.setState({
      isSubmitting: false,
      jobId: null,
      jobStatus: null,
      report: null,
      jobError: null,
      stageEvents: [],
      progressStage: null,
      progressElapsed: null,
    })
  })

  it('sets report to null, jobStatus to "failed", and jobError to non-empty string', async () => {
    const { submitJob } = useStore.getState()
    // TIC 150428135 has no fixture → NoFixtureError → store catches and sets failed
    await submitJob('TIC 150428135', 'TESS', 'long')
    const state = useStore.getState()
    expect(state.report).toBeNull()
    expect(state.jobStatus).toBe('failed')
    expect(typeof state.jobError).toBe('string')
    expect(state.jobError).toBeTruthy()
  })

  it('error message in the store names the target identifier', async () => {
    const { submitJob } = useStore.getState()
    await submitJob('TIC 150428135', 'TESS', 'long')
    const { jobError } = useStore.getState()
    expect(jobError).toContain('TIC 150428135')
  })
})
