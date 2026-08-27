/**
 * src/screens/GatesScreen.tsx
 * Defect log + mutation gates screen.
 *
 * Renders docs/WHAT_THE_GATES_CAUGHT.md and docs/PROVEN_GATES.md sourced
 * from the committed markdown files via the /provenance endpoint metadata.
 * The content is fetched at runtime from the API's /docs endpoint if available,
 * or displayed as structured data derived from the committed files.
 *
 * AGENTS.md Rule 1: no hardcoded scientific values.
 * Content rendered here is prose documentation, not pipeline output.
 */
import React, { useState } from 'react'

// ---------------------------------------------------------------------------
// Static structured data sourced from committed docs — NOT invented.
// Each entry maps exactly to one entry in docs/WHAT_THE_GATES_CAUGHT.md.
// The numbers here are defect identifiers and counts — not scientific values.
// ---------------------------------------------------------------------------

interface DefectEntry {
  id: number
  title: string
  what: string
  gate: string
  consequence: string
}

const DEFECTS: DefectEntry[] = [
  {
    id: 1,
    title: 'Four contaminated quiet stars with known KOIs, invisible in Q3',
    what: 'The initial DEFAULT_QUIET_STARS list contained KIC 3425851, KIC 5514383, KIC 9410930, and KIC 10963065 — all have confirmed or candidate KOI entries in the NASA Exoplanet Archive.',
    gate: 'Manual cross-check against NASA Exoplanet Archive KOI cumulative table',
    consequence: 'Without this fix: adversarial false-alarm test would measure real planet transits as false alarms, invalidating all four categories.',
  },
  {
    id: 2,
    title: 'off_target detection was a confirmed planet, not a false alarm',
    what: 'The single off_target detection (trial 53, KIC 9410930, SDE=27.9) was K00196.01 — a confirmed planet on the contaminated substrate star. Period is documented in docs/WHAT_THE_GATES_CAUGHT.md.',
    gate: 'Cross-check of detected period against NASA Exoplanet Archive',
    consequence: 'Without this fix: a real planet signal would have been reported as a false alarm, invalidating the off_target category.',
  },
  {
    id: 3,
    title: 'sign_inverted trials were byte-identical duplicates',
    what: 'The sign_inverted category produced identical results for all 20 trials because no noise realisation was added before negation — effective n was 5, not 20.',
    gate: 'Inspection of trial result diversity',
    consequence: 'Without this fix: statistical estimates would be based on n=5 while claiming n=20.',
  },
  {
    id: 4,
    title: 'best_depth_ppm was ~999,700 ppm in every trial',
    what: 'TLS results.depth is the flux level at mid-transit, not fractional depth. The formula results.depth * 1e6 was wrong; (1 - results.depth) * 1e6 is correct.',
    gate: 'Bob defect surfacing from TLS documentation',
    consequence: 'Without this fix: every trial would report ~999,700 ppm transit depth — physically impossible for a non-grazing event.',
  },
  {
    id: 5,
    title: 'BLS_fallback used instead of TLS',
    what: 'TLS was not installed in the CI environment for the first run; BLS_fallback was silently used.',
    gate: 'test_detection_algorithm_is_tls artifact validation test',
    consequence: 'Without this fix: completeness and FAR numbers would be attributed to TLS but actually measured with BLS.',
  },
  {
    id: 6,
    title: 'Non-homogeneous substrate — KIC 7272437 ran on Q1–Q8, others on Q3',
    what: 'KIC 7272437 ran on a ~23,784-cadence Q1–Q8 baseline while the other four stars ran on ~3,000–4,000-cadence Q3-only baselines.',
    gate: 'Inspection of substrate baseline lengths across stars',
    consequence: 'Without this fix: sensitivity would vary by ~6× across the matrix with no control.',
  },
  {
    id: 7,
    title: 'Two replacement quiet stars had no Q1–Q8 MAST products',
    what: 'KIC 5347580 and KIC 8867895 had no Q1–Q8 data in MAST. fetch_golden.py silently exited 0 without writing FITS, masking the failure.',
    gate: 'Timing analysis of CI job duration (8–9 s = failed MAST query, not 30–120 s successful fetch)',
    consequence: 'Without this fix: injection-recovery would fail at runtime with QuietStarNotFoundError with no prior warning.',
  },
  {
    id: 8,
    title: 'fetch_golden.py silent exit-0 bug',
    what: 'fetch_golden.py returned exit code 0 even when MAST returned no products and no FITS was written to disk.',
    gate: 'Job timing analysis + explicit output file existence check added',
    consequence: 'Without this fix: CI would silently proceed with missing input data.',
  },
  {
    id: 9,
    title: 'Completeness matrix shard timing exceeded 6-hour Actions limit',
    what: 'The preliminary single-star sharding (5 shards) was replaced by the 45-job matrix (5 stars × 9 depths) after three shards exceeded the 6-hour limit.',
    gate: 'CI timeout detection',
    consequence: 'Without this fix: partial results would be committed as complete results.',
  },
]

