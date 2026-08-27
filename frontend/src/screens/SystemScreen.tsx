/**
 * src/screens/SystemScreen.tsx
 * Landing page + investigation view.
 * Newspaper layout: headline question, plain prose, three-step strip,
 * prominent flagship card, search input, worked verdict preview.
 * Orbital 3D view as a bordered figure-inset with caption.
 * All visual properties driven from data layer — no scientific literals.
 */
import React, { useState, useEffect, useCallback } from 'react'
import { useStore } from '../store'
import { DispoChip, FixtureProvenanceBadge } from './CandidateDetail'
import OrbitalViewer from './OrbitalViewer'
import { isFixtureMode } from '../data/DataSource'
import { dispositionStandfirst } from '../data/outcomeConfig'
/** Canonical KIC target for the primary example button. */
const FIXTURE_TARGET_ID = 'KIC 11904151'

// ── Example targets across missions ─────────────────────────────────────
// Aliases that the user may type and that should resolve to the fixture target.
// Normalised with _normAlias before comparison (lower-case, collapse spaces).
const FIXTURE_TARGET_ALIASES = ['kepler-10', 'kepler 10', 'kic11904151', 'kic 11904151']
const FIXTURE_EB_ALIASES = ['kic6965293', 'kic 6965293']
function _normAlias(s: string): string {
  return s.toLowerCase().replace(/\s+/g, ' ').trim()
}
/** Canonical fixture display name shown to the user. */
const FIXTURE_DISPLAY_NAME = 'Kepler-10 (KIC 11904151)'

const EXAMPLE_TARGETS = [
  { id: 'KIC 11904151', mission: 'Kepler',  cadence: 'long',  label: 'Kepler-10 (KIC 11904151)', hasFixture: true, gloss: 'Kepler-10 (KIC 11904151) — a star in NASA\'s Kepler Input Catalogue, hosting the confirmed planet Kepler-10b' },
  // TOI-700 and TRAPPIST-1 have no TESS long-cadence (30-min) SPOC products.
  // Their SPOC data is short-cadence (2-min) only — cadence='long' returns zero
  // results and produces a misleading "try a different mission" error.
  { id: 'TIC 150428135', mission: 'TESS',   cadence: 'short', label: 'TOI-700 (TESS)',             hasFixture: false, gloss: 'TOI-700 — a star observed by NASA\'s TESS satellite, hosting planet candidates in its habitable zone. Short cadence (2 min).' },
  { id: 'TIC 200322593', mission: 'TESS',   cadence: 'short', label: 'TRAPPIST-1 (TESS)',          hasFixture: false, gloss: 'TRAPPIST-1 — an ultra-cool dwarf star hosting seven confirmed planets, observed by NASA\'s TESS satellite. Short cadence (2 min).' },
  { id: 'KIC 6965293',   mission: 'Kepler', cadence: 'long',  label: 'KIC 6965293 (Kepler EB)',    hasFixture: true, gloss: 'KIC 6965293 — a star in the Kepler Input Catalogue; its signal is an eclipsing binary (not a planet). Has committed fixture.' },
]

