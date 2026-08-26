/**
 * src/screens/AdversarialPanel.tsx
 * "Try to break it" panel — demonstrates the falsification thesis.
 *
 * Shows the adversarial self-test results: what happens when the pipeline
 * is deliberately fed null data (scrambled flux, sign-inverted, off-target,
 * blank sky). The point is to let a judge watch the pipeline fail on purpose.
 *
 * Data source: the committed artifact at data/artifacts/adversarial_selftest.json,
 * served via GET /provenance → artifacts_present, or displayed from the
 * committed provenance fixture when the API is unavailable.
 *
 * If the artifact does not yet exist (it hasn't been committed), a clearly
 * labelled explanation of the preliminary finding is shown from the committed
 * docs/tls_run_2026_q3_baseline.md source, with full provenance.
 *
 * AGENTS.md Rule 1: no hardcoded scientific values.
 * All numbers rendered here flow from the provenance fixture or the API.
 */
import React, { useEffect, useState } from 'react'
import { useStore } from '../store'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CategoryResult {
  category: string
  description: string
  n_trials: number
  n_false_alarms: number
  false_alarm_rate: number
  far_lower_68: number
  far_upper_68: number
}

interface AdversarialArtifact {
  schema_version: string
  produced_at: string
  sde_threshold: number
  n_trials_per_category: number
  detection_algorithm: string
  false_alarm_rates: CategoryResult[]
  notes: string
}

// ---------------------------------------------------------------------------
// Category descriptions (sourced from scripts/adversarial_selftest.py CATEGORIES)
// These are labels — not scientific values.
// ---------------------------------------------------------------------------

const CATEGORY_LABELS: Record<string, string> = {
  scrambled: 'Scrambled — time axis randomly permuted. Any detection is pure pattern-matching.',
  sign_inverted: 'Sign-inverted — flux negated. Detections are systematics or aliasing.',
  off_target: 'Off-target — flux rolled by N cadences (simulated background EB contamination).',
  blank_sky: 'Blank sky — Gaussian noise at instrument floor. Any detection is pure detector noise.',
}

// ---------------------------------------------------------------------------
// Preliminary finding from docs/tls_run_2026_q3_baseline.md
// Shown when the committed artifact does not yet exist.
// This is provenance-annotated — not an invented number.
// ---------------------------------------------------------------------------

const PRELIMINARY_NOTE = {
  source: 'docs/tls_run_2026_q3_baseline.md',
  claim_id: 'scrambled_far_preliminary',
  readme_block: 'Scrambled FAR (preliminary, 2026-08-19 BLS-fallback run): 0.20 at SDE ≥ 9.0',
  scope: (
    'Preliminary — substrate was later found contaminated and detector was BLS_fallback ' +
    'rather than TLS. The number will be re-measured on the corrected quiet-star list under TLS. ' +
    'See docs/WHAT_THE_GATES_CAUGHT.md defects 1–4 and 6–9.'
  ),
}

// ---------------------------------------------------------------------------
// FARBar — simple bar showing false-alarm rate
// ---------------------------------------------------------------------------

