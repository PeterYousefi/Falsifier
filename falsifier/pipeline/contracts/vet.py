"""
falsifier.pipeline.contracts.vet
==================================
Pydantic contracts for the vet pipeline stage.

  VettingTestOutcome — PASS | FAIL | FLAG | INCONCLUSIVE
  VettingTestName    — seven load-bearing canonical identifiers
  VettingTestResult  — one test's result + metric + reason
  Disposition        — deterministic classification of a TCE
  VetInput           — per-TCE request
  VetOutput          — the complete, self-contained disposition record

Policy
------
Disposition lives here and nowhere else.  The truth table is enforced as
Pydantic validators so any code that constructs a VetOutput with an
inconsistent disposition fails at object-creation time:

  All seven PASS               → candidate
  Any FAIL                     → false_positive   (first FAIL triggers)
  No FAIL + any FLAG           → candidate_with_caveats  (first FLAG triggers)
  No FAIL + no FLAG + any INC  → ambiguous        (first INCONCLUSIVE triggers)

ClassifyOutput must never restate or override this disposition.
"""

from __future__ import annotations

import datetime
import math
from typing import Literal

from pydantic import BaseModel, field_validator, model_validator

from .manifest import ArtifactRef, DatasetProvenance, StageManifest

# ---------------------------------------------------------------------------
# Transit geometry closure constant
# ---------------------------------------------------------------------------

# Solar mean density in g/cm³ (IAU 2015 nominal solar mass 1.98892e30 kg,
# radius 6.957e8 m).  Used to convert rho_sun → g/cm³ when checking geometry.
_RHO_SUN_G_PER_CM3: float = 1.411

__all__ = [
    "VettingTestOutcome",
    "VettingTestName",
    "VettingTestResult",
    "Disposition",
    "VetInput",
    "VetOutput",
]

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

VettingTestOutcome = Literal["PASS", "FAIL", "FLAG", "INCONCLUSIVE"]
"""
Four-valued outcome for each vetting test:
  PASS         — test passed cleanly
  FAIL         — hard rejection gate triggered
  FLAG         — soft caution (passes the gate but warrants annotation)
  INCONCLUSIVE — test could not determine an outcome
"""

VettingTestName = Literal[
    "odd_even_depth",
    "secondary_eclipse",
    "centroid_shift",
    "transit_shape",
    "stellar_density",
    "gaia_ruwe",
    "systematics_coincidence",
]
"""
Seven canonical, load-bearing vetting test names.

These strings appear in the golden EB test (``tests/test_known_eb_rejected.py``)
and are asserted on by name.  Do NOT rename them without updating:
  - tests/test_known_eb_rejected.py (EXPECTED_TRIGGERING_TEST)
  - docs/PROVEN_GATES.md (gate 2 section)
  - pipeline-contracts-plan.md (Sub-Task 5, step 3)
"""

# Canonical ordering — used to validate that exactly one result exists per test
VETTING_TEST_ORDER: tuple[str, ...] = (
    "odd_even_depth",
    "secondary_eclipse",
    "centroid_shift",
    "transit_shape",
    "stellar_density",
    "gaia_ruwe",
    "systematics_coincidence",
)

Disposition = Literal[
    "candidate",
    "candidate_with_caveats",
    "false_positive",
    "ambiguous",
]
"""
Deterministic classification of a TCE, computed from the seven vetting tests.
This value lives exclusively in VetOutput.  No downstream stage may override it.
"""


# ---------------------------------------------------------------------------
# VettingTestResult
# ---------------------------------------------------------------------------

class VettingTestResult(BaseModel):
    """Result of one vetting test for one TCE."""

    test_name: VettingTestName
    """Typed to the load-bearing Literal; unknown names fail at construction."""

    outcome: VettingTestOutcome

    metric_value: float | None = None
    """The scalar metric the test evaluated, if applicable (e.g. RUWE = 1.42)."""

    metric_unit: str | None = None
    """Unit string, ``"dimensionless"``, or ``None`` if no metric applies."""

    reason: str
    """Required, non-empty one-sentence human-readable explanation."""

    @field_validator("reason")
    @classmethod
    def _reason_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("VettingTestResult.reason must be a non-empty string")
        return v


# ---------------------------------------------------------------------------
# VetInput
# ---------------------------------------------------------------------------

class VetInput(BaseModel):
    """Per-TCE request to the vet stage."""

    search_artifact: ArtifactRef
    """Points to the SearchOutput that contains this TCE."""

    tce_id: str
    """One TCE per VetInput.  Vet runs per-TCE, not per-star."""

    pipeline_run_id: str


# ---------------------------------------------------------------------------
# VetOutput
# ---------------------------------------------------------------------------

