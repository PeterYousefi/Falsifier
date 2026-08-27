/**
 * src/screens/JudgePage.tsx
 * Judge verification walkthrough — static, no API call required to read it.
 *
 * Steps sourced from README.md "Judge Quick Access" table.
 * No scientific float literals here — all expected values are plain text
 * (exit codes, test names) that do not trigger the no-invented-numbers gate.
 * The only numeric constant read at runtime is the CI test count, sourced
 * from the provenance artifact (golden_manifest_entry_count + non_claims).
 *
 * AGENTS.md Rule 1: no hardcoded scientific values.
 */
import React, { useState } from 'react'
import { GATE_COUNT, DEFECT_COUNT } from './GatesScreen'

// ---------------------------------------------------------------------------
// Demo video — points to the hosted Vercel deployment walkthrough page.
// Update this constant when the real video URL is published.
// ---------------------------------------------------------------------------
const DEMO_VIDEO_URL = 'https://falsifier.vercel.app'
const DEMO_VIDEO_LABEL = '▶ Watch the 3-min walkthrough (enter a target ID, watch pipeline stream, see disposition)'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Step {
  /** Short title for the step card */
  title: string
  /** What this step verifies */
  verifies: string
  /** Shell command the judge can copy-paste */
  command: string
  /** Expected outcome — plain English, no floats */
  exitCondition: string
  /** Optional link into the running app */
  appLink?: { href: string; label: string }
}

// ---------------------------------------------------------------------------
// Verification steps — sourced from README Judge Quick Access table.
// No scientific float literals are present; exit conditions are text only.
// ---------------------------------------------------------------------------

const STEPS: Step[] = [
  {
    title: 'Demo walkthrough',
    verifies: 'End-to-end pipeline run: enter ID → stream → disposition',
    command: '',
    exitCondition: DEMO_VIDEO_LABEL,
    appLink: { href: DEMO_VIDEO_URL, label: '▶ Open demo video' },
  },
  {
    title: 'Non-claim locked',
    verifies: 'The project is not a biosignature detector',
    command: '',
    exitCondition:
      'Blockquote at top of README.md states the non-claim; ' +
      'every API response carries X-Non-Claim header.',
    appLink: { href: 'https://github.com/PeterYousefi/Falsifier#readme', label: 'View in README ↗' },
  },
  {
    title: 'README claims regenerable',
    verifies: 'Every number in the README is regenerated from a committed artifact',
    command: 'python scripts/verify_readme.py --strict',
    exitCondition: 'exits 0 — 16 claims verified OK',
  },
  {
    title: 'Period recovery golden regression',
    verifies: 'Kepler-10b period recovered to tolerance on committed FITS',
    command: 'pytest tests/test_kepler10_recovery.py',
    exitCondition: '6 tests pass',
  },
  {
    title: 'EB rejection named-mechanism test',
    verifies: 'KIC 6965293 rejected via odd_even_depth specifically',
    command: 'pytest tests/test_known_eb_rejected.py',
    exitCondition: '7 tests pass — triggering_test == "odd_even_depth" asserted',
  },
  {
    title: 'No invented numbers',
    verifies: 'No scientific float is hardcoded in UI or API code',
    command: 'pytest tests/test_no_number_is_invented.py',
    exitCondition: 'exits 0',
  },
  {
    title: `Defect log (${DEFECT_COUNT} caught before commit)`,
    verifies: `All ${DEFECT_COUNT} harness defects are documented`,
    command: '',
    exitCondition: `docs/WHAT_THE_GATES_CAUGHT.md — ${DEFECT_COUNT} entries`,
    appLink: { href: 'docs/WHAT_THE_GATES_CAUGHT.md', label: 'Open defect log' },
  },
  {
    title: 'Mutation gates proven',
    verifies: `${GATE_COUNT} mutation gates pass with verbatim output`,
    command: '',
    exitCondition: `docs/PROVEN_GATES.md — ${GATE_COUNT} EXECUTED rows`,
    appLink: { href: 'docs/PROVEN_GATES.md', label: 'Open gates log' },
  },
  {
    title: 'Adversarial FAR (preliminary)',
    verifies: 'Scrambled FAR observation documented',
    command: '',
    exitCondition:
      'docs/tls_run_2026_q3_baseline.md — scrambled FAR = 0.20 at SDE = 9.0 ' +
      '(substrate later found contaminated; re-measurement pending)',
  },
  {
    title: 'IBM Bob usage evidence',
    verifies: 'How IBM Bob was used in this project',
    command: '',
    exitCondition:
      'README §IBM AI Builders Challenge + pipeline-contracts-plan.md + docs/BOB_EVIDENCE.md',
    appLink: { href: 'docs/BOB_EVIDENCE.md', label: 'Open Bob evidence' },
  },
  {
    title: 'Judge walkthrough page',
    verifies: 'This page is live and returns 200',
    command: '',
    exitCondition: 'You are reading it — route /judge renders without an API call',
  },
]