// ── Error banner — user-facing summary with collapsible raw detail ─────────
// Strips the Python exception class prefix ("MastFetchError: …") so only the
// human-readable portion is shown at top level.  The raw string is available
// behind a disclosure button.  No scientific values are rendered (Rule 1).
function ErrorBanner({ jobError }: { jobError: string }) {
  const [showDetail, setShowDetail] = useState(false)

  // Strip "ExceptionClass: " prefix and stop at first newline.
  const firstLine = jobError.split('\n')[0] ?? jobError
  const colonIdx = firstLine.indexOf(': ')
  const summary = (colonIdx > 0 ? firstLine.slice(colonIdx + 2) : firstLine).trim()
    || 'The pipeline run did not complete.'

  const hasDetail = jobError !== summary

  return (
    <div role="alert" aria-live="assertive" style={{
      marginTop: 8, padding: '8px 12px',
      background: 'var(--np-surface)',
      border: '1px solid var(--np-rule)',
      borderLeft: '3px solid var(--fail)',
    }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
        <strong style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--fail)', letterSpacing: '0.06em', flexShrink: 0 }}>
          PIPELINE ERROR
        </strong>
        <span style={{ fontFamily: 'var(--font-serif)', fontSize: 13, color: 'var(--np-muted)', lineHeight: 1.55 }}>
          {summary}
        </span>
      </div>
      {hasDetail && (
        <div style={{ marginTop: 4 }}>
          <button
            onClick={() => setShowDetail((v) => !v)}
            style={{
              fontFamily: 'var(--font-mono)', fontSize: 10,
              letterSpacing: '0.05em', color: 'var(--np-muted)',
              background: 'none', border: 'none', cursor: 'pointer',
              padding: '2px 0', textDecoration: 'underline',
            }}
            aria-expanded={showDetail}
            aria-controls="error-banner-detail"
          >
            {showDetail ? '▲ hide details' : '▼ show details'}
          </button>
          {showDetail && (
            <pre
              id="error-banner-detail"
              style={{
                fontFamily: 'var(--font-mono)', fontSize: 10,
                color: 'var(--np-muted)', background: 'var(--np-surface)',
                border: '1px solid var(--np-rule)', padding: '6px 8px',
                marginTop: 4, whiteSpace: 'pre-wrap', wordBreak: 'break-all',
                overflowX: 'auto', maxHeight: 160, overflowY: 'auto',
              }}
            >
              {jobError}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}

// ── Target search form ─────────────────────────────────────────────────────
function TargetForm({ defaultTarget, defaultMission, defaultCadence }: {
  defaultTarget?: string
  defaultMission?: string
  defaultCadence?: string
}) {
  const {
    targetId, setTargetId,
    mission, setMission,
    cadence, setCadence,
    isSubmitting, jobStatus, jobError, submitJob, progressStage, progressElapsed,
  } = useStore()
  const busy = isSubmitting || jobStatus === 'running' || jobStatus === 'queued'
  // D4: form controls are non-functional when the backend is not deployed.
  const backendAbsent = isFixtureMode

  useEffect(() => {
    if (defaultTarget) setTargetId(defaultTarget)
    if (defaultMission) setMission(defaultMission)
    if (defaultCadence) setCadence(defaultCadence)
  }, [defaultTarget, defaultMission, defaultCadence])

  const handleSubmit = useCallback((e: React.FormEvent) => {
    e.preventDefault()
    const id = targetId.trim()
    if (!id) return
    const norm = _normAlias(id)
    // Resolve common aliases (Kepler-10 → KIC 11904151, etc.) before submit
    const resolvedId =
      FIXTURE_TARGET_ALIASES.includes(norm)
        ? FIXTURE_TARGET_ID
        : FIXTURE_EB_ALIASES.includes(norm)
          ? 'KIC 6965293'
          : id
    submitJob(resolvedId, mission, cadence)
  }, [targetId, mission, cadence, submitJob])

  // Compose a human-readable progress label
  const progressLabel = busy && progressStage
    ? progressElapsed != null
      ? `${progressStage} — ${progressElapsed.toFixed(1)}s`
      : `${progressStage}…`
    : null

  return (
    <div>
      <form
        className="search-row"
        style={{ margin: '16px 0' }}
        onSubmit={handleSubmit}
      >
        <input
          value={targetId}
          onChange={(e) => setTargetId(e.target.value)}
          placeholder="e.g. KIC 11904151 · TIC 150428135 · TIC 200322593"
          disabled={busy || backendAbsent}
          aria-label="Target catalogue identifier"
          aria-disabled={backendAbsent || undefined}
          style={{ fontFamily: 'var(--font-mono)', fontSize: 13 }}
        />
        <select value={mission} onChange={(e) => setMission(e.target.value)} disabled={busy || backendAbsent} aria-label="Mission" aria-disabled={backendAbsent || undefined}>
          <option>Kepler</option>
          <option>K2</option>
          <option>TESS</option>
        </select>
        <select value={cadence} onChange={(e) => setCadence(e.target.value)} disabled={busy || backendAbsent} aria-label="Cadence" aria-disabled={backendAbsent || undefined}>
          <option value="long">long cadence</option>
          <option value="short">short cadence</option>
        </select>
        <button type="submit" className="btn-primary" disabled={busy || backendAbsent || !targetId.trim()}>
          {busy
            ? <><span className="spinner" aria-label="Running" /> {progressLabel ?? 'Running…'}</>
            : 'Investigate →'
          }
        </button>
      </form>

      {/* D4: degraded-backend notice — primary instruction for fixture-only deployment */}
      {backendAbsent && (
        <p
          role="status"
          aria-live="polite"
          style={{
            marginTop: 6,
            fontFamily: 'var(--font-serif)',
            fontSize: '0.95rem',
            color: 'var(--np-text)',
            lineHeight: 1.55,
          }}
        >
          Live runs require the local pipeline —{' '}
          <a
            href="https://github.com/PeterYousefi/Falsifier"
            target="_blank"
            rel="noreferrer"
            style={{ color: 'var(--rust)', textDecoration: 'underline' }}
          >
            clone the repo
          </a>
          {' '}to investigate any target.
        </p>
      )}

      {/* Live progress indicator */}
      {busy && progressStage && (
        <div aria-live="polite" style={{
          marginTop: 4, padding: '6px 12px',
          background: 'var(--np-surface)',
          border: '1px solid var(--np-rule)',
          fontFamily: 'var(--font-mono)', fontSize: 12,
          color: 'var(--np-muted)', letterSpacing: '0.04em',
        }}>
          <span style={{ color: 'var(--rust)' }}>●</span>
          {' '}{progressStage}{progressElapsed != null ? ` ✓ ${progressElapsed.toFixed(1)}s` : '…'}
        </div>
      )}

      {/* Error display — user-facing summary + collapsible raw detail */}
      {jobStatus === 'failed' && jobError && (
        <ErrorBanner jobError={jobError} />
      )}
    </div>
  )
}

// ── Verdict preview (worked example from fixture) ─────────────────────────
function VerdictPreview() {
  const { report, setActiveScreen } = useStore()
  if (!report) return null

  const vet = report.vet?.[0]
  if (!vet) return null

  // D1: headline and standfirst derived from disposition via outcomeConfig —
  // no inline string comparison with disposition value.
  const headline = vet.disposition === 'candidate'
    ? `${report.target_id} — candidate planet survives all ${vet.test_results?.length ?? 0} challenges`
    : vet.disposition === 'false_positive'
      ? `${report.target_id} — rejected: ${vet.triggering_reason ?? 'see vetting report'}`
      : `${report.target_id} — ${vet.disposition.replace(/_/g, ' ')}`

  const standfirst = dispositionStandfirst(vet)

  return (
    <div className="verdict-card">
      <FixtureProvenanceBadge report={report} />
      <div className="section-label">Latest result — {report.target_id}</div>
      <h2 style={{ fontFamily: 'var(--font-head)', fontSize: 20, marginBottom: 8 }}>{headline}</h2>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
        <DispoChip disposition={vet.disposition} />
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--np-muted)' }}>
          Period: {vet.period_days != null ? vet.period_days.toFixed(4) + ' d' : '—'}
          {' · '}
          Depth: {vet.depth_ppm != null ? vet.depth_ppm.toFixed(0) + ' ppm' : '—'}
        </span>
      </div>
      <p style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: 'var(--np-muted)', lineHeight: 1.6, marginBottom: 12 }}>
        {standfirst}
      </p>
      <button
        className="btn-secondary"
        onClick={() => setActiveScreen('detail')}
        aria-label="View full report"
      >
        Read the full report →
      </button>
    </div>
  )
}

// ── Landing page content ──────────────────────────────────────────────────
function LandingContent() {
  const { setTargetId, setMission, setCadence, submitJob, setActiveScreen, jobStatus, isSubmitting } = useStore()
  const [tooltipIdx, setTooltipIdx] = useState<number | null>(null)

  const runExample = () => {
    const ex = EXAMPLE_TARGETS[0]
    setTargetId(ex.id)
    setMission(ex.mission)
    setCadence(ex.cadence)
    submitJob(ex.id, ex.mission, ex.cadence)
    setActiveScreen('detail')
  }

  const busy = isSubmitting || jobStatus === 'running' || jobStatus === 'queued'

  return (
    <div className="page-body">
      {/* Article dateline + headline */}
      <hr className="rule-double" />
      <div className="article-dateline" style={{ marginTop: 16 }}>
        NO. 001 · KEPLER · K2 · TESS · LONG CADENCE
      </div>
      <h1 style={{ textAlign: 'center', fontSize: 'clamp(28px, 5vw, 48px)', marginBottom: 8 }}>
        Is that a planet, or something pretending to be one?
      </h1>
      <p className="standfirst" style={{ textAlign: 'center', borderLeft: 'none', paddingLeft: 0 }}>
        Seven automated challenges. Every false positive fingerprint tested in sequence.
        Nothing is hidden.
      </p>
      <hr className="rule-hair" />

      {/* Two-column opening prose with drop cap */}
      <div className="article-columns prose-drop" style={{ marginTop: 20 }}>
        <p>
          Every so often, a star dims by a tiny fraction — perhaps one part in ten thousand —
          and then brightens again. It looks exactly like something passing in front of it.
          It might be a planet. It might also be a companion star whose orbit carries it into
          our line of sight, or a systematic error baked into the spacecraft's sensors, or
          scattered light from a brighter neighbour. The signal alone cannot tell you which.
        </p>
        <p>
          <em>Falsifier</em> runs the dimming event through seven independent challenges,
          each designed to expose a specific kind of impersonator: eclipsing-binary dips
          come in pairs of unequal depth; contaminating stars shift the brightness centroid;
          instrumental artefacts align with spacecraft roll manoeuvres. A real planet
          fails none of these tests. Anything that fails even one is flagged — the harder
          the challenge, the more confident the rejection.
        </p>
        <p>
          The tool covers observations from NASA's Kepler telescope
          (a space observatory that watched a fixed field of 150,000 stars for four years),
          its second mission K2, and the newer TESS satellite (which scans the entire sky
          in 27-day segments). You can investigate a catalogue target by identifier or
          upload your own light curve.
        </p>
        <p>
          A calibrated ranking score is computed alongside the vetting result,
          but that number is a <em>sorting signal only</em> — it is not a detection claim.
          Disposition is determined exclusively by the seven vetting tests.
          This tool is not a biosignature detector; no exoplanet biosignature has ever been confirmed.
        </p>
      </div>

      {/* I. THE SEVEN CHALLENGES */}
      <hr className="rule-hair" style={{ marginTop: 24 }} />
      <div className="section-label" style={{ marginTop: 20, textAlign: 'center' }}>I. How it works</div>
      <div className="how-strip">
        <div className="how-step">
          <div className="how-step-num">I</div>
          <div className="how-step-title">Fetch</div>
          <div className="how-step-body">
            Light curve data are pulled from the Kepler or TESS archive by catalogue ID,
            detrended to remove stellar variability, and segmented for analysis.
          </div>
        </div>
        <div className="how-step">
          <div className="how-step-num">II</div>
          <div className="how-step-title">Search</div>
          <div className="how-step-body">
            The Transit Least Squares algorithm folds the detrended curve at all plausible
            periods to identify periodic dimming events above a signal-to-noise threshold.
          </div>
        </div>
        <div className="how-step">
          <div className="how-step-num">III</div>
          <div className="how-step-title">Challenge</div>
          <div className="how-step-body">
            Seven automated tests probe each event for the fingerprints of false positives.
            Every result is reported with its measured metric and threshold — nothing is hidden.
          </div>
        </div>
      </div>

      {/* II. FLAGSHIP EXAMPLE — KIC 11904151 */}
      <hr className="rule-double" style={{ marginTop: 28 }} />
      <div className="section-label" style={{ marginBottom: 10 }}>II. Worked example</div>

      {/* Single fixture-mode disclosure — lives here and only here */}
      {isFixtureMode && (
        <div style={{
          background: 'var(--np-surface)',
          border: '1px solid var(--np-border)',
          padding: '10px 14px',
          marginBottom: 14,
          fontFamily: 'var(--font-serif)',
          fontSize: 13,
          color: 'var(--np-muted)',
          lineHeight: 1.6,
        }} role="note">
          This example shows real, committed pipeline output for{' '}
          <span style={{ fontFamily: 'var(--font-mono)' }}>KIC 11904151</span> (Kepler-10).
          Enter your own target ID and it will run against the live pipeline if you clone
          and run this locally —{' '}
          <a
            href="https://github.com/PeterYousefi/Falsifier#readme"
            target="_blank"
            rel="noreferrer"
            style={{ color: 'var(--rust)', textDecoration: 'underline' }}
          >
            see README
          </a>
          {' '}and{' '}
          <a
            href="https://falsifier.vercel.app"
            target="_blank"
            rel="noreferrer"
            style={{ color: 'var(--rust)', textDecoration: 'underline' }}
          >
            live demo
          </a>.
          TOI-700 and TRAPPIST-1 require the local pipeline (no fixture exists for them).
        </div>
      )}

      {/* Flagship card — KIC 11904151 */}
      <div style={{
        border: '2px solid var(--np-rule)',
        background: 'var(--np-surface)',
        padding: '18px 20px',
        marginBottom: 20,
      }}>
        <div style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          color: 'var(--np-muted)',
          letterSpacing: '0.08em',
          marginBottom: 6,
        }}>
          FEATURED TARGET · KEPLER · FULL PIPELINE RECORD
        </div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap', marginBottom: 6 }}>
          <span style={{ fontFamily: 'var(--font-head)', fontSize: 22, fontWeight: 700, color: 'var(--np-text)' }}>
            Kepler-10 (KIC 11904151)
          </span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--np-muted)' }}>
            Kepler · long cadence · confirmed host star
          </span>
        </div>
        <p style={{
          fontFamily: 'var(--font-serif)',
          fontSize: 13,
          color: 'var(--np-muted)',
          lineHeight: 1.6,
          marginBottom: 14,
          maxWidth: 560,
        }}>
          A star in NASA's Kepler Input Catalogue hosting the confirmed planet Kepler-10b.
          This is the fully-worked example: ingest, detrend, TLS search, and seven vetting tests,
          all from the committed pipeline artifact.
        </p>
        <button
          className="btn-primary"
          onClick={runExample}
          disabled={busy}
          aria-label={`Load the Kepler-10 (KIC 11904151) worked example`}
          style={{ fontSize: 15, padding: '11px 24px' }}
        >
          {busy
            ? <><span className="spinner" /> Loading…</>
            : 'Load worked example: Kepler-10 →'
          }
        </button>
      </div>

      {/* III. BEGIN — custom target */}
      <hr className="rule-hair" style={{ marginTop: 4 }} />
      <div className="section-label" style={{ marginBottom: 10 }}>III. Investigate any target</div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 14, margin: '0 0 24px' }}>
        <div>
          <div style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: 'var(--np-muted)', marginBottom: 8 }}>
            Enter any Kepler / TESS catalogue identifier:
          </div>
          <TargetForm />
        </div>

        <div>
          <div className="section-label" style={{ marginBottom: 8 }}>Other example targets</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {EXAMPLE_TARGETS.filter((t) => t.id !== FIXTURE_TARGET_ID).map((t, _i) => {
              // Map back to original index for tooltip tracking
              const i = EXAMPLE_TARGETS.indexOf(t)
              // In fixture mode: chips without a committed fixture file cannot
              // run — disable them so users aren't left with a spinner.
              const noFixture = isFixtureMode && !t.hasFixture
              const chipDisabled = busy || noFixture

              if (noFixture) {
                return (
                  <div key={t.id} style={{ position: 'relative', display: 'inline-block' }}>
                    <span
                      style={{
                        display: 'inline-block',
                        border: '1px dashed var(--np-border)',
                        color: 'var(--np-faint)',
                        fontFamily: 'var(--font-mono)',
                        fontSize: 11,
                        padding: '4px 10px',
                        cursor: 'default',
                      }}
                      onMouseEnter={() => setTooltipIdx(i)}
                      onMouseLeave={() => setTooltipIdx(null)}
                      aria-describedby={`chip-tip-${i}`}
                    >
                      {t.label}
                      <span style={{
                        marginLeft: 6,
                        fontFamily: 'var(--font-serif)',
                        fontStyle: 'italic',
                        fontSize: 10,
                        color: 'var(--np-faint)',
                      }}>local only</span>
                    </span>
                    {tooltipIdx === i && (
                      <div
                        id={`chip-tip-${i}`}
                        role="tooltip"
                        style={{
                          position: 'absolute', top: '100%', left: 0, zIndex: 50,
                          background: 'var(--np-text)', color: 'var(--np-paper)',
                          fontFamily: 'var(--font-serif)', fontSize: 12,
                          padding: '6px 10px', borderRadius: 'var(--r)',
                          whiteSpace: 'normal', maxWidth: 280, lineHeight: 1.5,
                          marginTop: 4, pointerEvents: 'none',
                        }}
                      >
                        {t.gloss}
                        {' Requires the local pipeline — clone the repo to run this target.'}
                      </div>
                    )}
                  </div>
                )
              }

              return (
                <div key={t.id} style={{ position: 'relative', display: 'inline-block' }}>
                  <button
                    className="target-chip"
                    onClick={() => {
                      setTargetId(t.id)
                      setMission(t.mission)
                      setCadence(t.cadence)
                      submitJob(t.id, t.mission, t.cadence)
                    }}
                    onMouseEnter={() => setTooltipIdx(i)}
                    onMouseLeave={() => setTooltipIdx(null)}
                    onFocus={() => setTooltipIdx(i)}
                    onBlur={() => setTooltipIdx(null)}
                    aria-describedby={`chip-tip-${i}`}
                    disabled={chipDisabled}
                  >
                    {t.label}
                  </button>
                  {tooltipIdx === i && (
                    <div
                      id={`chip-tip-${i}`}
                      role="tooltip"
                      style={{
                        position: 'absolute', top: '100%', left: 0, zIndex: 50,
                        background: 'var(--np-text)', color: 'var(--np-paper)',
                        fontFamily: 'var(--font-serif)', fontSize: 12,
                        padding: '6px 10px', borderRadius: 'var(--r)',
                        whiteSpace: 'normal', maxWidth: 280, lineHeight: 1.5,
                        marginTop: 4, pointerEvents: 'none',
                      }}
                    >
                      {t.gloss}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
          <div style={{ marginTop: 12 }}>
            <a href="#upload" onClick={(e) => { e.preventDefault(); useStore.getState().setActiveScreen('upload') }}
               style={{ fontFamily: 'var(--font-serif)', fontSize: 14 }}>
              Have your own observations? Upload a light curve →
            </a>
          </div>
        </div>
      </div>

      {/* Worked verdict preview */}
      <VerdictPreview />
    </div>
  )
}

// ── Orbital figure (used after running a job) ─────────────────────────────
function OrbitalFigure() {
  const { report, jobStatus, jobError, progressStage, targetId, jobId, selectedTceId } = useStore()

  // While a job is actively running (or has failed without a report yet),
  // render the viewer with no vet data so it shows the RUNNING / FAILED state.
  // Once the report arrives the vet data populates the scene normally.
  const isInFlight = (jobStatus === 'running' || jobStatus === 'queued') && !report
  const isFailedNoReport = jobStatus === 'failed' && !report

  if (!report && !isInFlight && !isFailedNoReport) return null

  const vets = report?.vet ?? []
  const activeVet = vets.find((v) => v.tce_id === selectedTceId) ?? vets[0] ?? null
  const displayTarget = report?.target_id ?? targetId

  return (
    <div className="page-body" style={{ paddingTop: 0 }}>
    <hr className="rule-hair" />
    <div className="section-label" style={{ marginBottom: 12 }}>
      {displayTarget ? `Orbital system — ${displayTarget}` : 'Orbital system'}
      {jobStatus && jobStatus !== 'done' && (
        <span className={`job-status-badge ${jobStatus}`} style={{ marginLeft: 10 }}>{jobStatus}</span>
      )}
    </div>
      <OrbitalViewer
        vet={activeVet}
        stellarParams={report?.stellar_params}
        jobId={report?.job_id ?? jobId}
        isFixture={!!report?.fixture_provenance}
        jobStatus={jobStatus}
        progressStage={progressStage}
        jobError={jobError}
      />
    </div>
  )
}

// ── Main export ───────────────────────────────────────────────────────────
export default function SystemScreen() {
  return (
    <div className="screen" style={{ overflowY: 'auto' }}>
      <LandingContent />
      <OrbitalFigure />
    </div>
  )
}
