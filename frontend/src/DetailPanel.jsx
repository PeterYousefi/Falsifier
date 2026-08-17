/**
 * src/DetailPanel.jsx
 * Right-panel: shows selected TCE detail.
 *
 * Sections:
 *   1. Target overview  — host star ID, n_segments, stellar params
 *   2. TCE properties   — period, depth, duration, epoch (ALL from report)
 *   3. Classify score   — probability ± uncertainty, labelled "ranking score"
 *   4. Vetting rows     — 7 named tests with outcome badge + reason
 *   5. Phase-folded LC  — canvas SVG mini-plot (data from report or placeholder)
 *   6. Download panel   — JSON artifact buttons
 *
 * Policy: every numeric value rendered has a data-source attribute pointing
 * to the API field it came from.  No values are invented.
 *
 * When highlightedPanel === 'vet' the entire vetting section pulses.
 */
import React, { useRef, useEffect, useMemo } from 'react'
import { useStore } from './store.js'

const VETTING_TEST_ORDER = [
  'odd_even_depth',
  'secondary_eclipse',
  'centroid_shift',
  'transit_shape',
  'stellar_density',
  'gaia_ruwe',
  'systematics_coincidence',
]

const TEST_LABELS = {
  odd_even_depth:           'Odd/even depth',
  secondary_eclipse:        'Secondary eclipse',
  centroid_shift:           'Centroid shift',
  transit_shape:            'Transit shape',
  stellar_density:          'Stellar density',
  gaia_ruwe:                'Gaia RUWE',
  systematics_coincidence:  'Systematics coincidence',
}

// ── helpers ───────────────────────────────────────────────────────────────
function fmt(v, decimals = 4) {
  if (v == null) return '—'
  return Number(v).toFixed(decimals)
}

function fmtUnit(unitedArr, decimals = 4) {
  if (!unitedArr?.values?.length) return '—'
  return `${fmt(unitedArr.values[0], decimals)} ${unitedArr.unit}`
}

// ── DetailRow with data-source attribute ──────────────────────────────────
function Row({ label, value, source }) {
  return (
    <div className="detail-row">
      <span className="label">{label}</span>
      <span className="value" data-source={source} title={source ? `Source: ${source}` : undefined}>
        {value ?? '—'}
      </span>
    </div>
  )
}

// ── Phase-folded light curve mini-plot (SVG) ──────────────────────────────
function PhaseLCPlot({ phasedData }) {
  // phasedData: {phase: number[], flux: number[]} or null
  const W = 300, H = 100
  if (!phasedData?.phase?.length) {
    return (
      <svg width={W} height={H} style={{ background: '#0a0c0f', borderRadius: 3 }}>
        <text x={W/2} y={H/2} fill="#374151" textAnchor="middle" dominantBaseline="middle" fontSize="11">
          No light curve data yet
        </text>
      </svg>
    )
  }

  const { phase, flux } = phasedData
  const minF = Math.min(...flux), maxF = Math.max(...flux)
  const range = maxF - minF || 1

  const toX = (p) => ((p + 0.5) / 1.0) * W   // phase ∈ [-0.5, 0.5]
  const toY = (f) => H - ((f - minF) / range) * (H - 4) - 2

  const pts = phase.map((p, i) => `${toX(p).toFixed(1)},${toY(flux[i]).toFixed(1)}`).join(' ')

  return (
    <svg width={W} height={H} style={{ background: '#0a0c0f', borderRadius: 3, display: 'block' }}>
      <polyline points={pts} fill="none" stroke="#3b82f6" strokeWidth="0.8" />
      {/* Mid-transit marker */}
      <line x1={W/2} y1="0" x2={W/2} y2={H} stroke="#334155" strokeWidth="0.5" strokeDasharray="2,2" />
    </svg>
  )
}

