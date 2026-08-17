/**
 * src/screens/CandidateDetail.tsx
 * Full candidate detail screen: phase-folded LC, all 7 vetting rows,
 * disposition, calibrated probability as separate ranking signal.
 *
 * Also exports shared helpers (VetBadge, DispoChip, Row, PhaseLCPlot,
 * VETTING_TEST_ORDER, TEST_LABELS) used by the inline system detail panel.
 */
import React, { useMemo, useRef } from 'react'
import { useStore } from '../store'
import type { VettingTestOutcome, Disposition, PhasedLC } from '../data/types'

export const VETTING_TEST_ORDER = [
  'odd_even_depth',
  'secondary_eclipse',
  'centroid_shift',
  'transit_shape',
  'stellar_density',
  'gaia_ruwe',
  'systematics_coincidence',
] as const

export const TEST_LABELS: Record<string, string> = {
  odd_even_depth:           'Odd / even depth',
  secondary_eclipse:        'Secondary eclipse',
  centroid_shift:           'Centroid shift',
  transit_shape:            'Transit shape',
  stellar_density:          'Stellar density',
  gaia_ruwe:                'Gaia RUWE',
  systematics_coincidence:  'Systematics coincidence',
}

// ── VetBadge ──────────────────────────────────────────────────────────────
export function VetBadge({ outcome }: { outcome: VettingTestOutcome | string }) {
  return <span className={`vet-badge ${outcome}`}>{outcome}</span>
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
  const W = 296, H = 90
  if (!phasedData?.phase?.length) {
    return (
      <div className="lc-container">
        <svg width={W} height={H} style={{ background: '#0a0c0f', borderRadius: 3, display: 'block' }}>
          <text x={W / 2} y={H / 2} fill="#374151" textAnchor="middle" dominantBaseline="middle" fontSize="11">
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

  const toX = (p: number) => ((p + 0.5)) * W           // phase ∈ [-0.5, 0.5]
  const toY = (f: number) => H - 2 - ((f - minF) / rng) * (H - 6)

  const pts = phase.map((p, i) => `${toX(p).toFixed(1)},${toY(flux[i]).toFixed(1)}`).join(' ')

  return (
    <div className="lc-container">
      <svg
        width={W} height={H}
        style={{ background: '#0a0c0f', borderRadius: 3, display: 'block' }}
        aria-label="Phase-folded light curve"
        role="img"
      >
        {/* Axis labels */}
        <text x={2} y={H - 2} fill="#374151" fontSize="9">−0.5</text>
        <text x={W - 22} y={H - 2} fill="#374151" fontSize="9">+0.5</text>
        <text x={W / 2} y={H - 2} fill="#374151" fontSize="9" textAnchor="middle">phase</text>
        {/* Mid-transit line */}
        <line x1={W / 2} y1="0" x2={W / 2} y2={H} stroke="#334155" strokeWidth="0.5" strokeDasharray="2,2" />
        {/* Light curve */}
        <polyline points={pts} fill="none" stroke="#3b82f6" strokeWidth="0.9" />
        {/* Baseline */}
        <line x1="0" y1={toY(maxF)} x2={W} y2={toY(maxF)} stroke="#1e2329" strokeWidth="0.5" />
      </svg>
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
      <div className="screen" style={{ overflow: 'auto' }}>
        <div className="no-data" style={{ height: '100%' }}>
          No report available. Run a target from the System screen.
        </div>
      </div>
    )
  }

  return (
    <div className="screen" style={{ overflow: 'auto' }}>
      <div style={{ maxWidth: 780, padding: '14px 16px' }}>

        {/* TCE selector */}
        {report.vet.length > 1 && (
          <div style={{ marginBottom: 12, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {report.vet.map((v) => (
              <TceSelector key={v.tce_id} tce_id={v.tce_id} disposition={v.disposition} />
            ))}
          </div>
        )}

        {vetResult ? (
          <>
            {/* Header */}
            <div style={{ marginBottom: 14 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
                <h1 style={{ fontFamily: 'var(--font-mono)', fontSize: 15, fontWeight: 500, color: 'var(--text)' }}>
                  {vetResult.tce_id}
                </h1>
                <DispoChip disposition={vetResult.disposition} />
                {vetResult.triggering_test && (
                  <span style={{ fontSize: 11, color: 'var(--muted)' }}>
                    triggered by <span style={{ color: 'var(--text)' }}>{TEST_LABELS[vetResult.triggering_test]}</span>
                  </span>
                )}
              </div>
              {vetResult.triggering_reason && (
                <div style={{ fontSize: 12, color: 'var(--muted)', fontStyle: 'italic' }}>
                  "{vetResult.triggering_reason}"
                </div>
              )}
            </div>

            {/* Two-column layout: LC + metrics */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 14 }}>

              {/* Phase-folded LC */}
              <section aria-label="Phase-folded light curve">
                <div className="step-label">Phase-folded light curve</div>
                <PhaseLCPlot phasedData={vetResult.phased_lc} />
                <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 4 }}>
                  Data from: report.vet[].phased_lc
                </div>
              </section>

              {/* TCE parameters */}
              <section aria-label="TCE parameters">
                <div className="step-label">TCE parameters</div>
                <div className="detail-section" style={{ borderBottom: 'none' }}>
                  <Row label="Period"   value={vetResult.period_days != null ? `${vetResult.period_days.toFixed(6)} d` : null}   source="vet.period_days" />
                  <Row label="Depth"    value={vetResult.depth_ppm != null ? `${vetResult.depth_ppm.toFixed(0)} ppm` : null}       source="vet.depth_ppm" />
                  <Row label="Duration" value={vetResult.duration_hours != null ? `${vetResult.duration_hours.toFixed(3)} h` : null} source="vet.duration_hours" />
                  <Row label="Epoch"    value={vetResult.epoch_bkjd != null ? `${vetResult.epoch_bkjd.toFixed(4)} BKJD` : null}   source="vet.epoch_bkjd" />
                  <Row label="Inclination" value={vetResult.inclination_deg != null ? `${vetResult.inclination_deg.toFixed(1)} °` : null} source="vet.inclination_deg" />
                  <Row label="Vet time" value={vetResult.wall_time_seconds != null ? `${vetResult.wall_time_seconds.toFixed(2)} s` : null} source="vet.wall_time_seconds" />
                </div>
              </section>
            </div>

            {/* Calibrated probability — clearly separate from disposition */}
            {classifyResult && (
              <section aria-label="Classifier ranking score" style={{ marginBottom: 14 }}>
                <div className="step-label">Classifier ranking score</div>
                <div style={{
                  background: 'var(--surface2)', border: '1px solid var(--border)',
                  borderLeft: '3px solid var(--warn)', borderRadius: 'var(--r)', padding: '10px 12px',
                }}>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 6 }}>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 22, fontWeight: 500, color: 'var(--text)' }}>
                      {(classifyResult.probability * 100).toFixed(1)} %
                    </span>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--muted)' }}>
                      ± {(classifyResult.probability_uncertainty * 100).toFixed(1)} %
                    </span>
                    <span style={{ fontSize: 11, color: 'var(--warn)' }}>ranking only</span>
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--muted)', lineHeight: 1.5 }}>
                    Model: <span style={{ fontFamily: 'var(--font-mono)' }}>{classifyResult.model_version}</span>
                    {' · '}Source: <span style={{ fontFamily: 'var(--font-mono)' }}>classify.probability</span>
                  </div>
                  <div style={{ marginTop: 5, fontSize: 11, color: 'var(--muted)', lineHeight: 1.5 }}>
                    This probability is a ranking signal only. It carries no disposition.
                    Disposition is determined exclusively by the vet stage above.
                  </div>
                </div>
              </section>
            )}

            {/* All 7 vetting rows */}
            <section aria-label="Vetting tests">
              <div className="step-label">Vetting tests — all 7</div>
              <div style={{ background: 'var(--surface2)', border: '1px solid var(--border)', borderRadius: 'var(--r)', overflow: 'hidden' }}>
                <div style={{ padding: '4px 10px', borderBottom: '1px solid var(--border)', display: 'flex', gap: 7, fontSize: 10, color: 'var(--muted)' }}>
                  <span style={{ width: 80 }}>Outcome</span>
                  <span style={{ minWidth: 160 }}>Test</span>
                  <span style={{ minWidth: 80, textAlign: 'right' }}>Metric</span>
                  <span style={{ flex: 1 }}>Reason</span>
                </div>
                {VETTING_TEST_ORDER.map((name) => {
                  const r = vetResult.test_results?.find((t) => t.test_name === name)
                  const outcome = r?.outcome ?? 'INCONCLUSIVE'
                  const isTriggering = vetResult.triggering_test === name
                  return (
                    <div
                      key={name}
                      className={`vet-row${isTriggering ? ' triggering' : ''}`}
                      style={{ padding: '5px 10px' }}
                      aria-label={`${TEST_LABELS[name]}: ${outcome}`}
                    >
                      <VetBadge outcome={outcome} />
                      <span className="vet-name" style={{ minWidth: 160 }}>
                        {TEST_LABELS[name]}
                        {isTriggering && <span style={{ color: 'var(--fail)', marginLeft: 4, fontSize: 10 }}>◀ trigger</span>}
                      </span>
                      <span className="vet-metric">
                        {r?.metric_value != null
                          ? `${r.metric_value.toFixed(3)}${r.metric_unit ? ` ${r.metric_unit}` : ''}`
                          : '—'}
                      </span>
                      <span className="vet-reason">{r?.reason ?? '—'}</span>
                    </div>
                  )
                })}
              </div>
            </section>
          </>
        ) : (
          <div className="no-data">No TCE selected.</div>
        )}
      </div>
    </div>
  )
}

function TceSelector({ tce_id, disposition }: { tce_id: string; disposition: Disposition | string }) {
  const { selectedTceId, setSelectedTceId } = useStore()
  const active = selectedTceId === tce_id || (!selectedTceId)
  return (
    <button
      style={{
        background: active ? 'var(--accent-dim)' : 'var(--surface2)',
        border: `1px solid ${active ? 'var(--accent)' : 'var(--border)'}`,
        borderRadius: 'var(--r)', color: active ? 'var(--accent)' : 'var(--muted)',
        cursor: 'pointer', font: 'inherit', fontFamily: 'var(--font-mono)', fontSize: 11,
        padding: '2px 10px',
      }}
      onClick={() => setSelectedTceId(tce_id)}
      aria-pressed={active}
    >
      {tce_id} <DispoChip disposition={disposition} />
    </button>
  )
}
