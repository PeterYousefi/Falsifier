/**
 * src/screens/TrainingSandbox.tsx
 * Training sandbox in newspaper style.
 * Session metrics vs baseline, leakage check, reliability diagrams.
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

// ── Reliability diagram (SVG) ─────────────────────────────────────────────
function ReliabilityDiagram({ metrics, label, color }: {
  metrics: TrainingMetrics
  label: string
  color: string
}) {
  const W = 240, H = 190, PAD = 32

  const bins = metrics.calibration_bins
  const inner = { x0: PAD, y0: 0, x1: W - 10, y1: H - PAD }
  const iW = inner.x1 - inner.x0
  const iH = inner.y1 - inner.y0

  const toX = (v: number) => inner.x0 + v * iW
  const toY = (v: number) => inner.y1 - v * iH

  const pts = bins.map((b) => `${toX(b.bin_center).toFixed(1)},${toY(b.fraction_positive).toFixed(1)}`).join(' ')
  const diagPts = `${toX(0).toFixed(1)},${toY(0).toFixed(1)} ${toX(1).toFixed(1)},${toY(1).toFixed(1)}`

  return (
    <div>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--np-muted)', marginBottom: 4, letterSpacing: '0.05em' }}>
        {label.toUpperCase()} · ECE={metrics.ece.toFixed(3)} · Brier={metrics.brier_score.toFixed(3)}
      </div>
      <svg width={W} height={H}
        style={{ background: 'var(--np-surface)', border: '1px solid var(--np-border)', display: 'block' }}
        aria-label={`${label} reliability diagram`}
      >
        <polyline points={diagPts} fill="none" stroke="var(--np-border)" strokeWidth="0.8" strokeDasharray="3,2" />
        <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" />
        {bins.map((b, i) => (
          <circle
            key={i}
            cx={toX(b.bin_center).toFixed(1)}
            cy={toY(b.fraction_positive).toFixed(1)}
            r="3"
            fill={color}
          />
        ))}
        <line x1={inner.x0} y1={inner.y1} x2={inner.x1} y2={inner.y1} stroke="var(--np-rule)" strokeWidth="1" />
        <line x1={inner.x0} y1={inner.y0} x2={inner.x0} y2={inner.y1} stroke="var(--np-rule)" strokeWidth="1" />
        <text x={W / 2} y={H - 4} fill="var(--np-faint)" fontSize="9" textAnchor="middle" fontFamily="var(--font-mono)">
          predicted prob.
        </text>
        <text x={9} y={H / 2} fill="var(--np-faint)" fontSize="9" textAnchor="middle"
          fontFamily="var(--font-mono)"
          transform={`rotate(-90 9 ${H / 2})`}>
          fraction pos.
        </text>
      </svg>
    </div>
  )
}

export default function TrainingSandbox() {
  const [data, setData] = useState<TrainingFixture | null>(null)
  const [fileUploaded, setFileUploaded] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    dataSource.getTrainingFixture().then(setData).catch(() => {})
  }, [])

  if (!data) {
    return (
      <div className="screen" style={{ overflowY: 'auto' }}>
        <div className="page-body no-data">
          <span className="spinner" aria-label="Loading training fixture" />
          <span style={{ marginLeft: 10 }}>Loading training data…</span>
        </div>
      </div>
    )
  }

  const { session: s, session_metrics: sm, baseline_metrics: bm } = data

  return (
    <div className="screen" style={{ overflowY: 'auto' }}>
      <div className="page-body">

        <hr className="rule-double" />
        <h1 style={{ marginTop: 14, marginBottom: 6 }}>Training Sandbox</h1>
        <p style={{ fontFamily: 'var(--font-serif)', color: 'var(--np-muted)', fontSize: 15, lineHeight: 1.6, marginBottom: 6 }}>
          Upload a labeled set to retrain the XGBoost classifier and compare session metrics against the
          committed baseline. Splits are always grouped by host star ID to prevent system-level data leakage
          (AGENTS.md Rule 4).
        </p>
        <p style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--np-muted)', marginBottom: 20 }}>
          Classifier probability is a ranking score only — not a verdict. Disposition is determined by the vet stage.
        </p>
        <hr className="rule-hair" />

        {/* Step 1 — Upload labeled set */}
        <div className="step-section">
          <div className="section-label">I. Upload labeled set</div>
          <p style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: 'var(--np-muted)', marginBottom: 10, lineHeight: 1.55 }}>
            Minimum requirements:{' '}
            <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--np-text)' }}>{s.min_rows_threshold.toLocaleString()} rows</span>
            {' · '}
            <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--np-text)' }}>{s.min_host_stars_threshold} host stars</span>
            {' '}(splits grouped by host star ID — AGENTS.md Rule 4)
          </p>
          {!fileUploaded ? (
            <>
              <button
                className="btn-primary"
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
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
              <span style={{ color: 'var(--pass)', fontFamily: 'var(--font-mono)', fontSize: 12 }}>✓ {s.labeled_set_name}</span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--np-muted)' }}>
                {s.n_rows.toLocaleString()} rows · {s.n_host_stars.toLocaleString()} host stars
              </span>
              <span style={{ fontSize: 13, color: 'var(--np-muted)', fontFamily: 'var(--font-serif)' }}>
                DOI:{' '}
                <a href={`https://doi.org/${s.labeled_set_doi}`} target="_blank" rel="noreferrer">
                  {s.labeled_set_doi}
                </a>
              </span>
            </div>
          )}
        </div>

        <hr className="rule-muted" />

        {/* Leakage check */}
        <div className="step-section">
          <div className="section-label">Leakage check — host-star disjoint split</div>
          <div className={`leakage-badge ${s.leakage_check.passed ? 'pass' : 'fail'}`}>
            {s.leakage_check.passed ? '✓ PASSED' : '✗ FAILED'}
          </div>
          <p style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: 'var(--np-muted)', marginTop: 8, lineHeight: 1.55 }}>
            {s.leakage_check.detail}
          </p>
          {!s.leakage_check.passed && (
            <div className="rejection-box">
              Training is blocked: host-star leakage detected.
              AGENTS.md Rule 4 requires GroupShuffleSplit with group_by="host_star_id".
            </div>
          )}
        </div>

        <hr className="rule-muted" />

        {/* Session vs baseline metrics */}
        <div className="step-section">
          <div className="section-label">
            Session metrics vs baseline — held-out fold ({sm.n_samples.toLocaleString()} samples)
          </div>
          <div className="metrics-grid">
            <MetricCell label="AUC-ROC"       session={sm.auc_roc}         baseline={bm.auc_roc}         higherBetter />
            <MetricCell label="Brier Score"   session={sm.brier_score}     baseline={bm.brier_score}     higherBetter={false} />
            <MetricCell label="ECE"           session={sm.ece}             baseline={bm.ece}             higherBetter={false} />
            <MetricCell label="Precision @50%" session={sm.precision_at_50} baseline={bm.precision_at_50} higherBetter />
            <MetricCell label="Recall @50%"   session={sm.recall_at_50}   baseline={bm.recall_at_50}   higherBetter />
          </div>
        </div>

        <hr className="rule-muted" />

        {/* Reliability diagrams */}
        <div className="step-section">
          <div className="section-label">Reliability diagrams — session vs baseline</div>
          <figure className="figure-inset">
            <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
              <ReliabilityDiagram metrics={sm} label="session" color="var(--rust)" />
              <ReliabilityDiagram metrics={bm} label="baseline" color="var(--np-faint)" />
            </div>
            <figcaption>
              Dashed diagonal = perfect calibration.
              Session model in rust; baseline in grey.
              A well-calibrated model tracks the diagonal.
              Source: <span style={{ fontFamily: 'var(--font-mono)' }}>training.session_metrics.calibration_bins</span>
              {' · '}
              <span style={{ fontFamily: 'var(--font-mono)' }}>training.baseline_metrics.calibration_bins</span>
            </figcaption>
          </figure>
        </div>

      </div>
    </div>
  )
}