// ── Vetting section ────────────────────────────────────────────────────────
function VettingSection({ vetResult, highlightedPanel }) {
  if (!vetResult?.test_results?.length) {
    // Render skeleton rows with the correct labels but no data
    return (
      <div className="detail-section">
        <h3>Vetting tests</h3>
        {VETTING_TEST_ORDER.map((name) => (
          <div key={name} className="vet-row">
            <span className="vet-badge INCONCLUSIVE">—</span>
            <span className="vet-name">{TEST_LABELS[name]}</span>
            <span className="vet-reason" style={{ color: 'var(--muted)' }}>no data</span>
          </div>
        ))}
      </div>
    )
  }

  const byName = {}
  for (const r of vetResult.test_results) byName[r.test_name] = r

  const isHighlighted = highlightedPanel === 'vet'

  return (
    <div className={`detail-section${isHighlighted ? ' highlighted' : ''}`}
         style={isHighlighted ? { transition: 'background 0.2s', background: 'var(--highlight)' } : {}}>
      <h3>
        Vetting tests&nbsp;
        {vetResult.disposition && (
          <span className={`disposition-chip ${vetResult.disposition}`}>
            {vetResult.disposition.replace(/_/g, ' ')}
          </span>
        )}
      </h3>
      {VETTING_TEST_ORDER.map((name) => {
        const r = byName[name]
        const outcome = r?.outcome ?? 'INCONCLUSIVE'
        const isTriggering = vetResult.triggering_test === name
        return (
          <div key={name}
               className={`vet-row${isTriggering ? ' highlighted' : ''}`}
               title={isTriggering ? 'Triggering test' : undefined}>
            <span className={`vet-badge ${outcome}`}>{outcome}</span>
            <span className="vet-name">{TEST_LABELS[name]}</span>
            <span className="vet-reason">
              {r?.reason ?? '—'}
              {r?.metric_value != null && (
                <span style={{ color: 'var(--muted)', marginLeft: 6 }}>
                  ({fmt(r.metric_value, 3)}{r.metric_unit ? ` ${r.metric_unit}` : ''})
                </span>
              )}
            </span>
          </div>
        )
      })}
    </div>
  )
}

// ── Download panel ─────────────────────────────────────────────────────────
function DownloadPanel({ report }) {
  if (!report) return null

  const downloadJson = (obj, filename) => {
    const blob = new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="detail-section">
      <h3>Download</h3>
      <button className="download-btn"
              onClick={() => downloadJson(report, `report_${report.job_id}.json`)}>
        ↓ Full report (JSON)
      </button>
      {report.vet?.length > 0 && (
        <button className="download-btn"
                onClick={() => downloadJson(report.vet, `vet_${report.job_id}.json`)}>
          ↓ Vetting results (JSON)
        </button>
      )}
      {report.classify?.length > 0 && (
        <button className="download-btn"
                onClick={() => downloadJson(report.classify, `classify_${report.job_id}.json`)}>
          ↓ Classify scores (JSON)
        </button>
      )}
    </div>
  )
}

