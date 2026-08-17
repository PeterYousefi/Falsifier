/**
 * src/screens/UploadFlow.tsx
 * Upload flow: drop zone → column mapping → preview plot → submission.
 * Explicit rejection reason shown on malformed input.
 */
import React, { useState, useRef, useCallback } from 'react'

// Time scale and format options (user must choose; no default preselected)
const TIME_SCALES = ['tdb', 'tcb', 'tcg', 'tt', 'ut1', 'utc']
const TIME_FORMATS = ['bjd', 'btjd', 'bkjd', 'jd', 'mjd', 'isot', 'fits']
const FLUX_CONVENTIONS = [
  { value: 'sap', label: 'SAP flux (raw Simple Aperture Photometry)' },
  { value: 'pdcsap', label: 'PDCSAP flux (Pre-search Data Conditioning)' },
  { value: 'normalized', label: 'Normalised flux (around 1.0)' },
  { value: 'relative', label: 'Relative flux (dimensionless)' },
]

type ColMapping = {
  time: string
  flux: string
  flux_err: string
  time_scale: string
  time_format: string
  flux_convention: string
}

type ParsedPreview = {
  columns: string[]
  rows: Record<string, string>[]
  n_rows: number
}

// ── File parser (CSV / TSV heuristic) ──────────────────────────────────────
async function parseCsv(file: File): Promise<ParsedPreview | { error: string }> {
  const text = await file.text()
  const lines = text.split('\n').filter((l) => l.trim().length > 0)
  if (lines.length < 2) return { error: 'File must have at least one header row and one data row.' }

  const sep = lines[0].includes('\t') ? '\t' : ','
  const cols = lines[0].split(sep).map((c) => c.trim().replace(/^"|"$/g, ''))
  if (cols.length < 2) return { error: `Could not detect columns. Expected comma or tab delimiters. Found ${cols.length} column(s).` }

  const rows = lines.slice(1, 11).map((l) => {
    const vals = l.split(sep).map((v) => v.trim().replace(/^"|"$/g, ''))
    const row: Record<string, string> = {}
    cols.forEach((c, i) => { row[c] = vals[i] ?? '' })
    return row
  })

  // Basic numeric check on first data row
  for (const [col, val] of Object.entries(rows[0])) {
    if (val !== '' && isNaN(Number(val))) {
      return { error: `Column "${col}" contains non-numeric value "${val}" in the first data row. This upload expects a numeric light curve table.` }
    }
  }

  return { columns: cols, rows, n_rows: lines.length - 1 }
}

// ── Preview plot (SVG) ─────────────────────────────────────────────────────
function PreviewPlot({ rows, timeCol, fluxCol }: {
  rows: Record<string, string>[]
  timeCol: string
  fluxCol: string
}) {
  const W = 460, H = 100
  const points = rows
    .map((r) => ({ x: Number(r[timeCol]), y: Number(r[fluxCol]) }))
    .filter((p) => isFinite(p.x) && isFinite(p.y))

  if (!points.length || !timeCol || !fluxCol) return null

  const xs = points.map((p) => p.x)
  const ys = points.map((p) => p.y)
  const xMin = Math.min(...xs), xMax = Math.max(...xs)
  const yMin = Math.min(...ys), yMax = Math.max(...ys)
  const xRng = xMax - xMin || 1, yRng = yMax - yMin || 1

  const toX = (v: number) => 4 + ((v - xMin) / xRng) * (W - 8)
  const toY = (v: number) => H - 4 - ((v - yMin) / yRng) * (H - 8)

  const pts = points.map((p) => `${toX(p.x).toFixed(1)},${toY(p.y).toFixed(1)}`).join(' ')

  return (
    <div className="preview-plot-container">
      <div style={{ fontSize: 10, color: 'var(--muted)', marginBottom: 3 }}>
        Preview (first {points.length} rows) — {timeCol} vs {fluxCol}
      </div>
      <svg width={W} height={H} style={{ background: '#0a0c0f', borderRadius: 3, display: 'block' }}>
        <polyline points={pts} fill="none" stroke="#3b82f6" strokeWidth="1" />
        <text x={4} y={H - 3} fill="#374151" fontSize="8">{xMin.toFixed(2)}</text>
        <text x={W - 4} y={H - 3} fill="#374151" fontSize="8" textAnchor="end">{xMax.toFixed(2)}</text>
      </svg>
    </div>
  )
}