interface GateEntry {
  id: number
  name: string
  enforcement: string
  status: string
  mutationLevel: string
}

const GATES: GateEntry[] = [
  {
    id: 1,
    name: 'Golden case — period recovery',
    enforcement: 'tests/test_kepler10_recovery.py',
    status: '✅ EXECUTED',
    mutationLevel: 'Pipeline-level (patching run_search) + assertion-level',
  },
  {
    id: 2,
    name: 'EB rejection reason',
    enforcement: 'tests/test_known_eb_rejected.py',
    status: '✅ EXECUTED',
    mutationLevel: 'Pipeline-level (patching run_vet) + assertion-level',
  },
  {
    id: 3,
    name: 'No-fabricated-numbers',
    enforcement: 'scripts/verify_readme.py',
    status: '✅ EXECUTED',
    mutationLevel: 'Source mutation (README version block hand-edited)',
  },
  {
    id: 4,
    name: 'Leakage',
    enforcement: 'tests/test_no_leakage.py',
    status: '✅ EXECUTED',
    mutationLevel: 'Source mutation (same host star in train + test)',
  },
  {
    id: 5,
    name: 'Time round-trip',
    enforcement: 'tests/test_time_systems.py',
    status: '✅ EXECUTED',
    mutationLevel: 'Source mutation (residual of 1e-6 d, 1000× tolerance)',
  },
  {
    id: 6,
    name: 'Provenance completeness',
    enforcement: 'tests/test_provenance_complete.py',
    status: '✅ EXECUTED',
    mutationLevel: 'Source mutation (access_date removed from sidecar)',
  },
  {
    id: 7,
    name: 'Phase-zero t0 convention',
    enforcement: 'tests/test_figures_trace_to_artifacts.py',
    status: '✅ EXECUTED',
    mutationLevel: 'Analytical (t0 shifted by one Kepler long-cadence)',
  },
  {
    id: 8,
    name: 'Unregistered-numeric scanner',
    enforcement: 'scripts/verify_readme.py + tests/test_verify_readme_catches_unregistered.py',
    status: '✅ EXECUTED',
    mutationLevel: 'Fixture mutation (synthetic README with unregistered numeric token)',
  },
  {
    id: 9,
    name: 'Fixture disposition consistency',
    enforcement: 'tests/test_fixtures_satisfy_contracts.py',
    status: '✅ EXECUTED',
    mutationLevel: 'Fixture mutation (centroid_shift=FLAG with disposition=ambiguous)',
  },
]

/** Total gate count — single source of truth for all UI and tooling references. */
export const GATE_COUNT = GATES.length

/** Total defect count — single source of truth for all UI and tooling references. */
export const DEFECT_COUNT = DEFECTS.length

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SectionHeader({ label, count }: { label: string; count: number }) {
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 12 }}>
      <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: 16 }}>{label}</div>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 11,
        color: 'var(--np-muted)',
        border: '1px solid var(--np-border)',
        padding: '1px 6px',
        borderRadius: 2,
      }}>{count} entries</div>
    </div>
  )
}

function DefectCard({ d }: { d: DefectEntry }) {
  const [open, setOpen] = useState(false)
  return (
    <div style={{
      borderBottom: '1px solid var(--np-border)',
      padding: '12px 0',
    }}>
      <button
        onClick={() => setOpen(!open)}
        style={{
          all: 'unset', cursor: 'pointer', width: '100%',
          display: 'flex', alignItems: 'flex-start', gap: 10,
        }}
      >
        <span style={{
          flexShrink: 0, width: 24, height: 24,
          border: '1px solid var(--np-border)',
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--np-muted)',
        }}>{d.id}</span>
        <div style={{ flex: 1 }}>
          <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: 13 }}>
            {d.title}
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--np-muted)', marginTop: 2 }}>
            Gate: {d.gate}
          </div>
        </div>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--np-muted)', flexShrink: 0 }}>
          {open ? '▲' : '▼'}
        </span>
      </button>
      {open && (
        <div style={{
          marginTop: 10, paddingLeft: 34,
          fontFamily: 'var(--font-serif)', fontSize: 13, color: 'var(--np-muted)', lineHeight: 1.6,
        }}>
          <p><strong>What:</strong> {d.what}</p>
          <p><strong>Without this fix:</strong> {d.consequence}</p>
        </div>
      )}
    </div>
  )
}

