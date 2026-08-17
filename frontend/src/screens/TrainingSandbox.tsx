/**
 * src/screens/TrainingSandbox.tsx
 * Training sandbox: labeled-set upload, threshold display, leakage check,
 * session vs baseline metrics, reliability diagrams for both.
 */
import React, { useEffect, useState, useRef } from 'react'
import { dataSource } from '../data/DataSource'
import type { TrainingFixture, TrainingMetrics } from '../data/types'

// ── Metric cell ────────────────────────────────────────────────────────────
function MetricCell({ label, session, baseline, unit = '', higherBetter = true }: {
  label: string
  session: number
  baseline: number
  unit?: string
  higherBetter?: boolean
}) {
  const better = higherBetter ? session >= baseline : session <= baseline
  const delta = session - baseline
  const sign = delta >= 0 ? '+' : ''
  return (
    <div className="metric-cell">
      <div className="m-label">{label}</div>
      <div className="m-value">{session.toFixed(3)}{unit}</div>
      <div className="m-baseline">
        baseline {baseline.toFixed(3)}{unit}
        {' · '}
        <span style={{ color: better ? 'var(--pass)' : 'var(--fail)' }}>
          {sign}{delta.toFixed(3)} {better ? '▲' : '▼'}
        </span>
      </div>
    </div>
  )
}

// ── Reliability diagram (SVG calibration curve) ───────────────────────────
function ReliabilityDiagram({ metrics, label, color }: {
  metrics: TrainingMetrics
  label: string
  color: string
}) {
  const W = 220, H = 180, PAD = 30

  const bins = metrics.calibration_bins
  const inner = { x0: PAD, y0: 0, x1: W - 10, y1: H - PAD }
  const iW = inner.x1 - inner.x0
  const iH = inner.y1 - inner.y0

  const toX = (v: number) => inner.x0 + v * iW
  const toY = (v: number) => inner.y1 - v * iH  // 0 at bottom

  const pts = bins.map((b) => `${toX(b.bin_center).toFixed(1)},${toY(b.fraction_positive).toFixed(1)}`).join(' ')
  const diagPts = `${toX(0).toFixed(1)},${toY(0).toFixed(1)} ${toX(1).toFixed(1)},${toY(1).toFixed(1)}`

  return (
    <div>
      <div style={{ fontSize: 10, color: 'var(--muted)', marginBottom: 3, fontFamily: 'var(--font-mono)' }}>
        {label} · ECE={metrics.ece.toFixed(3)} · Brier={metrics.brier_score.toFixed(3)}
      </div>
      <svg width={W} height={H} style={{ background: '#0a0c0f', borderRadius: 3, display: 'block' }}>
        {/* Perfect calibration diagonal */}
        <polyline points={diagPts} fill="none" stroke="#334155" strokeWidth="0.8" strokeDasharray="3,2" />

        {/* Calibration curve */}
        <polyline points={pts} fill="none" stroke={color} strokeWidth="1.2" />

        {/* Dots at bin centers */}
        {bins.map((b, i) => (
          <circle
            key={i}
            cx={toX(b.bin_center).toFixed(1)}
            cy={toY(b.fraction_positive).toFixed(1)}
            r="2.5"
            fill={color}
          />
        ))}

        {/* Axes */}
        <line x1={inner.x0} y1={inner.y1} x2={inner.x1} y2={inner.y1} stroke="#252a30" strokeWidth="1" />
        <line x1={inner.x0} y1={inner.y0} x2={inner.x0} y2={inner.y1} stroke="#252a30" strokeWidth="1" />

        {/* Axis labels */}
        <text x={W / 2} y={H - 4} fill="#374151" fontSize="9" textAnchor="middle">predicted prob.</text>
        <text x={9} y={H / 2} fill="#374151" fontSize="9" textAnchor="middle" transform={`rotate(-90 9 ${H / 2})`}>
          fraction pos.
        </text>
      </svg>
    </div>
  )
}