// ── Main export ─────────────────────────────────────────────────────────────
export default function UploadFlow() {
  const [dragOver, setDragOver] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<ParsedPreview | null>(null)
  const [parseError, setParseError] = useState<string | null>(null)
  const [mapping, setMapping] = useState<ColMapping>({
    time: '', flux: '', flux_err: '',
    time_scale: '', time_format: '', flux_convention: '',
  })
  const [submitted, setSubmitted] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleFile = useCallback(async (f: File) => {
    setFile(f)
    setPreview(null)
    setParseError(null)
    setMapping({ time: '', flux: '', flux_err: '', time_scale: '', time_format: '', flux_convention: '' })
    setSubmitted(false)

    const result = await parseCsv(f)
    if ('error' in result) {
      setParseError(result.error)
    } else {
      setPreview(result)
      // Auto-detect common column names (user still confirms)
      const cols = result.columns.map((c) => c.toLowerCase())
      const guess = (candidates: string[]) => {
        for (const c of candidates) {
          const idx = cols.findIndex((col) => col.includes(c))
          if (idx !== -1) return result.columns[idx]
        }
        return ''
      }
      setMapping((m) => ({
        ...m,
        time:     guess(['time', 'bjd', 'bkjd', 'btjd', 'jd', 't']),
        flux:     guess(['flux', 'sap_flux', 'pdcsap_flux', 'f']),
        flux_err: guess(['flux_err', 'error', 'err', 'flux_error', 'sigma']),
      }))
    }
  }, [])

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    const f = e.dataTransfer.files[0]
    if (f) handleFile(f)
  }

  const mappingComplete =
    mapping.time && mapping.flux && mapping.flux_err &&
    mapping.time_scale && mapping.time_format && mapping.flux_convention

  const handleSubmit = async () => {
    if (!mappingComplete || !file) return
    setSubmitting(true)
    // Simulate submission delay
    await new Promise((r) => setTimeout(r, 900))
    setSubmitting(false)
    setSubmitted(true)
  }

  return (
    <div className="screen upload-layout">
      <div className="panel-header">
        Upload
        <span className="tag">light curve ingestion</span>
        <span className="spacer" />
        <span style={{ fontSize: 10, color: 'var(--muted)' }}>
          Mandatory column mapping before submission · time scale and format must be explicit
        </span>
      </div>

      <div className="upload-body scroll-body">

        {/* Step 1 — Drop zone */}
        <div className="step-section">
          <div className="step-label">Step 1 — Drop light curve file</div>
          <div
            className={`drop-zone${dragOver ? ' drag-over' : ''}${file && !parseError ? ' has-file' : ''}`}
            tabIndex={0}
            role="button"
            aria-label="Drop light curve file here or click to browse"
            onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') fileInputRef.current?.click() }}
          >
            {file
              ? <><strong>{file.name}</strong> — {(file.size / 1024).toFixed(1)} KB</>
              : <>Drop a CSV or TSV light curve here, or click to browse.<br /><span style={{ fontSize: 11, color: 'var(--muted)' }}>Expected columns: time, flux, flux_err (header row required)</span></>
            }
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv,.tsv,.txt"
              style={{ display: 'none' }}
              onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f) }}
            />
          </div>

          {/* Parse error — shown verbatim */}
          {parseError && (
            <div className="rejection-box" role="alert" aria-live="assertive">
              <strong>Rejected:</strong> {parseError}
            </div>
          )}
        </div>

        {/* Step 2 — Column mapping */}
        {preview && !parseError && (
          <div className="step-section">
            <div className="step-label">
              Step 2 — Confirm column mapping ({preview.n_rows.toLocaleString()} rows detected)
            </div>
            <table className="col-map-table" aria-label="Column mapping">
              <thead>
                <tr>
                  <th>Detected column</th>
                  <th>Assign as</th>
                </tr>
              </thead>
              <tbody>
                {preview.columns.map((col) => (
                  <tr key={col}>
                    <td style={{ fontFamily: 'var(--font-mono)' }}>{col}</td>
                    <td>
                      <select
                        value={
                          mapping.time === col ? 'time'
                            : mapping.flux === col ? 'flux'
                              : mapping.flux_err === col ? 'flux_err'
                                : ''
                        }
                        onChange={(e) => {
                          const role = e.target.value
                          setMapping((m) => ({
                            ...m,
                            time:     m.time === col ? '' : m.time,
                            flux:     m.flux === col ? '' : m.flux,
                            flux_err: m.flux_err === col ? '' : m.flux_err,
                            ...(role === 'time' ? { time: col } : {}),
                            ...(role === 'flux' ? { flux: col } : {}),
                            ...(role === 'flux_err' ? { flux_err: col } : {}),
                          }))
                        }}
                        aria-label={`Assign column ${col}`}
                      >
                        <option value="">— ignore —</option>
                        <option value="time">time</option>
                        <option value="flux">flux</option>
                        <option value="flux_err">flux_err</option>
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {/* Preview plot */}
            {mapping.time && mapping.flux && (
              <PreviewPlot rows={preview.rows} timeCol={mapping.time} fluxCol={mapping.flux} />
            )}
          </div>
        )}

        {/* Step 3 — Time metadata (no default preselected) */}
        {preview && !parseError && (
          <div className="step-section">
            <div className="step-label">Step 3 — Time system (no default — explicit selection required)</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 8 }}>
              <div>
                <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 3 }}>Time scale</div>
                <select
                  value={mapping.time_scale}
                  onChange={(e) => setMapping((m) => ({ ...m, time_scale: e.target.value }))}
                  style={{ background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 'var(--r)', color: 'var(--text)', font: 'inherit', fontSize: 12, padding: '4px 7px', width: '100%' }}
                  aria-label="Time scale"
                >
                  <option value="">— select time scale —</option>
                  {TIME_SCALES.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div>
                <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 3 }}>Time format</div>
                <select
                  value={mapping.time_format}
                  onChange={(e) => setMapping((m) => ({ ...m, time_format: e.target.value }))}
                  style={{ background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 'var(--r)', color: 'var(--text)', font: 'inherit', fontSize: 12, padding: '4px 7px', width: '100%' }}
                  aria-label="Time format"
                >
                  <option value="">— select time format —</option>
                  {TIME_FORMATS.map((f) => <option key={f} value={f}>{f}</option>)}
                </select>
              </div>
            </div>

            <div>
              <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 3 }}>Flux convention</div>
              <select
                value={mapping.flux_convention}
                onChange={(e) => setMapping((m) => ({ ...m, flux_convention: e.target.value }))}
                style={{ background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 'var(--r)', color: 'var(--text)', font: 'inherit', fontSize: 12, padding: '4px 7px', width: '100%' }}
                aria-label="Flux convention"
              >
                <option value="">— select flux convention —</option>
                {FLUX_CONVENTIONS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
              </select>
            </div>
          </div>
        )}

        {/* Step 4 — Confirm and submit */}
        {preview && !parseError && (
          <div className="step-section">
            <div className="step-label">Step 4 — Confirm and submit</div>
            {!mappingComplete && (
              <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 6 }}>
                Complete all column assignments and time system selections before submitting.
              </div>
            )}
            {submitted ? (
              <div style={{ color: 'var(--pass)', fontSize: 12, fontFamily: 'var(--font-mono)' }}>
                ✓ Upload accepted — job queued
              </div>
            ) : (
              <button
                className="primary-btn"
                onClick={handleSubmit}
                disabled={!mappingComplete || submitting}
                aria-label="Submit light curve upload"
              >
                {submitting ? <><span className="spinner" /> Submitting…</> : 'Submit'}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
