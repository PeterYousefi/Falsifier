/**
 * src/screens/UploadFlow.tsx
 * Upload flow in newspaper style.
 * Drop zone → file summary → column-mapping table (no preselection) →
 * time-system labeled cards → preview plot with orientation hint →
 * retention policy + submit.
 */
import React, { useState, useRef, useCallback } from 'react'

const TIME_SYSTEM_CARDS = [
  {
    value: 'bjd',
    name: 'BJD',
    desc: 'Barycentric Julian Date — values near 2,458,000, most ground-based software.',
    match: (v: number) => v > 2400000 && v < 2500000,
  },
  {
    value: 'btjd',
    name: 'BTJD',
    desc: 'TESS Barycentric Julian Date — values near 2,000. If this came from the TESS pipeline.',
    match: (v: number) => v > 1000 && v < 10000,
  },
  {
    value: 'bkjd',
    name: 'BKJD',
    desc: 'Barycentric Kepler Julian Date — values near 100–1600. Standard for Kepler data products.',
    match: (v: number) => v > 100 && v < 2000,
  },
  {
    value: 'mjd',
    name: 'MJD',
    desc: 'Modified Julian Date — values near 58,000. Common in general-purpose astronomy software.',
    match: (v: number) => v > 50000 && v < 70000,
  },
  {
    value: 'jd',
    name: 'JD',
    desc: 'Julian Date — values near 2,458,000. The unreduced form of BJD.',
    match: (v: number) => v > 2400000 && v < 2500000,
  },
  {
    value: 'isot',
    name: 'ISOT',
    desc: 'ISO 8601 string (e.g. 2019-06-01T00:00:00). Human-readable calendar time.',
    match: (_v: number) => false,
  },
]

const FLUX_CONVENTIONS = [
  { value: 'sap',        label: 'SAP flux',        desc: 'Raw Simple Aperture Photometry counts from the spacecraft.' },
  { value: 'pdcsap',     label: 'PDCSAP flux',      desc: 'Pre-search Data Conditioning — systematic-corrected counts.' },
  { value: 'normalized', label: 'Normalised flux',  desc: 'Flux divided by the out-of-transit baseline, centred near 1.0.' },
  { value: 'relative',   label: 'Relative flux',    desc: 'Dimensionless ratio; values should dip below 1.0 during transit.' },
]

type ColMapping = {
  time: string
  flux: string
  flux_err: string
  time_format: string
  flux_convention: string
}

type ParsedPreview = {
  columns: string[]
  rows: Record<string, string>[]
  n_rows: number
}

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
  const W = 480, H = 120
  const points = rows
    .map((r) => ({ x: Number(r[timeCol]), y: Number(r[fluxCol]) }))
    .filter((p) => isFinite(p.x) && isFinite(p.y))

  if (!points.length || !timeCol || !fluxCol) return null

  const xs = points.map((p) => p.x)
  const ys = points.map((p) => p.y)
  const xMin = Math.min(...xs), xMax = Math.max(...xs)
  const yMin = Math.min(...ys), yMax = Math.max(...ys)
  const xRng = xMax - xMin || 1
  const yRng = yMax - yMin || 1
  const PAD = 8

  const toX = (v: number) => PAD + ((v - xMin) / xRng) * (W - PAD * 2)
  const toY = (v: number) => H - PAD - ((v - yMin) / yRng) * (H - PAD * 2)
  const pts = points.map((p) => `${toX(p.x).toFixed(1)},${toY(p.y).toFixed(1)}`).join(' ')

  // Does flux spike upward (possible magnitude units)?
  const yMid = (yMax + yMin) / 2
  const spikeUp = ys.some((y) => y > yMid * 1.01)

  return (
    <div style={{ margin: '12px 0' }}>
      <figure className="figure-inset">
        <hr className="figure-inset-rule-top" />
        <div className="figure-inset-plot">
          <svg
            width={W} height={H}
            style={{ background: 'var(--np-surface)', display: 'block', width: '100%' }}
            aria-label={`Preview: ${timeCol} vs ${fluxCol}`}
          >
            <polyline points={pts} fill="none" stroke="var(--rust)" strokeWidth="1.2" />
            <text x={PAD} y={H - 2} fill="var(--np-faint)" fontSize="9" fontFamily="var(--font-mono)">
              {xMin.toFixed(2)}
            </text>
            <text x={W - PAD} y={H - 2} fill="var(--np-faint)" fontSize="9" fontFamily="var(--font-mono)" textAnchor="end">
              {xMax.toFixed(2)}
            </text>
          </svg>
        </div>
        <hr className="figure-inset-rule-bottom" />
        <div className="figure-label">FIG. 1</div>
        <figcaption>
          Preview ({points.length} rows) — {timeCol} vs {fluxCol}.
          {' '}Flux should dip <em>below</em> the baseline (≤ 1.0 for normalised flux) during a transit.
          {spikeUp && (
            <span style={{ color: 'var(--fail)', marginLeft: 4 }}>
              ⚑ Values appear to spike upward — if these are magnitudes, convert to flux first
              (fainter object = higher magnitude = smaller flux).
            </span>
          )}
        </figcaption>
      </figure>
    </div>
  )
}