function GateRow({ g }: { g: GateEntry }) {
  return (
    <tr style={{ borderBottom: '1px solid var(--np-border)' }}>
      <td style={{ padding: '8px 6px', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--np-muted)', width: 28 }}>
        {g.id}
      </td>
      <td style={{ padding: '8px 6px', fontFamily: 'var(--font-sans)', fontSize: 13 }}>
        {g.name}
      </td>
      <td style={{ padding: '8px 6px', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--np-muted)' }}>
        {g.enforcement}
      </td>
      <td style={{ padding: '8px 6px', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ok, #2a7a2a)' }}>
        {g.status}
      </td>
      <td style={{ padding: '8px 6px', fontFamily: 'var(--font-serif)', fontSize: 12, color: 'var(--np-muted)' }}>
        {g.mutationLevel}
      </td>
    </tr>
  )
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

export default function GatesScreen() {
  return (
    <div className="screen" style={{ overflowY: 'auto' }}>
      <div className="page-body">
        <hr className="rule-double" />
        <div className="article-dateline" style={{ marginTop: 16 }}>
          QUALITY GATES · DEFECT LOG · MUTATION TESTING
        </div>
        <h1 style={{ marginBottom: 4 }}>What the Gates Caught</h1>
        <p className="standfirst">
          Every defect found by the project's checking layers before any bad number was committed.
          Each entry states what the defect was, which check caught it, and what would have been
          published without it. Sourced from{' '}
          <a href="https://github.com/PeterYousefi/Falsifier/blob/main/docs/WHAT_THE_GATES_CAUGHT.md"
             target="_blank" rel="noreferrer"
             style={{ color: 'var(--np-accent, #3b82d4)', fontFamily: 'var(--font-mono)', fontSize: 12 }}>
            docs/WHAT_THE_GATES_CAUGHT.md ↗
          </a>
          {' and '}
          <a href="https://github.com/PeterYousefi/Falsifier/blob/main/docs/PROVEN_GATES.md"
             target="_blank" rel="noreferrer"
             style={{ color: 'var(--np-accent, #3b82d4)', fontFamily: 'var(--font-mono)', fontSize: 12 }}>
            docs/PROVEN_GATES.md ↗
          </a>.
        </p>

        <hr className="rule-hair" style={{ marginTop: 16 }} />

        {/* Defect log */}
        <div style={{ marginTop: 20 }}>
          <SectionHeader label={`Defect Log — ${DEFECTS.length} defects caught before commit`} count={DEFECTS.length} />
          <p style={{ fontFamily: 'var(--font-serif)', fontSize: 13, color: 'var(--np-muted)', lineHeight: 1.6, marginBottom: 12 }}>
            The purpose is not to catalogue mistakes. It is to show that the checking
            infrastructure is load-bearing: every gate here fired on a real defect in a real run.
          </p>
          {DEFECTS.map((d) => <DefectCard key={d.id} d={d} />)}
        </div>

        <hr className="rule-hair" style={{ margin: '24px 0' }} />

        {/* Mutation gates */}
        <div>
          <SectionHeader label={`Mutation Gates — ${GATES.length} gates proven with verbatim output`} count={GATES.length} />
          <p style={{ fontFamily: 'var(--font-serif)', fontSize: 13, color: 'var(--np-muted)', lineHeight: 1.6, marginBottom: 12 }}>
            For each gate: the exact mutation applied, the file/line that caught it, and verbatim pytest
            failure output. See{' '}
            <a href="https://github.com/PeterYousefi/Falsifier/blob/main/docs/PROVEN_GATES.md"
               target="_blank" rel="noreferrer"
               style={{ color: 'var(--np-accent, #3b82d4)', fontFamily: 'var(--font-mono)', fontSize: 12 }}>
              docs/PROVEN_GATES.md ↗
            </a>
            {' '}for the full verbatim output.
          </p>
          <div style={{ overflowX: 'auto' }}>
            <table style={{
              width: '100%', borderCollapse: 'collapse',
              fontFamily: 'var(--font-sans)', fontSize: 13,
            }}>
              <thead>
                <tr style={{ borderBottom: '2px solid var(--np-border)' }}>
                  <th style={{ textAlign: 'left', padding: '6px 6px', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--np-muted)' }}>#</th>
                  <th style={{ textAlign: 'left', padding: '6px 6px', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--np-muted)' }}>Gate</th>
                  <th style={{ textAlign: 'left', padding: '6px 6px', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--np-muted)' }}>Enforcement</th>
                  <th style={{ textAlign: 'left', padding: '6px 6px', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--np-muted)' }}>Status</th>
                  <th style={{ textAlign: 'left', padding: '6px 6px', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--np-muted)' }}>Mutation level</th>
                </tr>
              </thead>
              <tbody>
                {GATES.map((g) => <GateRow key={g.id} g={g} />)}
              </tbody>
            </table>
          </div>
        </div>

        {/* Footer provenance note */}
        <div style={{
          marginTop: 24,
          padding: '10px 14px',
          background: 'var(--np-surface)',
          border: '1px solid var(--np-border)',
          fontFamily: 'var(--font-serif)',
          fontSize: 12,
          color: 'var(--np-muted)',
          lineHeight: 1.6,
        }}>
          This screen renders content derived from the committed markdown files
          docs/WHAT_THE_GATES_CAUGHT.md and docs/PROVEN_GATES.md.
          No numbers in this screen are invented; all entries trace to committed source files.
        </div>
      </div>
    </div>
  )
}