// ── Main export ─────────────────────────────────────────────────────────────
export default function TrainingSandbox() {
  const [data, setData] = useState<TrainingFixture | null>(null)
  const [fileUploaded, setFileUploaded] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    dataSource.getTrainingFixture().then(setData).catch(() => {})
  }, [])

  if (!data) {
    return <div className="screen"><div className="no-data">Loading training fixture…</div></div>
  }

  const { session: s, session_metrics: sm, baseline_metrics: bm } = data

  return (
    <div className="screen training-layout">
      <div className="panel-header">
        Training Sandbox
        <span className="tag">xgboost · isotonic calibration</span>
        <span className="spacer" />
        <span style={{ fontSize: 10, color: 'var(--muted)' }}>
          Metrics on the held-out fold · splits grouped by host star (AGENTS.md Rule 4)
        </span>
      </div>

      <div className="training-body">

        {/* Dataset upload */}
        <div className="step-section">
          <div className="step-label">Step 1 — Upload labeled set</div>
          <div className="threshold-note">
            Minimum requirements:&ensp;
            <strong style={{ color: 'var(--text)', fontFamily: 'var(--font-mono)' }}>{s.min_rows_threshold.toLocaleString()} rows</strong>
            {' · '}
            <strong style={{ color: 'var(--text)', fontFamily: 'var(--font-mono)' }}>{s.min_host_stars_threshold} host stars</strong>
            {' (splits grouped by host star ID — AGENTS.md Rule 4)'}
          </div>
          {!fileUploaded ? (
            <>
              <button
                className="primary-btn"
                onClick={() => fileRef.current?.click()}
                aria-label="Upload labeled set CSV"
              >
                Upload labeled set (.csv)
              </button>
              <input
                ref={fileRef}
                type="file"
                accept=".csv,.tsv"
                style={{ display: 'none' }}
                onChange={() => setFileUploaded(true)}
              />
            </>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              <span style={{ color: 'var(--pass)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>✓ {s.labeled_set_name}</span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--muted)' }}>
                {s.n_rows.toLocaleString()} rows · {s.n_host_stars.toLocaleString()} host stars
              </span>
              <span style={{ fontSize: 11, color: 'var(--muted)' }}>DOI: <a href={`https://doi.org/${s.labeled_set_doi}`} target="_blank" rel="noreferrer" style={{ color: 'var(--accent)' }}>{s.labeled_set_doi}</a></span>
            </div>
          )}
        </div>

        {/* Leakage check */}
        <div className="step-section">
          <div className="step-label">Leakage check (host-star disjoint split)</div>
          <div className={`leakage-badge ${s.leakage_check.passed ? 'pass' : 'fail'}`}>
            {s.leakage_check.passed ? '✓ PASSED' : '✗ FAILED'}
          </div>
          <div style={{ marginTop: 5, fontSize: 11, color: 'var(--muted)' }}>{s.leakage_check.detail}</div>
          {!s.leakage_check.passed && (
            <div className="rejection-box" style={{ marginTop: 6 }}>
              Training is blocked: host-star leakage detected. AGENTS.md Rule 4 requires
              GroupShuffleSplit with group_by="host_star_id".
            </div>
          )}
        </div>

        {/* Session vs baseline metrics */}
        <div className="step-section">
          <div className="step-label">Session metrics vs baseline — held-out fold ({sm.n_samples.toLocaleString()} samples)</div>
          <div className="metrics-grid">
            <MetricCell label="AUC-ROC"          session={sm.auc_roc}           baseline={bm.auc_roc}           higherBetter />
            <MetricCell label="Brier Score"       session={sm.brier_score}       baseline={bm.brier_score}       higherBetter={false} />
            <MetricCell label="ECE"               session={sm.ece}               baseline={bm.ece}               higherBetter={false} />
            <MetricCell label="Precision @50%"    session={sm.precision_at_50}   baseline={bm.precision_at_50}   higherBetter />
            <MetricCell label="Recall @50%"       session={sm.recall_at_50}      baseline={bm.recall_at_50}      higherBetter />
          </div>
        </div>

        {/* Reliability diagrams — side by side */}
        <div className="step-section">
          <div className="step-label">Reliability diagrams — session (blue) vs baseline (orange)</div>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            <ReliabilityDiagram metrics={sm} label="session" color="#3b82f6" />
            <ReliabilityDiagram metrics={bm} label="baseline" color="#f59e0b" />
          </div>
          <div style={{ marginTop: 6, fontSize: 10, color: 'var(--muted)' }}>
            Dashed diagonal = perfect calibration.
            Data from: training.session_metrics.calibration_bins · training.baseline_metrics.calibration_bins
          </div>
        </div>

        {/* Non-claim */}
        <div style={{ marginTop: 14, fontSize: 11, color: 'var(--muted)', lineHeight: 1.6, borderTop: '1px solid var(--border)', paddingTop: 10 }}>
          The classifier probability is a ranking score only — not a verdict.
          Disposition is determined exclusively by the vet stage.
        </div>
      </div>
    </div>
  )
}
