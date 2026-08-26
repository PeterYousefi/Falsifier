/**
 * src/screens/CandidateDetail.tsx
 * Full candidate detail — result page styled as a news report.
 * Headline states the physical finding. Standfirst names the deciding test.
 * Two-column body with phase LC as a bordered figure-inset.
 * All 7 tests always shown; metrics behind "Show the numbers" expander.
 * Classifier panel shown only when a trained model artifact produced a score;
 * renders an explicit unavailable state otherwise.
 *
 * Also exports shared helpers used by other screens.
 */
import React, { useMemo, useState, useRef } from 'react'
import { useStore } from '../store'
import type { VettingTestOutcome, Disposition, PhasedLC, VetResult, ClassifyResult, DetectionReport } from '../data/types'
import { dispositionStandfirst } from '../data/outcomeConfig'

export const VETTING_TEST_ORDER = [
  'odd_even_depth',
  'secondary_eclipse',
  'centroid_shift',
  'transit_shape',
  'stellar_density',
  'gaia_ruwe',
  'systematics_coincidence',
] as const

export const TEST_LABELS: Record<string, { short: string; headline: string; why: string }> = {
  odd_even_depth: {
    short:    'Odd / even depth',
    headline: 'Every dip is the same depth',
    why:      'An eclipsing binary produces alternating deep and shallow dips as each star passes in front of the other. Equal depths rule that out.',
  },
  secondary_eclipse: {
    short:    'Secondary eclipse',
    headline: 'No secondary event at half-orbit',
    why:      'Two stars produce a second dimming half an orbit away, when the fainter star is eclipsed. Absence of this event is a key test.',
  },
  centroid_shift: {
    short:    'Centroid shift',
    headline: 'The star\'s position did not move during the dip',
    why:      'If the signal comes from a background star rather than the target, the pixel centroid shifts during the dimming. A fixed centroid points back to the target.',
  },
  transit_shape: {
    short:    'Transit shape',
    headline: 'The dip has a limb-darkened profile, not a V-shape',
    why:      'A planet transiting a limb-darkened star produces a U-shaped dip with a curved floor. A sharp V-shape is the eclipsing-binary heuristic — it indicates a companion of comparable size.',
  },
  stellar_density: {
    short:    'Stellar density',
    headline: 'Transit geometry matches the star',
    why:      'The transit duration and depth together imply a stellar density. Agreement with the spectroscopic value confirms the geometry is self-consistent.',
  },
  gaia_ruwe: {
    short:    'Gaia RUWE',
    headline: 'Single-star astrometric solution',
    why:      'Gaia\'s astrometric fit residuals diagnose unresolved binaries. A high RUWE indicates a second source whose light could mimic a transit.',
  },
  systematics_coincidence: {
    short:    'Systematics coincidence',
    headline: 'Dips don\'t align with spacecraft events',
    why:      'Known instrumental artefacts — thruster firings, attitude tweaks — occur at predictable times. Overlap would flag an instrumental origin.',
  },
}

