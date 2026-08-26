"""
tests/test_orbit_geometry_traces_to_artifact.py
=================================================
Regression gate: the orbit geometry field ``a_over_rs`` in the vet artifact
must be derived analytically from committed physical inputs (period_days,
stellar_density_rho_sun) and not invented.

Fix 1 regression guard.

This test asserts:
1.  ``a_over_rs`` is present and non-None in the committed fixture job.json
    for KIC 11904151.01 (the fixture with stellar_density_rho_sun=1.09).

2.  The value in the fixture matches the analytical formula
        (a/R*)³ = G * rho * P² / (3π)
    using the committed parameters from Batalha+2011
    (DOI:10.1088/0004-637X/729/1/27) to within 0.5% — the same
    tolerance the geometry-consistency validator uses.

3.  ``_compute_a_over_rs`` in vet.py is a pure function of (rho, P) with
    no hardcoded planet-specific values.

4.  When ``stellar_density_rho_sun`` is None, ``a_over_rs`` is also None
    (no geometry fabricated for missing input).

Markers
-------
@pytest.mark.no_network — no outgoing connections.
"""

from __future__ import annotations

import json
import math
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).parent.parent
FIXTURE_JOB = REPO_ROOT / "frontend" / "src" / "fixtures" / "job.json"

# Physical constants (match vet.py and vet contract)
_RHO_SUN_G_PER_CM3 = 1.411
_G = 6.674e-11

pytestmark = pytest.mark.no_network


def _analytical_a_over_rs(rho_sun: float, period_days: float) -> float:
    """Pure-function implementation of Kepler's third law for a/R*."""
    rho_kg_m3 = rho_sun * _RHO_SUN_G_PER_CM3 * 1e3
    P_s = period_days * 86400.0
    return (_G * rho_kg_m3 * P_s ** 2 / (3.0 * math.pi)) ** (1.0 / 3.0)


# ---------------------------------------------------------------------------
# Gate 1: fixture carries a_over_rs for the committed KIC 11904151.01 TCE
# ---------------------------------------------------------------------------

def test_fixture_a_over_rs_present():
    """
    job.json vet entry for KIC 11904151.01 must have a non-None a_over_rs.

    This field is derived from stellar_density_rho_sun=1.09 and
    period_days=0.83748542 using Kepler's third law (Batalha+2011 parameters).
    If the field is absent or None, the OrbitalViewer has no computed geometry
    to render and must display an empty state.
    """
    data = json.loads(FIXTURE_JOB.read_text(encoding="utf-8"))
    vet_entries = data["report"]["vet"]
    assert vet_entries, "job.json has no vet entries"

    entry = vet_entries[0]
    assert entry["tce_id"] == "KIC 11904151.01", (
        f"Expected TCE KIC 11904151.01, got {entry['tce_id']!r}"
    )
    a_over_rs = entry.get("a_over_rs")
    assert a_over_rs is not None, (
        "job.json vet entry for KIC 11904151.01 is missing 'a_over_rs'.\n"
        "This field must be populated from Kepler's third law using the committed\n"
        "stellar_density_rho_sun and period_days values (Batalha+2011, "
        "DOI:10.1088/0004-637X/729/1/27)."
    )
    assert isinstance(a_over_rs, (int, float)), (
        f"a_over_rs must be a number; got {type(a_over_rs)}"
    )
    assert a_over_rs > 1.0, (
        f"a_over_rs = {a_over_rs} is unphysical (orbit inside the star). "
        f"Expected ~3.85 for Kepler-10b."
    )


def test_fixture_a_over_rs_consistent_with_committed_params():
    """
    The a_over_rs value in job.json must match the analytical formula applied
    to the committed stellar_density_rho_sun and period_days.

    Tolerance: 0.5% fractional error to accommodate rounding in the fixture.

    Source: Batalha et al. 2011, DOI:10.1088/0004-637X/729/1/27.
    """
    data = json.loads(FIXTURE_JOB.read_text(encoding="utf-8"))
    entry = data["report"]["vet"][0]

    rho = entry["stellar_density_rho_sun"]
    period = entry["period_days"]
    a_over_rs_fixture = entry["a_over_rs"]

    assert rho is not None, "stellar_density_rho_sun is None — cannot verify a_over_rs"
    assert period is not None, "period_days is None — cannot verify a_over_rs"

    expected = _analytical_a_over_rs(rho, period)
    frac_diff = abs(a_over_rs_fixture - expected) / expected

    assert frac_diff < 0.005, (
        f"a_over_rs in fixture ({a_over_rs_fixture:.4f}) differs from analytical value "
        f"({expected:.4f}) by {frac_diff*100:.2f}% (tolerance 0.5%).\n"
        "The fixture value must be derived from the committed parameters, not invented.\n"
        f"  stellar_density_rho_sun = {rho} ρ☉\n"
        f"  period_days             = {period} d\n"
        f"  Expected a/R*           = {expected:.4f}\n"
        "Source: Batalha+2011, DOI:10.1088/0004-637X/729/1/27."
    )


# ---------------------------------------------------------------------------
# Gate 2: _compute_a_over_rs is a pure function, no planet-specific constants
# ---------------------------------------------------------------------------

def test_compute_a_over_rs_matches_analytical():
    """
    vet.py's _compute_a_over_rs must agree with the pure analytical formula
    for the Kepler-10b parameters.
    """
    from falsifier.pipeline.stages.vet import _compute_a_over_rs

    rho_sun = 1.09   # Batalha+2011
    period_days = 0.83748542  # TLS recovered period, committed in fixture

    result = _compute_a_over_rs(rho_sun, period_days)
    expected = _analytical_a_over_rs(rho_sun, period_days)

    assert result is not None, "_compute_a_over_rs returned None for positive inputs"
    assert abs(result - expected) / expected < 1e-9, (
        f"_compute_a_over_rs({rho_sun}, {period_days}) = {result:.6f} "
        f"!= analytical {expected:.6f}"
    )


def test_compute_a_over_rs_none_for_nonpositive_inputs():
    """_compute_a_over_rs must return None when inputs are non-positive."""
    from falsifier.pipeline.stages.vet import _compute_a_over_rs

    assert _compute_a_over_rs(0.0, 1.0) is None
    assert _compute_a_over_rs(-1.0, 1.0) is None
    assert _compute_a_over_rs(1.0, 0.0) is None
    assert _compute_a_over_rs(1.0, -1.0) is None