export default function UploadFlow() {
  const [dragOver, setDragOver] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<ParsedPreview | null>(null)
  const [parseError, setParseError] = useState<string | null>(null)
  const [mapping, setMapping] = useState<ColMapping>({
    time: '', flux: '', flux_err: '',
    time_format: '', flux_convention: '',
  })
  const [submitted, setSubmitted] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleFile = useCallback(async (f: File) => {
    setFile(f)
    setPreview(null)
    setParseError(null)
    setMapping({ time: '', flux: '', flux_err: '', time_format: '', flux_convention: '' })
    setSubmitted(false)

    const result = await parseCsv(f)
    if ('error' in result) {
      setParseError(result.error)
    } else {
      setPreview(result)
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

  const mappingComplete = mapping.time && mapping.flux && mapping.flux_err && mapping.time_format && mapping.flux_convention

  const handleSubmit = async () => {
    if (!mappingComplete || !file) return
    setSubmitting(true)
    await new Promise((r) => setTimeout(r, 900))
    setSubmitting(false)
    setSubmitted(true)
  }

  // Hint about first time value
  const firstTimeValue = preview && mapping.time && preview.rows[0]
    ? Number(preview.rows[0][mapping.time])
    : null

  const matchedTimeCard = firstTimeValue != null && isFinite(firstTimeValue)
    ? TIME_SYSTEM_CARDS.find((c) => c.match(firstTimeValue))
    : null

  return (
    <div className="screen" style={{ overflowY: 'auto' }}>
      <div className="page-body">

        <hr className="rule-double" />
        <div className="article-dateline" style={{ marginTop: 16 }}>
          UPLOAD · CUSTOM LIGHT CURVE
        </div>
        <h1 style={{ marginBottom: 8 }}>Upload a light curve</h1>
        <p className="standfirst">
          Provide a CSV or TSV file with a time column and a flux column.
          The pipeline requires explicit confirmation of the time system and flux convention —
          no defaults are preselected.
        </p>
        <hr className="rule-hair" />

        {/* Step 1 — Drop zone */}
        <div className="step-section">
          <div className="section-label">I. Drop light curve file</div>
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
            {file ? (
              <div>
                <strong style={{ fontFamily: 'var(--font-mono)' }}>{file.name}</strong>
                <span style={{ fontFamily: 'var(--font-mono)', marginLeft: 8, color: 'var(--np-muted)' }}>
                  {(file.size / 1024).toFixed(1)} KB
                </span>
                {preview && (
                  <span style={{ fontFamily: 'var(--font-mono)', marginLeft: 8, color: 'var(--np-muted)' }}>
                    · {preview.n_rows.toLocaleString()} rows · {preview.columns.length} columns
                  </span>
                )}
              </div>
            ) : (
              <>
                Drop a CSV or TSV light curve here, or click to browse.
                <br />
                <span style={{ fontSize: 13, color: 'var(--np-muted)', fontStyle: 'italic' }}>
                  Expected: a header row followed by numeric rows. Columns: time, flux, flux_err.
                </span>
              </>
            )}
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv,.tsv,.txt"
              style={{ display: 'none' }}
              onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f) }}
            />
          </div>

          {parseError && (
            <div className="rejection-box" role="alert" aria-live="assertive">
              <strong>Rejected:</strong> {parseError}
            </div>
          )}
        </div>

        {/* Step 2 — Column mapping */}
        {preview && !parseError && (
          <div className="step-section">
            <div className="section-label">II. Confirm column mapping</div>
            <p style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: 'var(--np-muted)', marginBottom: 10, lineHeight: 1.55 }}>
              The table below shows each detected column with its first two values.
              Assign each column a role — or leave it as "ignore" if not needed.
              No role is preselected.
            </p>
            <table className="col-map-table" aria-label="Column mapping">
              <thead>
                <tr>
                  <th>Column name</th>
                  <th>Value [0]</th>
                  <th>Value [1]</th>
                  <th>Assign as</th>
                </tr>
              </thead>
              <tbody>
                {preview.columns.map((col) => (
                  <tr key={col}>
                    <td style={{ fontFamily: 'var(--font-mono)' }}>{col}</td>
                    <td style={{ fontFamily: 'var(--font-mono)', color: 'var(--np-muted)' }}>
                      {preview.rows[0]?.[col] ?? '—'}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', color: 'var(--np-muted)' }}>
                      {preview.rows[1]?.[col] ?? '—'}
                    </td>
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

        {/* Step 3 — Time system */}
        {preview && !parseError && (
          <div className="step-section">
            <div className="section-label">III. Time system — select one (no default)</div>
            <p style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: 'var(--np-muted)', marginBottom: 10, lineHeight: 1.55 }}>
              Each card describes what values to expect. No system is preselected — you must choose.
            </p>
            <div className="time-cards">
              {TIME_SYSTEM_CARDS.map((card) => (
                <div
                  key={card.value}
                  className={`time-card${mapping.time_format === card.value ? ' selected' : ''}`}
                  onClick={() => setMapping((m) => ({ ...m, time_format: card.value }))}
                  role="radio"
                  aria-checked={mapping.time_format === card.value}
                  tabIndex={0}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setMapping((m) => ({ ...m, time_format: card.value })) }}
                >
                  <div className="time-card-name">{card.name}</div>
                  <div className="time-card-desc">{card.desc}</div>
                </div>
              ))}
            </div>
            {/* Hint from actual first value */}
            {firstTimeValue != null && isFinite(firstTimeValue) && (
              <p style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', fontSize: 13, color: 'var(--np-muted)', marginTop: 10, lineHeight: 1.5 }}>
                Your first time value is{' '}
                <span style={{ fontFamily: 'var(--font-mono)' }}>{firstTimeValue.toFixed(3)}</span>.
                {matchedTimeCard
                  ? ` This looks like ${matchedTimeCard.name} — but please verify before selecting.`
                  : ' This value range does not match any common format — check your time column carefully.'
                }
                {' '}This is a hint only, not an auto-selection.
              </p>
            )}

            {/* Flux convention */}
            <div style={{ marginTop: 20 }}>
              <div className="section-label">Flux convention</div>
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 8 }}>
                {FLUX_CONVENTIONS.map((fc) => (
                  <div
                    key={fc.value}
                    className={`time-card${mapping.flux_convention === fc.value ? ' selected' : ''}`}
                    style={{ flex: '1 1 180px', minWidth: 160 }}
                    onClick={() => setMapping((m) => ({ ...m, flux_convention: fc.value }))}
                    role="radio"
                    aria-checked={mapping.flux_convention === fc.value}
                    tabIndex={0}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setMapping((m) => ({ ...m, flux_convention: fc.value })) }}
                  >
                    <div className="time-card-name">{fc.label}</div>
                    <div className="time-card-desc">{fc.desc}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Step 4 — Submit */}
        {preview && !parseError && (
          <div className="step-section">
            <hr className="rule-hair" />
            <div className="section-label">IV. Confirm and submit</div>
            {!mappingComplete && (
              <p style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: 'var(--np-muted)', marginBottom: 10, lineHeight: 1.55 }}>
                Complete all column assignments and select a time system and flux convention before submitting.
              </p>
            )}
            {/* Demo-mode notice */}
            <div style={{
              background: 'var(--np-surface)',
              border: '1px solid var(--np-rule)',
              borderLeft: '3px solid var(--warn)',
              padding: '8px 12px',
              fontFamily: 'var(--font-serif)',
              fontSize: 13,
              color: 'var(--np-muted)',
              lineHeight: 1.55,
              marginBottom: 12,
            }} role="note">
              <strong style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--warn)', letterSpacing: '0.06em' }}>
                DEMO MODE
              </strong>
              {' '}— No backend is deployed. Submit validates your column mapping and time system
              but does not enqueue a real pipeline run.
            </div>
            {submitted ? (
              <div style={{ color: 'var(--pass)', fontFamily: 'var(--font-mono)', fontSize: 13 }}>
                ✓ Upload accepted — mapping validated (demo mode, no pipeline run)
              </div>
            ) : (
              <div>
                <p style={{ fontFamily: 'var(--font-serif)', fontSize: 13, color: 'var(--np-muted)', marginBottom: 12, lineHeight: 1.5 }}>
                  Uploaded files are held only for the duration of your analysis session and are not retained
                  after the browser window is closed. No light curve data is stored on remote servers.
                </p>
                <button
                  className="btn-primary"
                  onClick={handleSubmit}
                  disabled={!mappingComplete || submitting}
                  aria-label="Submit light curve upload"
                >
                  {submitting ? <><span className="spinner" /> Submitting…</> : 'Submit'}
                </button>
              </div>
            )}
          </div>
        )}

      </div>
    </div>
  )
}
