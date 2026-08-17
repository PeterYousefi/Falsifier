/**
 * src/screens/ProvenancePage.tsx
 * Provenance: data versions, DOIs, access dates,
 * wired-vs-aspirational module table, locked non-claim prominently displayed.
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
      <div className="screen prov-layout">
        <div className="panel-header">Provenance <span className="tag">loading…</span></div>
        <div className="no-data"><span className="spinner" /></div>
      </div>
    )
  }

  return (
    <div className="screen prov-layout">
      <div className="panel-header">
        Provenance
        <span className="tag">data lineage + module wiring</span>
        <span className="spacer" />
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--muted)' }}>
          falsifier {provenance.falsifier_version}
        </span>
      </div>

      <div className="prov-body scroll-body">

        {/* Locked non-claim — displayed prominently */}
        <div className="prov-section">
          <div className="non-claim-block" role="note" aria-label="Immutable non-claims">
            <div className="nc-locked">Immutable Non-Claims (AGENTS.md)</div>
            <ul>
              {provenance.non_claims.map((c, i) => <li key={i}>{c}</li>)}
            </ul>
          </div>
        </div>

        {/* Data versions */}
        <div className="prov-section">
          <h2>Data versions</h2>
          {provenance.data_versions.length === 0 ? (
            <div style={{ fontSize: 12, color: 'var(--muted)' }}>
              No provenance sidecars found in data/golden/. Run the pipeline to generate them.
            </div>
          ) : (
            <table className="prov-table" aria-label="Data versions">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Source DOI</th>
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
                        style={{ color: 'var(--accent)', textDecoration: 'none' }}
                      >
                        {dv.source_doi}
                      </a>
                    </td>
                    <td className="mono">{dv.access_date}</td>
                    <td className="mono">{dv.row_count?.toLocaleString() ?? '—'}</td>
                    <td>{dv.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div style={{ marginTop: 6, fontSize: 10, color: 'var(--muted)' }}>
            Golden manifest entries: <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text)' }}>{provenance.golden_manifest_entry_count}</span>
          </div>
        </div>

        {/* Module wiring */}
        <div className="prov-section">
          <h2>Module wiring status</h2>
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
                  <td style={{ fontSize: 11, color: 'var(--muted)' }}>{m.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Pipeline version */}
        <div className="prov-section">
          <h2>Build</h2>
          <table className="prov-table" aria-label="Build information">
            <tbody>
              <tr>
                <td style={{ color: 'var(--muted)' }}>falsifier version</td>
                <td className="mono">{provenance.falsifier_version}</td>
              </tr>
              <tr>
                <td style={{ color: 'var(--muted)' }}>golden manifest entries</td>
                <td className="mono">{provenance.golden_manifest_entry_count}</td>
              </tr>
            </tbody>
          </table>
        </div>

      </div>
    </div>
  )
}