// Lowercase roman numeral sequence for vetting rows
const ROMAN_LOWER = ['i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'viii', 'ix', 'x']

const OUTCOME_ICONS: Record<string, string> = {
  PASS:        '✓',
  FAIL:        '✗',
  FLAG:        '⚑',
  INCONCLUSIVE: '?',
}

// ── VetBadge ──────────────────────────────────────────────────────────────
export function VetBadge({ outcome }: { outcome: VettingTestOutcome | string }) {
  return (
    <div className={`vet-badge ${outcome}`} aria-label={outcome}>
      {OUTCOME_ICONS[outcome] ?? outcome[0]}
    </div>
  )
}

// ── DispoChip ─────────────────────────────────────────────────────────────
export function DispoChip({ disposition }: { disposition: Disposition | string | null | undefined }) {
  if (!disposition) return null
  return (
    <span className={`dispo-chip ${disposition}`}>
      {disposition.replace(/_/g, ' ')}
    </span>
  )
}

// ── Detail row with data-source ───────────────────────────────────────────
export function Row({ label, value, source }: { label: string; value: unknown; source?: string }) {
  const display = value == null ? '—' : String(value)
  return (
    <div className="detail-row">
      <span className="lbl">{label}</span>
      <span className="val" data-source={source} title={source ? `Source: ${source}` : undefined}>
        {display}
      </span>
    </div>
  )
}

// ── Phase-folded light curve (SVG) ────────────────────────────────────────
export function PhaseLCPlot({ phasedData }: { phasedData: PhasedLC | null | undefined }) {
  const W = 320, H = 100

  if (!phasedData?.phase?.length) {
    return (
      <div className="lc-container">
        <svg
          width={W} height={H}
          style={{ background: 'var(--np-surface)', display: 'block', border: '1px solid var(--np-border)' }}
        >
          <text x={W / 2} y={H / 2} fill="var(--np-faint)" textAnchor="middle" dominantBaseline="middle" fontSize="12"
            fontFamily="var(--font-serif)" fontStyle="italic">
            No light curve data
          </text>
        </svg>
      </div>
    )
  }

  const { phase, flux } = phasedData
  const minF = Math.min(...flux)
  const maxF = Math.max(...flux)
  const rng  = maxF - minF || 1

  const PAD = 6
  const toX = (p: number) => PAD + (p + 0.5) * (W - PAD * 2)
  const toY = (f: number) => H - PAD - ((f - minF) / rng) * (H - PAD * 3)

  const pts = phase.map((p, i) => `${toX(p).toFixed(1)},${toY(flux[i]).toFixed(1)}`).join(' ')

  return (
    <div className="lc-container">
      <svg
        width={W} height={H}
        style={{ background: 'var(--np-surface)', display: 'block', border: '1px solid var(--np-border)' }}
        aria-label="Phase-folded light curve"
        role="img"
      >
        <text x={PAD} y={H - 2} fill="var(--np-faint)" fontSize="8" fontFamily="var(--font-mono)">−0.5</text>
        <text x={W - PAD - 16} y={H - 2} fill="var(--np-faint)" fontSize="8" fontFamily="var(--font-mono)">+0.5</text>
        <text x={W / 2} y={H - 2} fill="var(--np-faint)" fontSize="8" fontFamily="var(--font-mono)" textAnchor="middle">phase</text>
        <line x1={W / 2} y1="0" x2={W / 2} y2={H} stroke="var(--np-border)" strokeWidth="0.5" strokeDasharray="2,2" />
        <line x1={PAD} y1={toY(maxF)} x2={W - PAD} y2={toY(maxF)} stroke="var(--np-border)" strokeWidth="0.5" />
        <polyline points={pts} fill="none" stroke="var(--rust)" strokeWidth="1.2" />
      </svg>
    </div>
  )
}

// ── Number expander row ────────────────────────────────────────────────────
function MetricExpander({ metric_value, metric_unit, threshold }: {
  metric_value: number | null | undefined
  metric_unit: string | null | undefined
  threshold?: string
}) {
  const [open, setOpen] = useState(false)
  return (
    <div>
      <button
        className="expander-btn"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        {open ? 'Hide the numbers ▲' : 'Show the numbers ▼'}
      </button>
      {open && (
        <div className="expander-panel">
          <div>Metric: <span style={{ color: 'var(--np-text)' }}>
            {metric_value != null ? `${metric_value}${metric_unit ? ' ' + metric_unit : ''}` : '—'}
          </span></div>
          {threshold && <div>Threshold: <span style={{ color: 'var(--np-text)' }}>{threshold}</span></div>}
          <div style={{ fontSize: 11, marginTop: 3, color: 'var(--np-faint)' }}>Source: report.vet[].test_results</div>
        </div>
      )}
    </div>
  )
}

// ── Vetting test row with numeral gutter ───────────────────────────────────
function VetTestRow({ name, vetResult, index }: { name: string; vetResult: VetResult; index: number }) {
  const r = vetResult.test_results?.find((t) => t.test_name === name)
  const outcome = r?.outcome ?? 'INCONCLUSIVE'
  const isTriggering = vetResult.triggering_test === name
  const label = TEST_LABELS[name]
  const numeral = ROMAN_LOWER[index] ?? String(index + 1)

  return (
    <div
      className={`vet-row${isTriggering ? ' triggering' : ''}`}
      aria-label={`${label?.short}: ${outcome}`}
    >
      <span className="vet-numeral">{numeral}</span>
      <VetBadge outcome={outcome} />
      <div className="vet-body">
        <div className="vet-headline">
          {label?.headline ?? label?.short ?? name}
          {isTriggering && <span className="vet-trigger-label">◀ deciding test</span>}
        </div>
        <div className="vet-why">{r?.reason ?? label?.why ?? '—'}</div>
        <MetricExpander
          metric_value={r?.metric_value}
          metric_unit={r?.metric_unit}
        />
      </div>
    </div>
  )
}

// ── Headline generator (physical finding, not status code) ────────────────
function reportHeadline(vet: VetResult, targetId: string): string {
  if (vet.disposition === 'candidate') {
    return `${targetId} survives every challenge`
  }
  if (vet.disposition === 'false_positive') {
    const tl = vet.triggering_test ? TEST_LABELS[vet.triggering_test]?.short : null
    return tl
      ? `Not a planet: rejected by the ${tl} test`
      : 'Not a planet: rejected by automated vetting'
  }
  if (vet.disposition === 'candidate_with_caveats') {
    return `${targetId} passes most tests but carries caveats`
  }
  return `${targetId} — ${vet.disposition.replace(/_/g, ' ')}`
}

function reportStandfirst(vet: VetResult, classify: ClassifyResult | null): string {
  // Delegate to outcomeConfig so standfirst text is consistent across all screens.
  const base = dispositionStandfirst(vet)
  if (vet.disposition === 'candidate' && classify) {
    return `${base} Ranking score ${(classify.probability * 100).toFixed(1)}\u202f% (signal only, not a verdict).`
  }
  if (vet.disposition === 'false_positive' && vet.triggering_test) {
    const label = TEST_LABELS[vet.triggering_test]?.short ?? vet.triggering_test
    return `The deciding test was "${label}". ${vet.triggering_reason ?? ''}`
  }
  return base
}

// ── Download helper ────────────────────────────────────────────────────────
function dlJson(obj: unknown, name: string) {
  const b = new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json' })
  const u = URL.createObjectURL(b)
  const a = document.createElement('a')
  a.href = u; a.download = name; a.click()
  URL.revokeObjectURL(u)
}

// ── TCE selector ──────────────────────────────────────────────────────────
function TceSelector({ tce_id, disposition }: { tce_id: string; disposition: Disposition | string }) {
  const { selectedTceId, setSelectedTceId } = useStore()
  const active = selectedTceId === tce_id || !selectedTceId
  return (
    <button
      style={{
        background: active ? 'var(--rust-dim)' : 'var(--np-surface)',
        border: `1px solid ${active ? 'var(--rust)' : 'var(--np-rule)'}`,
        borderRadius: 0, color: active ? 'var(--rust)' : 'var(--np-muted)',
        cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: 11,
        padding: '3px 10px', display: 'inline-flex', alignItems: 'center', gap: 6,
      }}
      onClick={() => setSelectedTceId(tce_id)}
      aria-pressed={active}
    >
      {tce_id} <DispoChip disposition={disposition} />
    </button>
  )
}

// ── Fixture provenance badge ───────────────────────────────────────────────
export function FixtureProvenanceBadge({ report }: { report: DetectionReport }) {
  if (!report.fixture_provenance) return null
  return (
    <div
      role="note"
      data-testid="fixture-provenance-badge"
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: 10,
        padding: '8px 14px',
        background: 'var(--np-surface)',
        border: '1px solid var(--np-rule)',
        borderLeft: '3px solid var(--warn)',
        marginBottom: 16,
        fontFamily: 'var(--font-serif)',
        fontSize: 13,
        color: 'var(--np-muted)',
        lineHeight: 1.55,
      }}
    >
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--warn)', letterSpacing: '0.06em', whiteSpace: 'nowrap', paddingTop: 2 }}>
        FIXTURE
      </span>
      <span>
        <strong style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--np-text)' }}>
          This report was not computed by the pipeline.
        </strong>
        {' '}It is a committed hand-authored fixture ({report.fixture_provenance.fixture_id}).
        Values shown are illustrative and are <strong>not</strong> outputs of a live run.
        {' '}No trained classifier model exists; the ranking score cannot be computed.
        {' '}See the Provenance page for pipeline status.
      </span>
    </div>
  )
}