class VetOutput(BaseModel):
    """
    Complete, self-contained disposition record for one TCE.

    The ``disposition`` field is the only authoritative verdict; it is
    computed deterministically from ``test_results`` and validated at
    construction.  The "API-deletion test": if the classifier and its API
    were deleted, this record alone must constitute a defensible scientific
    result.
    """

    input: VetInput
    tce_id: str
    host_star_id: str

    test_results: list[VettingTestResult]
    """Exactly seven entries, one per canonical test, in VETTING_TEST_ORDER."""

    disposition: Disposition

    triggering_test: VettingTestName | None
    """
    The test whose outcome determined the disposition.
    None only when disposition == "candidate" (all seven PASS).
    Typed to VettingTestName so unknown names are rejected at construction.
    """

    triggering_reason: str | None
    """The reason string from the triggering test.  None only for "candidate"."""

    # ------------------------------------------------------------------
    # Optional physical geometry fields.
    # When provided, they are validated for mutual consistency by
    # _geometry_consistent().  A None value means "not determined".
    # ------------------------------------------------------------------

    period_days: float | None = None
    """Orbital period in days.  Must be positive when provided."""

    duration_hours: float | None = None
    """Total transit duration T14 in hours (first to fourth contact).  Must be positive."""

    inclination_deg: float | None = None
    """Orbital inclination in degrees, range [0, 90]."""

    stellar_density_rho_sun: float | None = None
    """
    Photometric stellar density from transit geometry in solar density units (ρ☉).
    1 ρ☉ = 1.411 g/cm³.  Must NOT be populated with g/cm³ values labelled as ρ☉.
    When provided together with period_days, duration_hours, and inclination_deg,
    the four values are checked for mutual consistency (see _geometry_consistent).
    """

    rp_rs: float | None = None
    """Planet-to-star radius ratio Rp/Rs (dimensionless).  Range (0, 1) when provided."""

    manifest: StageManifest
    artifact: ArtifactRef

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------

    @field_validator("test_results")
    @classmethod
    def _exactly_seven(cls, v: list[VettingTestResult]) -> list[VettingTestResult]:
        if len(v) != 7:
            found = [r.test_name for r in v]
            expected = set(VETTING_TEST_ORDER)
            present = {r.test_name for r in v}
            missing = expected - present
            extra = present - expected
            msg = f"test_results must contain exactly 7 entries; got {len(v)}."
            if missing:
                msg += f" Missing: {sorted(missing)}."
            if extra:
                msg += f" Extra: {sorted(extra)}."
            raise ValueError(msg)
        return v

    @model_validator(mode="after")
    def _disposition_consistent(self) -> "VetOutput":
        results = self.test_results

        # Compute the expected disposition from the outcomes
        outcomes = {r.test_name: r.outcome for r in results}

        # Priority 1: any FAIL → false_positive
        first_fail = next(
            (r for r in results if r.outcome == "FAIL"), None
        )
        if first_fail is not None:
            expected = "false_positive"
            trig_test: VettingTestName | None = first_fail.test_name  # type: ignore[assignment]
            trig_reason: str | None = first_fail.reason
        else:
            # Priority 2: no FAIL + any FLAG → candidate_with_caveats
            first_flag = next(
                (r for r in results if r.outcome == "FLAG"), None
            )
            if first_flag is not None:
                expected = "candidate_with_caveats"
                trig_test = first_flag.test_name  # type: ignore[assignment]
                trig_reason = first_flag.reason
            else:
                # Priority 3: any INCONCLUSIVE → ambiguous
                first_inc = next(
                    (r for r in results if r.outcome == "INCONCLUSIVE"), None
                )
                if first_inc is not None:
                    expected = "ambiguous"
                    trig_test = first_inc.test_name  # type: ignore[assignment]
                    trig_reason = first_inc.reason
                else:
                    # All PASS
                    expected = "candidate"
                    trig_test = None
                    trig_reason = None

        if self.disposition != expected:
            raise ValueError(
                f"VetOutput.disposition is inconsistent with test_results.\n"
                f"  Declared  : {self.disposition!r}\n"
                f"  Computed  : {expected!r}\n"
                f"  Outcomes  : "
                + ", ".join(f"{r.test_name}={r.outcome}" for r in results)
            )

        # Validate triggering_test / triggering_reason coherence
        if expected == "candidate":
            if self.triggering_test is not None or self.triggering_reason is not None:
                raise ValueError(
                    "disposition == 'candidate' requires triggering_test == None "
                    "and triggering_reason == None"
                )
        else:
            if self.triggering_test is None or self.triggering_reason is None:
                raise ValueError(
                    f"disposition == {self.disposition!r} requires both "
                    "triggering_test and triggering_reason to be non-None"
                )

        return self

    @model_validator(mode="after")
    def _geometry_consistent(self) -> "VetOutput":
        """
        Assert that (rho, i, duration, period) are mutually consistent within
        tolerance when all four are provided.

        Physics
        -------
        For a circular orbit the normalised semi-major axis a/R* satisfies
        Kepler's third law:

            (a/R*)³ = (G/(3π)) * rho * P²

        where rho is the stellar mean density in SI units.  The transit
        duration T14 (first-to-fourth contact) satisfies:

            sin(T14 * π / P) = (a/R*) * cos(i) / sqrt(1 - (a/R * cos(i))^2)
            (small-angle form for large a/R*):
            T14 ≈ P/π * arcsin(sqrt(((1 + k)^2 - (a/R* cos i)^2) / (a/R*)^2))

        where k = Rp/Rs.  When Rp/Rs is unknown we use k=0 (point-transit
        approximation), which underestimates T14 slightly but is adequate for
        the closure check.

        Tolerance: 15% fractional difference on T14 accommodates the k=0
        approximation, eccentricity (circular assumption), and limb-darkening
        effects on apparent T14.

        The validator only runs when all four of rho, period, duration,
        inclination are non-None.  Absence of any one silently skips the check
        (the pipeline may not have determined all quantities for every TCE).
        """
        rho = self.stellar_density_rho_sun
        P   = self.period_days
        T14 = self.duration_hours
        inc = self.inclination_deg
        k   = self.rp_rs if self.rp_rs is not None else 0.0

        if any(x is None for x in (rho, P, T14, inc)):
            return self  # incomplete — skip the check

        assert rho is not None and P is not None and T14 is not None and inc is not None

        if rho <= 0 or P <= 0 or T14 <= 0:
            raise ValueError(
                f"VetOutput geometry fields must be positive: "
                f"stellar_density_rho_sun={rho}, period_days={P}, duration_hours={T14}"
            )
        if not (0.0 <= inc <= 90.0):
            raise ValueError(
                f"VetOutput.inclination_deg must be in [0, 90], got {inc}"
            )

        # Convert rho from ρ☉ to kg/m³ for Kepler's third law
        rho_kg_m3 = rho * _RHO_SUN_G_PER_CM3 * 1e3  # g/cm³ → kg/m³
        P_s = P * 86400.0  # days → seconds
        G = 6.674e-11  # m³ kg⁻¹ s⁻²

        # a/R* from Kepler's third law (circular orbit)
        a_over_Rs = (G * rho_kg_m3 * P_s ** 2 / (3.0 * math.pi)) ** (1.0 / 3.0)

        if a_over_Rs < 1.0:
            # Unphysical — orbit inside the star.  Geometry is incoherent.
            raise ValueError(
                f"VetOutput geometry is unphysical: computed a/R* = {a_over_Rs:.3f} < 1 "
                f"(orbit inside the star).\n"
                f"  stellar_density_rho_sun = {rho:.4f} ρ☉\n"
                f"  period_days             = {P:.6f} d\n"
                "Check that stellar_density_rho_sun is in ρ☉ (solar density units), "
                "not in g/cm³."
            )

        i_rad = math.radians(inc)
        b = a_over_Rs * math.cos(i_rad)  # impact parameter

        # For b >= (1 + k) there is no transit at all
        if b >= (1.0 + k):
            raise ValueError(
                f"VetOutput geometry predicts no transit: impact parameter b = {b:.4f} "
                f">= 1 + k = {1.0 + k:.4f}.\n"
                f"  stellar_density_rho_sun = {rho:.4f} ρ☉\n"
                f"  inclination_deg         = {inc:.2f} °\n"
                f"  period_days             = {P:.6f} d"
            )

        # Expected T14 in hours (small-angle approximation, circular orbit)
        inner = max(0.0, ((1.0 + k) ** 2 - b ** 2))
        T14_expected_h = (P * 24.0 / math.pi) * math.asin(math.sqrt(inner) / a_over_Rs)

        # Allow 15% fractional tolerance
        tol = 0.15
        frac_diff = abs(T14 - T14_expected_h) / T14_expected_h

        if frac_diff > tol:
            raise ValueError(
                f"VetOutput geometry does not close: observed T14 and the triplet "
                f"(rho, i, P) are inconsistent beyond {tol*100:.0f}% tolerance.\n"
                f"  Observed T14                = {T14:.4f} h\n"
                f"  Expected T14 from geometry  = {T14_expected_h:.4f} h\n"
                f"  Fractional difference       = {frac_diff*100:.1f}%\n"
                f"  stellar_density_rho_sun     = {rho:.4f} ρ☉\n"
                f"  period_days                 = {P:.6f} d\n"
                f"  inclination_deg             = {inc:.2f} °\n"
                f"  a/R*                        = {a_over_Rs:.4f}\n"
                f"  impact parameter b          = {b:.4f}\n"
                "Ensure stellar_density_rho_sun is in ρ☉ units (not g/cm³). "
                "If the orbit is eccentric, provide all four fields only when "
                "the circular approximation is valid."
            )

        return self