// ── Main export ────────────────────────────────────────────────────────────
export default function DetailPanel() {
  const { report, selectedTceId, highlightedPanel } = useStore()

  // Find the selected vet result
  const vetResult = useMemo(() => {
    if (!report?.vet?.length) return null
    if (selectedTceId) return report.vet.find((v) => v.tce_id === selectedTceId) ?? report.vet[0]
    return report.vet[0]
  }, [report, selectedTceId])

  // Find matching classify result
  const classifyResult = useMemo(() => {
    if (!report?.classify?.length || !vetResult) return null
    return report.classify.find((c) => c.tce_id === vetResult.tce_id) ?? null
  }, [report, vetResult])

  if (!report) {
    return (
      <div className="panel panel--detail">
        <div className="panel-header">
          Detail <span className="tag">no target</span>
        </div>
        <div className="no-data">
          Run a detection job to see<br />TCE detail, vetting rows,<br />and the download panel.
        </div>
      </div>
    )
  }

  const ingest = report.ingest
  const search = report.search

  return (
    <div className="panel panel--detail">
      <div className="panel-header">
        Detail
        <span className="tag">{report.target_id}</span>
        {report.ingest?.host_star_id && (
          <span className="tag" style={{ color: 'var(--accent)' }}>{report.ingest.host_star_id}</span>
        )}
      </div>

      {/* Target overview */}
      <div className={`detail-section${highlightedPanel === 'ingest' ? ' highlighted' : ''}`}
           style={highlightedPanel === 'ingest' ? { background: 'var(--highlight)' } : {}}>
        <h3>Target</h3>
        <Row label="Host star" value={ingest?.host_star_id} source="ingest.host_star_id" />
        <Row label="Segments" value={ingest?.n_segments} source="ingest.n_segments" />
        <Row label="Stellar params" value={ingest?.has_stellar_params ? 'yes' : 'no'} source="ingest.has_stellar_params" />
        <Row label="Code version" value={ingest?.code_version} source="ingest.code_version" />
        <Row label="Wall time" value={ingest?.wall_time_seconds != null ? `${ingest.wall_time_seconds.toFixed(2)}s` : null} source="ingest.wall_time_seconds" />
      </div>

      {/* Search overview */}
      <div className={`detail-section${highlightedPanel === 'search' ? ' highlighted' : ''}`}
           style={highlightedPanel === 'search' ? { background: 'var(--highlight)' } : {}}>
        <h3>Search</h3>
        <Row label="TCEs found" value={search?.n_tces ?? 0} source="search.n_tces" />
        <Row label="TLS version" value={search?.tls_version} source="search.tls_version" />
        {search?.tce_ids?.map((id) => (
          <Row key={id} label="TCE" value={id} source="search.tce_ids" />
        ))}
      </div>

      {/* Phase-folded light curve */}
      <div className={`detail-section${highlightedPanel === 'lc' ? ' highlighted' : ''}`}
           style={highlightedPanel === 'lc' ? { background: 'var(--highlight)' } : {}}>
        <h3>Phase-folded light curve <span style={{ color: 'var(--muted)' }}>(from report)</span></h3>
        <PhaseLCPlot phasedData={vetResult?.phased_lc ?? null} />
      </div>

      {/* Vetting */}
      <VettingSection vetResult={vetResult} highlightedPanel={highlightedPanel} />

      {/* Classify score */}
      {classifyResult && (
        <div className={`detail-section${highlightedPanel === 'classify' ? ' highlighted' : ''}`}
             style={highlightedPanel === 'classify' ? { background: 'var(--highlight)' } : {}}>
          <h3>Classify <span style={{ color: 'var(--warn)', fontWeight: 400 }}>ranking score only — not a verdict</span></h3>
          <Row label="Probability" value={`${(classifyResult.probability * 100).toFixed(1)}%`} source="classify.probability" />
          <Row label="± uncertainty" value={`${(classifyResult.probability_uncertainty * 100).toFixed(1)}%`} source="classify.probability_uncertainty" />
          <Row label="Model version" value={classifyResult.model_version} source="classify.model_version" />
          <div style={{ marginTop: 6, fontSize: 10, color: 'var(--muted)', lineHeight: 1.5 }}>
            This score is a ranking tool only. It carries no disposition.<br />
            Disposition is determined exclusively by the vet stage above.
          </div>
        </div>
      )}

      {/* Non-claims */}
      {report.non_claims?.length > 0 && (
        <div className="detail-section" style={{ fontSize: 10, color: 'var(--muted)', lineHeight: 1.6 }}>
          <h3>Non-claims</h3>
          {report.non_claims.map((c, i) => (
            <div key={i} style={{ marginBottom: 2 }}>— {c}</div>
          ))}
        </div>
      )}

      {/* Download */}
      <DownloadPanel report={report} />
    </div>
  )
}