// ── Classifier unavailable panel ───────────────────────────────────────────
function ClassifierUnavailablePanel({ reason }: { reason: string }) {
  return (
    <div style={{ breakInside: 'avoid', marginBottom: 16 }}>
      <div className="section-label">II. Ranking score — not a verdict</div>
      <div style={{
        background: 'var(--np-surface)', border: '1px solid var(--np-rule)',
        borderLeft: '3px solid var(--np-rule)', padding: '12px 14px',
      }}>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--np-muted)', marginBottom: 4 }}>
          — unavailable
        </div>
        <p style={{ fontSize: 13, color: 'var(--np-muted)', lineHeight: 1.55, marginBottom: 4 }}>
          {reason}
        </p>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--np-faint)' }}>
          Source: classify.probability · blocker: no model artifact
        </div>
      </div>
    </div>
  )
}

// ── Main screen ────────────────────────────────────────────────────────────
export default function CandidateDetail() {
  const { report, selectedTceId } = useStore()

  const vetResult = useMemo(() => {
    if (!report?.vet?.length) return null
    if (selectedTceId) return report.vet.find((v) => v.tce_id === selectedTceId) ?? report.vet[0]
    return report.vet[0]
  }, [report, selectedTceId])

  const classifyResult = useMemo(() => {
    if (!report?.classify?.length || !vetResult) return null
    return report.classify.find((c) => c.tce_id === vetResult.tce_id) ?? null
  }, [report, vetResult])

  if (!report) {
    return (
      <div className="screen" style={{ overflowY: 'auto' }}>
        <div className="page-body">
          <div className="no-data">
            No report available. Run a target from the Investigate screen first,<br />
            or try the "Run the Kepler-10b example" button on that screen.
          </div>
        </div>
      </div>
    )
  }

  const headline = vetResult ? reportHeadline(vetResult, report.target_id) : report.target_id
  const standfirst = vetResult ? reportStandfirst(vetResult, classifyResult) : ''

  // Determine classifier unavailable reason for item 3
  const classifierUnavailableReason = useMemo(() => {
    if (classifyResult) return null
    if (report.fixture_provenance) {
      return 'No trained classifier model artifact exists (artifacts/classify/xgb_classifier.ubj is absent). ' +
        'The training pipeline is blocked by train/serve feature skew — see README for details. ' +
        'This fixture value was a stub; it has been removed.'
    }
    return 'No classifier result is available for this TCE. Run the pipeline with run_classify=true and a trained model artifact present.'
  }, [classifyResult, report.fixture_provenance])

  return (
    <div className="screen" style={{ overflowY: 'auto' }}>
      <div className="page-body">

        {/* Fixture provenance badge — always shown at top when fixture-backed */}
        <FixtureProvenanceBadge report={report} />

        {/* TCE selector (multiple TCEs) */}
        {report.vet.length > 1 && (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16 }}>
            <span className="section-label" style={{ marginBottom: 0, alignSelf: 'center' }}>Select TCE:</span>
            {report.vet.map((v) => (
              <TceSelector key={v.tce_id} tce_id={v.tce_id} disposition={v.disposition} />
            ))}
          </div>
        )}

        {/* Article dateline + headline + standfirst */}
        <hr className="rule-double" />
        <div className="article-dateline" style={{ marginTop: 16 }}>
          {report.target_id} · CANDIDATE REPORT
        </div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 6, flexWrap: 'wrap' }}>
          <h1 style={{ marginBottom: 0 }}>{headline}</h1>
          {vetResult && <DispoChip disposition={vetResult.disposition} />}
        </div>
        <p className="standfirst">{standfirst}</p>
        <hr className="rule-hair" />

        {vetResult ? (
          <div className="article-columns" style={{ marginTop: 20 }}>

            {/* FIG. 1 — Phase-folded LC */}
            <figure className="figure-inset" style={{ breakInside: 'avoid' }}>
              <hr className="figure-inset-rule-top" />
              <div className="figure-inset-plot">
                <PhaseLCPlot phasedData={vetResult.phased_lc} />
              </div>
              <hr className="figure-inset-rule-bottom" />
              <div className="figure-label">FIG. 1</div>
              <figcaption>
                Phase-folded light curve for <span style={{ fontFamily: 'var(--font-mono)' }}>{vetResult.tce_id}</span>,
                plotted point-by-point from <span style={{ fontFamily: 'var(--font-mono)' }}>report.vet[].phased_lc</span>.
                Each point is one binned observation; flux is normalised to the out-of-transit baseline.
                A genuine limb-darkened planet transit appears as a U-shaped dip with a curved floor, symmetric about phase zero.
                An empty panel here means no phased light curve is present in the artifact — the pipeline has not run.
              </figcaption>
            </figure>

            {/* I. ORBITAL PARAMETERS */}
            <div style={{ breakInside: 'avoid', marginBottom: 16 }}>
              <div className="section-label">I. Orbital parameters</div>
              <div style={{ background: 'var(--np-surface)', border: '1px solid var(--np-rule)', padding: '10px 14px' }}>
                <Row label="Period"      value={vetResult.period_days != null ? `${vetResult.period_days} d` : null}                  source="vet.period_days" />
                <Row label="Depth"       value={vetResult.depth_ppm != null ? `${vetResult.depth_ppm.toFixed(0)} ppm` : null}         source="vet.depth_ppm" />
                <Row label="Duration"    value={vetResult.duration_hours != null ? `${vetResult.duration_hours} h` : null}            source="vet.duration_hours" />
                <Row label="Epoch"       value={vetResult.epoch_bkjd != null ? `${vetResult.epoch_bkjd} BKJD` : null}                source="vet.epoch_bkjd" />
                <Row label="Inclination" value={vetResult.inclination_deg != null ? `${vetResult.inclination_deg} °` : null}          source="vet.inclination_deg" />
                <Row label="TCE ID"      value={vetResult.tce_id}                                                                     source="vet.tce_id" />
              </div>
            </div>

            {/* II. RANKING SCORE — live result or explicit unavailable state */}
            {classifyResult ? (
              <div style={{ breakInside: 'avoid', marginBottom: 16 }}>
                <div className="section-label">II. Ranking score — not a verdict</div>
                <div style={{
                  background: 'var(--np-surface)', border: '1px solid var(--np-rule)',
                  borderLeft: '3px solid var(--warn)', padding: '12px 14px',
                }}>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 6 }}>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 26, fontWeight: 500, color: 'var(--np-text)' }}>
                      {(classifyResult.probability * 100).toFixed(1)}\u202f%
                    </span>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--np-muted)' }}>
                      ±\u202f{(classifyResult.probability_uncertainty * 100).toFixed(1)}\u202f%
                    </span>
                  </div>
                  <p style={{ fontSize: 13, color: 'var(--np-muted)', lineHeight: 1.55, marginBottom: 4 }}>
                    This is a ranking signal — it helps prioritise follow-up observations, not decide disposition.
                    Disposition is determined exclusively by the vetting tests above.
                  </p>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--np-faint)' }}>
                    Model: {classifyResult.model_version}
                    {' · '}Source: classify.probability
                  </div>
                </div>
              </div>
            ) : (
              <ClassifierUnavailablePanel reason={classifierUnavailableReason ?? 'No classifier result available.'} />
            )}

            {/* III. VETTING TESTS */}
            <div style={{ columnSpan: 'all', marginTop: 4 } as React.CSSProperties}>
              <hr className="rule-double" />
              <div className="section-label" style={{ marginTop: 16 }}>
                III. The seven challenges
                <span style={{ fontFamily: 'var(--font-serif)', textTransform: 'none', letterSpacing: 0, color: 'var(--np-muted)', marginLeft: 8, fontSize: 12 }}>
                  (Metrics hidden by default — click "Show the numbers" on any row to expand)
                </span>
              </div>
              <div style={{ background: 'var(--np-surface)', border: '1px solid var(--np-rule)', padding: '4px 16px' }}>
                {VETTING_TEST_ORDER.map((name, idx) => (
                  <VetTestRow key={name} name={name} vetResult={vetResult} index={idx} />
                ))}
              </div>
            </div>

            {/* Downloads */}
            <div style={{ columnSpan: 'all', marginTop: 20 } as React.CSSProperties}>
              <hr className="rule-hair" />
              <div className="section-label" style={{ marginBottom: 10 }}>Download pipeline artifacts</div>
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                <button className="dl-btn" style={{ width: 'auto', flex: 'none', padding: '7px 16px' }}
                  onClick={() => dlJson(report, `report_${report.job_id}.json`)}>
                  ↓ Full report (JSON)
                </button>
                {report.vet?.length > 0 && (
                  <button className="dl-btn" style={{ width: 'auto', flex: 'none', padding: '7px 16px' }}
                    onClick={() => dlJson(report.vet, `vet_${report.job_id}.json`)}>
                    ↓ Vetting results (JSON)
                  </button>
                )}
              </div>
            </div>

          </div>
        ) : (
          <div className="no-data">No TCE selected.</div>
        )}
      </div>
    </div>
  )
}
