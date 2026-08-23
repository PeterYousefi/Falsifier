/**
 * src/screens/SystemScreen.tsx
 * Landing page + investigation view.
 * Newspaper layout: headline question, plain prose, three-step strip,
 * prominent example button, search input, worked verdict preview.
 * Orbital 3D view as a bordered figure-inset with caption.
 * All visual properties driven from data layer — no scientific literals.
 */
import React, { useState, useEffect, useCallback } from 'react'
import { useStore } from '../store'
import { DispoChip } from './CandidateDetail'
import OrbitalViewer from './OrbitalViewer'
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
  { id: 'TIC 150428135', mission: 'TESS',   cadence: 'long',  label: 'TOI-700 (TESS)',             hasFixture: false, gloss: 'TOI-700 — a star observed by NASA\'s TESS satellite, hosting planet candidates in its habitable zone' },
  { id: 'TIC 200322593', mission: 'TESS',   cadence: 'long',  label: 'TRAPPIST-1 (TESS)',          hasFixture: false, gloss: 'TRAPPIST-1 — an ultra-cool dwarf star hosting seven confirmed planets, observed by NASA\'s TESS satellite' },
  { id: 'KIC 6965293',   mission: 'Kepler', cadence: 'long',  label: 'KIC 6965293 (Kepler EB)',    hasFixture: true, gloss: 'KIC 6965293 — a star in the Kepler Input Catalogue; its signal is an eclipsing binary (not a planet). Has committed fixture.' },
]

// ── Target search form ─────────────────────────────────────────────────────
function TargetForm({ defaultTarget, defaultMission, defaultCadence }: {
  defaultTarget?: string
  defaultMission?: string
  defaultCadence?: string
}) {
  const { targetId, setTargetId, isSubmitting, jobStatus, jobError, submitJob, progressStage, progressElapsed } = useStore()
  const [mission, setMission] = useState(defaultMission ?? 'Kepler')
  const [cadence, setCadence] = useState(defaultCadence ?? 'long')
  const busy = isSubmitting || jobStatus === 'running' || jobStatus === 'queued'

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
          disabled={busy}
          aria-label="Target catalogue identifier"
          style={{ fontFamily: 'var(--font-mono)', fontSize: 13 }}
        />
        <select value={mission} onChange={(e) => setMission(e.target.value)} disabled={busy} aria-label="Mission">
          <option>Kepler</option>
          <option>K2</option>
          <option>TESS</option>
        </select>
        <select value={cadence} onChange={(e) => setCadence(e.target.value)} disabled={busy} aria-label="Cadence">
          <option value="long">long cadence</option>
          <option value="short">short cadence</option>
        </select>
        <button type="submit" className="btn-primary" disabled={busy || !targetId.trim()}>
          {busy
            ? <><span className="spinner" aria-label="Running" /> {progressLabel ?? 'Running…'}</>
            : 'Investigate →'
          }
        </button>
      </form>

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

      {/* Error display — surfaces ingest / network errors immediately */}
      {jobStatus === 'failed' && jobError && (
        <div role="alert" aria-live="assertive" style={{
          marginTop: 8, padding: '8px 12px',
          background: 'var(--np-surface)',
          border: '1px solid var(--np-rule)',
          borderLeft: '3px solid var(--fail)',
          fontFamily: 'var(--font-serif)', fontSize: 13,
          color: 'var(--np-muted)', lineHeight: 1.55,
        }}>
          <strong style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--fail)', letterSpacing: '0.06em' }}>
            PIPELINE ERROR
          </strong>
          {' '}{jobError}
        </div>
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

  const allPass = vet.test_results?.every((t) => t.outcome === 'PASS')
  const headline = vet.disposition === 'candidate'
    ? `${report.target_id} — candidate planet survives all ${vet.test_results?.length ?? 0} challenges`
    : vet.disposition === 'false_positive'
      ? `${report.target_id} — rejected: ${vet.triggering_reason ?? 'see vetting report'}`
      : `${report.target_id} — ${vet.disposition.replace(/_/g, ' ')}`

  return (
    <div className="verdict-card">
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
        {allPass
          ? 'Every automated challenge returned negative: dip depths match across odd and even events, no secondary eclipse detected, the brightness centroid stays fixed, and the transit profile matches a limb-darkened planet. The stellar density inferred from transit geometry is consistent with the spectroscopic measurement.'
          : `One or more automated challenges raised a flag. The triggering test was ${vet.triggering_test ?? 'unknown'}.`
        }
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
  const { setTargetId, submitJob, setActiveScreen, jobStatus, isSubmitting } = useStore()
  const [tooltipIdx, setTooltipIdx] = useState<number | null>(null)

  const runExample = () => {
    const ex = EXAMPLE_TARGETS[0]
    setTargetId(ex.id)
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

      {/* III. BEGIN */}
      <hr className="rule-double" style={{ marginTop: 28 }} />
      <div className="section-label" style={{ marginBottom: 14 }}>III. Begin</div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 14, margin: '0 0 24px' }}>
        <div>
          <button
            className="btn-primary"
            onClick={runExample}
            disabled={busy}
            aria-label={`Investigate ${FIXTURE_DISPLAY_NAME}`}
            style={{ fontSize: 16, padding: '13px 28px' }}
          >
            {busy
              ? <><span className="spinner" /> Running…</>
              : `Investigate ${FIXTURE_DISPLAY_NAME} →`
            }
          </button>
          <span style={{ fontFamily: 'var(--font-serif)', fontSize: 13, color: 'var(--np-muted)', marginLeft: 14 }}>
            Kepler-10b — a confirmed hot rocky planet. Every challenge should pass.
          </span>
        </div>

        <div>
          <div style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: 'var(--np-muted)', marginBottom: 8 }}>
            Or enter any Kepler / TESS catalogue identifier:
          </div>
          <TargetForm />
        </div>

        <div>
          <div className="section-label" style={{ marginBottom: 8 }}>Example targets</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {EXAMPLE_TARGETS.map((t, i) => (
              <div key={t.id} style={{ position: 'relative', display: 'inline-block' }}>
                <button
                  className="target-chip"
                  onClick={() => { setTargetId(t.id); submitJob(t.id, t.mission, t.cadence) }}
                  onMouseEnter={() => setTooltipIdx(i)}
                  onMouseLeave={() => setTooltipIdx(null)}
                  onFocus={() => setTooltipIdx(i)}
                  onBlur={() => setTooltipIdx(null)}
                  aria-describedby={`chip-tip-${i}`}
                  disabled={busy}
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
            ))}
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
  const { report, jobStatus, selectedTceId } = useStore()
  if (!report) return null

  const vets = report.vet ?? []
  const activeVet = vets.find((v) => v.tce_id === selectedTceId) ?? vets[0] ?? null

  return (
    <div className="page-body" style={{ paddingTop: 0 }}>
      <hr className="rule-hair" />
      <div className="section-label" style={{ marginBottom: 12 }}>
        Orbital system — {report.target_id}
        {jobStatus && <span className={`job-status-badge ${jobStatus}`} style={{ marginLeft: 10 }}>{jobStatus}</span>}
      </div>
      <OrbitalViewer
        vet={activeVet}
        stellarParams={report.stellar_params}
        jobId={report.job_id}
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
