/**
 * src/screens/ProvenancePage.tsx
 * Provenance page in newspaper style.
 * Data versions, DOIs, access dates, wired-vs-aspirational module table,
 * locked non-claims prominently displayed.
 */
import React, { useEffect } from 'react'
import { useStore } from '../store'

export default function ProvenancePage() {
  const { provenance, loadProvenance } = useStore()

  useEffect(() => {
    if (!provenance) loadProvenance()
  }, [])

  if (!provenance) {
    return (
      <div className="screen" style={{ overflowY: 'auto' }}>
        <div className="page-body no-data">
          <span className="spinner" aria-label="Loading provenance" />
          <span style={{ marginLeft: 10 }}>Loading provenance…</span>
        </div>
      </div>
    )
  }

  return (
    <div className="screen" style={{ overflowY: 'auto' }}>
      <div className="page-body">

        {/* Article dateline + headline */}
        <hr className="rule-double" />
        <div className="article-dateline" style={{ marginTop: 16 }}>
          PROVENANCE · falsifier {provenance.falsifier_version}
        </div>
        <h1 style={{ marginBottom: 8 }}>Data Provenance</h1>
        <p className="standfirst">
          Every dataset ingested by this pipeline is recorded below with its citable DOI,
          access date, and row count at ingest time.
        </p>
        <hr className="rule-hair" />

        {/* Immutable non-claims */}
        <div className="panel-section">
          <div className="section-label">Immutable non-claims</div>
          <div className="non-claim-block" role="note" aria-label="Immutable non-claims">
            <div className="nc-locked">Locked claims (AGENTS.md)</div>
            <ul>
              {provenance.non_claims.map((c, i) => <li key={i}>{c}</li>)}
            </ul>
          </div>
        </div>

        <hr className="rule-hair" />

        {/* Data versions */}
        <div className="panel-section">
          <div className="section-label">Dataset versions</div>
          {provenance.data_versions.length === 0 ? (
            <p style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', color: 'var(--np-muted)', fontSize: 14 }}>
              No provenance sidecars found in data/golden/. Run the pipeline to generate them.
            </p>
          ) : (
            <table className="prov-table" aria-label="Dataset versions">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>DOI</th>
                  <th>Access date</th>
                  <th>Rows</th>
                  <th>Description</th>
                </tr>
              </thead>
              <tbody>
                {provenance.data_versions.map((dv) => (
                  <tr key={dv.name}>
                    <td className="mono">{dv.name}</td>
                    <td className="mono">
                      <a
                        href={`https://doi.org/${dv.source_doi}`}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {dv.source_doi}
                      </a>
                    </td>
                    <td className="mono">{dv.access_date}</td>
                    <td className="mono">{dv.row_count?.toLocaleString() ?? '—'}</td>
                    <td style={{ fontFamily: 'var(--font-serif)' }}>{dv.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div style={{ marginTop: 8, fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--np-muted)' }}>
            Golden manifest entries: {provenance.golden_manifest_entry_count}
          </div>
        </div>

        <hr className="rule-hair" />

        {/* Module wiring */}
        <div className="panel-section">
          <div className="section-label">Pipeline module wiring status</div>
          <p style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: 'var(--np-muted)', marginBottom: 12, lineHeight: 1.6 }}>
            <em>Wired</em> modules are reachable from the live code path.
            <em> Aspirational</em> modules are written and listed here per AGENTS.md Rule 6,
            but are not yet connected to any live execution path.
          </p>
          <table className="prov-table" aria-label="Pipeline module wiring status">
            <thead>
              <tr>
                <th>Module</th>
                <th>Status</th>
                <th>Note</th>
              </tr>
            </thead>
            <tbody>
              {provenance.modules.map((m) => (
                <tr key={m.module}>
                  <td className="mono">{m.module}</td>
                  <td>
                    {m.status === 'wired'
                      ? <span className="wired-chip">wired</span>
                      : <span className="aspir-chip">aspirational</span>
                    }
                  </td>
                  <td style={{ fontFamily: 'var(--font-serif)', fontSize: 13, color: 'var(--np-muted)' }}>{m.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <hr className="rule-hair" />

        {/* Build info */}
        <div className="panel-section">
          <div className="section-label">Build</div>
          <table className="prov-table" style={{ maxWidth: 420 }} aria-label="Build information">
            <tbody>
              <tr>
                <td style={{ color: 'var(--np-muted)', fontFamily: 'var(--font-serif)' }}>falsifier version</td>
                <td className="mono">{provenance.falsifier_version}</td>
              </tr>
              <tr>
                <td style={{ color: 'var(--np-muted)', fontFamily: 'var(--font-serif)' }}>golden manifest entries</td>
                <td className="mono">{provenance.golden_manifest_entry_count}</td>
              </tr>
            </tbody>
          </table>
        </div>

      </div>
    </div>
  )
}