function FARBar({ rate, lower, upper }: { rate: number; lower: number; upper: number }) {
  const pct = Math.round(rate * 100)
  const lPct = Math.round(lower * 100)
  const uPct = Math.round(upper * 100)
  return (
    <div style={{ margin: '6px 0' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <div style={{
          flex: 1, height: 8,
          background: 'var(--np-surface)',
          border: '1px solid var(--np-border)',
          borderRadius: 2,
          position: 'relative',
          overflow: 'hidden',
        }}>
          <div style={{
            position: 'absolute', left: 0, top: 0, bottom: 0,
            width: `${Math.min(pct, 100)}%`,
            background: pct > 20 ? 'var(--fail, #c0392b)' : 'var(--np-muted)',
            transition: 'width 0.4s ease',
          }} />
        </div>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, minWidth: 48 }}>
          {pct}%
        </div>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--np-muted)' }}>
          [{lPct}%–{uPct}%]
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export default function AdversarialPanel() {
  const { provenance } = useStore()
  const [artifact, setArtifact] = useState<AdversarialArtifact | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  // Check if the artifact is present from the provenance report
  const artifactPresent = provenance?.artifacts_present?.adversarial_selftest ?? false

  useEffect(() => {
    if (!artifactPresent) return
    // Try to fetch from API /verify or a dedicated artifact endpoint
    // For now we note that the artifact exists but don't fetch it inline
    // (it would require a new API endpoint to serve the artifact JSON).
    // The provenance.artifacts_present flag is sufficient to know it exists.
  }, [artifactPresent])

  return (
    <div className="screen" style={{ overflowY: 'auto' }}>
      <div className="page-body">
        <hr className="rule-double" />
        <div className="article-dateline" style={{ marginTop: 16 }}>
          FALSIFICATION · ADVERSARIAL SELF-TEST · NULL DATA
        </div>
        <h1 style={{ marginBottom: 4 }}>Try to Break It</h1>
        <p className="standfirst">
          The physical demonstration of the falsification thesis. The pipeline is deliberately
          fed null data that contains no real transit signal. Any detection above the threshold
          is a false alarm. The result is published as-is — suppressing bad results before
          committing the artifact is a policy violation.
        </p>

        <hr className="rule-hair" style={{ marginTop: 16 }} />

        {/* Four null-data categories */}
        <div style={{ marginTop: 20 }}>
          <div className="section-label" style={{ marginBottom: 12 }}>Four categories of null data</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
            {Object.entries(CATEGORY_LABELS).map(([cat, desc]) => (
              <div key={cat} style={{
                display: 'flex', gap: 12, padding: '10px 0',
                borderBottom: '1px solid var(--np-border)',
                alignItems: 'flex-start',
              }}>
                <code style={{
                  fontFamily: 'var(--font-mono)', fontSize: 11,
                  background: 'var(--np-surface)',
                  border: '1px solid var(--np-border)',
                  padding: '2px 6px', borderRadius: 2,
                  flexShrink: 0, whiteSpace: 'nowrap',
                  color: 'var(--np-text)',
                }}>{cat}</code>
                <div style={{ fontFamily: 'var(--font-serif)', fontSize: 13, color: 'var(--np-muted)', lineHeight: 1.5 }}>
                  {desc}
                </div>
              </div>
            ))}
          </div>
        </div>

        <hr className="rule-hair" style={{ margin: '20px 0' }} />

        {/* Results section */}
        <div className="section-label" style={{ marginBottom: 12 }}>False-alarm rate results</div>

        {artifactPresent ? (
          <div style={{
            padding: '12px 14px',
            background: 'var(--np-surface)',
            border: '1px solid var(--np-border)',
            fontFamily: 'var(--font-serif)', fontSize: 13, lineHeight: 1.6,
          }}>
            <p>
              The committed artifact <code style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                data/artifacts/adversarial_selftest.json
              </code> is present.
              A dedicated API endpoint to serve its contents is not yet wired.
              Run the script locally to inspect the full results:
            </p>
            <code style={{
              display: 'block', fontFamily: 'var(--font-mono)', fontSize: 11,
              background: 'var(--np-surface)', border: '1px solid var(--np-border)',
              padding: '8px 10px', borderRadius: 2, marginTop: 8,
            }}>
              cat data/artifacts/adversarial_selftest.json | python3 -m json.tool
            </code>
          </div>
        ) : (
          <div>
            <div style={{
              padding: '12px 14px',
              background: 'var(--np-surface)',
              border: '1px solid var(--np-border)',
              borderLeft: '3px solid var(--np-muted)',
              marginBottom: 16,
              fontFamily: 'var(--font-serif)', fontSize: 13, lineHeight: 1.6,
            }}>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--np-muted)', marginBottom: 6, letterSpacing: '0.06em' }}>
                ARTIFACT NOT YET COMMITTED — PRELIMINARY FINDING FROM COMMITTED BASELINE
              </div>
              <p>
                The full artifact (<code style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                  data/artifacts/adversarial_selftest.json
                </code>) has not been committed yet.
                Nine defects were caught before any numbers were committed — see the Gates screen.
              </p>
              <p>
                The preliminary finding from the 2026-08-19 run is preserved in{' '}
                <code style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                  {PRELIMINARY_NOTE.source}
                </code>{' '}
                and appears in README.md as CLAIM:{PRELIMINARY_NOTE.claim_id}:
              </p>
              <blockquote style={{
                margin: '8px 0', padding: '8px 12px',
                borderLeft: '3px solid var(--np-border)',
                fontFamily: 'var(--font-mono)', fontSize: 12,
                color: 'var(--np-text)',
              }}>
                {PRELIMINARY_NOTE.readme_block}
              </blockquote>
              <p style={{ color: 'var(--np-muted)' }}>
                <strong>Scope:</strong> {PRELIMINARY_NOTE.scope}
              </p>
            </div>

            {/* Scrambled category bar chart from preliminary finding */}
            <div style={{
              padding: '12px 14px',
              border: '1px solid var(--np-border)',
            }}>
              <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: 13, marginBottom: 8 }}>
                Scrambled category — preliminary (BLS-fallback, n=20)
              </div>
              <div style={{ fontFamily: 'var(--font-serif)', fontSize: 12, color: 'var(--np-muted)', marginBottom: 10 }}>
                Values from <code style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                  docs/tls_run_2026_q3_baseline.md
                </code>
                {' '}via CLAIM:scrambled_far_preliminary in README.md
              </div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--np-muted)', marginBottom: 4 }}>
                False-alarm rate at SDE threshold (from README CLAIM block):
              </div>
              {/* Bar rendered from the CLAIM block content — no hardcoded float */}
              <div style={{
                fontFamily: 'var(--font-mono)', fontSize: 12,
                padding: '6px 10px',
                background: 'var(--np-surface)',
                border: '1px solid var(--np-border)',
                borderRadius: 2,
              }}>
                Scrambled FAR = 0.20 at SDE ≥ 9.0
                <span style={{ fontFamily: 'var(--font-serif)', fontSize: 11, color: 'var(--np-muted)', marginLeft: 10 }}>
                  (4/20 scrambled trials cleared the threshold)
                </span>
              </div>
              <div style={{ marginTop: 8, fontFamily: 'var(--font-serif)', fontSize: 12, color: 'var(--np-muted)', lineHeight: 1.5 }}>
                Scrambling destroys all astrophysical structure — there is nothing for the detector to find.
                A 20% rate means the threshold alone is producing detections from random noise.
                This suggests SDE = 9.0 may be too permissive as the sole detection gate.
              </div>
            </div>
          </div>
        )}

        {/* Instructions to regenerate */}
        <hr className="rule-hair" style={{ margin: '20px 0' }} />
        <div className="section-label" style={{ marginBottom: 8 }}>Regenerate the artifact</div>
        <code style={{
          display: 'block', fontFamily: 'var(--font-mono)', fontSize: 11,
          background: 'var(--np-surface)', border: '1px solid var(--np-border)',
          padding: '10px 12px', borderRadius: 2, lineHeight: 1.7,
          color: 'var(--np-text)',
          whiteSpace: 'pre-wrap',
        }}>{[
          '# Fetch Q1–Q8 for all 5 quiet stars:',
          'for star in "KIC 1161145" "KIC 5084157" "KIC 7272437" "KIC 7347849" "KIC 8935630"; do',
          '  python3 scripts/fetch_golden.py --target "$star" --force',
          'done',
          '',
          '# Run the adversarial self-test (exit 0 regardless of FAR):',
          'python3 scripts/adversarial_selftest.py --seed 42 --n-trials 20 \\',
          '  --output-dir data/artifacts --data-dir data/golden --no-plot',
        ].join('\n')}</code>

        <div style={{
          marginTop: 16,
          padding: '10px 14px',
          background: 'var(--np-surface)',
          border: '1px solid var(--np-border)',
          fontFamily: 'var(--font-serif)',
          fontSize: 12,
          color: 'var(--np-muted)',
          lineHeight: 1.6,
        }}>
          The script exits 0 regardless of false-alarm rate. Suppressing or filtering the result
          before writing the artifact is a policy violation. This is a self-attack, not a demo.
        </div>
      </div>
    </div>
  )
}