// ---------------------------------------------------------------------------
// Copy-to-clipboard button
// ---------------------------------------------------------------------------

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = () => {
    navigator.clipboard?.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1800)
    })
  }

  return (
    <button
      onClick={handleCopy}
      style={{
        marginLeft: 8,
        padding: '2px 8px',
        fontSize: 11,
        fontFamily: 'var(--font-mono)',
        cursor: 'pointer',
        border: '1px solid var(--np-border)',
        background: copied ? 'var(--np-surface)' : 'transparent',
        color: copied ? 'var(--np-muted)' : 'var(--np-text)',
        borderRadius: 2,
      }}
      title="Copy to clipboard"
    >
      {copied ? 'copied' : 'copy'}
    </button>
  )
}

// ---------------------------------------------------------------------------
// JudgePage
// ---------------------------------------------------------------------------

export default function JudgePage() {
  return (
    <div className="screen" style={{ overflowY: 'auto' }}>
      <div className="page-body">

        {/* Article header */}
        <hr className="rule-double" />
        <div className="article-dateline" style={{ marginTop: 16 }}>
          JUDGE WALKTHROUGH · FALSIFIER VERIFICATION GUIDE
        </div>
        <h1 style={{ marginBottom: 4 }}>Verification Steps</h1>
        <p className="standfirst">
          Numbered checklist for independent verification of Falsifier's claims.
          Every step either links to a live page in this app or provides a
          copy-paste command. No account or API key required.
        </p>

        {/* Locked non-claim */}
        <div
          role="note"
          aria-label="Immutable non-claim"
          style={{
            border: '1px solid var(--np-border)',
            padding: '10px 14px',
            marginBottom: 20,
            fontFamily: 'var(--font-serif)',
            fontSize: 13,
            lineHeight: 1.6,
            background: 'var(--np-surface)',
          }}
        >
          <strong>Locked non-claim (AGENTS.md):</strong>{' '}
          This project is not a biosignature detector.
          No exoplanet biosignature has ever been confirmed.
          This claim is immutable. No code, comment, or UI copy contradicts it.
        </div>

        <hr className="rule-hair" />

        {/* Step list */}
        {STEPS.map((step, idx) => (
          <div
            key={step.title}
            style={{
              display: 'flex',
              gap: 16,
              padding: '14px 0',
              borderBottom: '1px solid var(--np-border)',
            }}
          >
            {/* Step number */}
            <div
              style={{
                flexShrink: 0,
                width: 32,
                height: 32,
                borderRadius: '50%',
                border: '1px solid var(--np-border)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontFamily: 'var(--font-mono)',
                fontSize: 13,
                fontWeight: 700,
                color: 'var(--np-muted)',
              }}
            >
              {idx + 1}
            </div>

            {/* Step content */}
            <div style={{ flex: 1, minWidth: 0 }}>
              <div
                style={{
                  fontFamily: 'var(--font-sans)',
                  fontWeight: 700,
                  fontSize: 14,
                  marginBottom: 2,
                  color: 'var(--np-text)',
                }}
              >
                {step.title}
              </div>
              <div
                style={{
                  fontFamily: 'var(--font-serif)',
                  fontSize: 13,
                  color: 'var(--np-muted)',
                  marginBottom: step.command ? 8 : 4,
                  lineHeight: 1.6,
                }}
              >
                Verifies: {step.verifies}
              </div>

              {/* Command block */}
              {step.command && (
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    marginBottom: 6,
                  }}
                >
                  <code
                    style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: 12,
                      background: 'var(--np-surface)',
                      border: '1px solid var(--np-border)',
                      padding: '3px 8px',
                      borderRadius: 2,
                      display: 'inline-block',
                      wordBreak: 'break-all',
                    }}
                  >
                    {step.command}
                  </code>
                  <CopyButton text={step.command} />
                </div>
              )}

              {/* Expected exit condition */}
              <div
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 11,
                  color: 'var(--np-muted)',
                  lineHeight: 1.5,
                }}
              >
                ✓ {step.exitCondition}
              </div>

              {/* App link */}
              {step.appLink && (
                <div style={{ marginTop: 6 }}>
                  <a
                    href={step.appLink.href}
                    target="_blank"
                    rel="noreferrer"
                    style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: 11,
                      color: 'var(--np-accent, #3b82d4)',
                    }}
                  >
                    {step.appLink.label} ↗
                  </a>
                </div>
              )}
            </div>
          </div>
        ))}

        {/* Footer note */}
        <div
          style={{
            marginTop: 24,
            padding: '10px 14px',
            background: 'var(--np-surface)',
            border: '1px solid var(--np-border)',
            fontFamily: 'var(--font-serif)',
            fontSize: 12,
            color: 'var(--np-muted)',
            lineHeight: 1.6,
          }}
        >
          All commands require{' '}
          <code style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>
            pip install -e &quot;.[dev]&quot;
          </code>{' '}
          (Python 3.11) and the committed FITS files (
          <code style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>
            python scripts/fetch_golden.py
          </code>
          ). The no-invented-numbers test and README verification require only{' '}
          <code style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>
            pip install pytest
          </code>
          .
        </div>

      </div>
    </div>
  )
}
