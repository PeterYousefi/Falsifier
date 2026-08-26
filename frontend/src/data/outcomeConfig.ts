/**
 * src/data/outcomeConfig.ts
 * Single source of truth for outcome-to-copy mapping.
 *
 * AGENTS.md Rule 1: no scientific literals.  Every string here is UI copy,
 * not a measured value.
 *
 * Exhaustiveness contract
 * -----------------------
 * OUTCOME_COPY is typed as Record<VettingTestOutcome, ...>.  TypeScript will
 * produce a compile error if a fifth enum member is added to VettingTestOutcome
 * without a corresponding entry here.  The Python policy test
 * tests/test_fixtures_satisfy_contracts.py asserts the same set at CI time.
 *
 * Usage
 * -----
 *   const cfg = OUTCOME_COPY[outcome]
 *   // cfg.chipLabel, cfg.colorClass, cfg.standfirst(reason)
 *
 * Never compare outcome strings with === in JSX.  Always index this map.
 */

import type { VettingTestOutcome } from './types'

export interface OutcomeCopy {
  /** Text displayed inside the status chip. */
  chipLabel: string
  /** CSS class applied to the chip (matches styles.css .vet-badge variants). */
  colorClass: string
  /**
   * User-facing sentence for the verdict card / report standfirst.
   * @param reason - the VettingTestResult.reason string from the artifact.
   */
  standfirst: (reason: string) => string
}

export const OUTCOME_COPY: Record<VettingTestOutcome, OutcomeCopy> = {
  PASS: {
    chipLabel: 'PASS',
    colorClass: 'PASS',
    standfirst: (_reason: string) =>
      'This test returned negative: no false-positive fingerprint detected.',
  },
  FAIL: {
    chipLabel: 'FAIL',
    colorClass: 'FAIL',
    standfirst: (reason: string) =>
      reason
        ? `Rejected: ${reason}`
        : 'This test triggered a hard rejection.',
  },
  FLAG: {
    chipLabel: 'FLAG',
    colorClass: 'FLAG',
    standfirst: (reason: string) =>
      reason
        ? `Soft flag raised: ${reason} The candidate passes this test but the result warrants attention.`
        : 'A soft flag was raised. The candidate passes but warrants attention.',
  },
  INCONCLUSIVE: {
    chipLabel: 'NOT EVALUATED',
    colorClass: 'INCONCLUSIVE',
    standfirst: (reason: string) =>
      reason
        ? `This test could not be evaluated: ${reason}`
        : 'This test could not be evaluated — no data available.',
  },
}

/**
 * Produce the verdict-card standfirst sentence for a VetResult.
 *
 * Replaces the inline ternary chain that previously compared disposition
 * strings in SystemScreen.tsx and CandidateDetail.tsx.
 *
 * Rules:
 *  - "raised a flag" language appears ONLY for candidate_with_caveats
 *  - "could not be evaluated" appears ONLY for ambiguous
 *  - Never uses "challenged" for INCONCLUSIVE outcomes
 */
export function dispositionStandfirst(vet: {
  disposition: string
  triggering_test: string | null
  triggering_reason: string | null
  test_results?: { outcome: string }[] | null
}): string {
  const d = vet.disposition
  const n = vet.test_results?.length ?? 0

  if (d === 'candidate') {
    return `All ${n} automated tests returned negative.`
  }
  if (d === 'false_positive') {
    return vet.triggering_reason
      ? `Rejected: ${vet.triggering_reason}`
      : 'Rejected by automated vetting.'
  }
  if (d === 'candidate_with_caveats') {
    return vet.triggering_reason
      ? `Passes most tests but a soft flag was raised: ${vet.triggering_reason}`
      : 'Passes most tests but one or more soft flags were raised.'
  }
  if (d === 'ambiguous') {
    return vet.triggering_reason
      ? `One or more tests could not be evaluated — the result is ambiguous pending additional data. (${vet.triggering_reason})`
      : 'One or more tests could not be evaluated — the result is ambiguous pending additional data.'
  }
  // Unknown disposition — surface the raw value rather than falling silent
  return `Disposition: ${d}`
}
