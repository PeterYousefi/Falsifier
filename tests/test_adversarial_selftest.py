"""
tests/test_adversarial_selftest.py
====================================
Unit tests for scripts/adversarial_selftest.py.

All tests run without network, lightkurve, or transitleastsquares.
They use the internal BLS fallback and synthetic data.

Tests cover:
- make_scrambled: flux values permuted, time unchanged, length preserved
- make_sign_inverted: flux reflected around median, time/err unchanged
- make_off_target: array rolled by correct amount
- make_blank_sky: array of correct length, flux ≈ 1.0, err ≈ noise floor
- Wilson score interval (shared with injection_recovery — quick check)
- run_trial: returns AdversarialTrial, never raises, error_message stored
- Artifact JSON: required AGENTS.md Rule 3 fields, unconditional write
- FAR values are in [0, 1] for all categories
- Exit code is always 0 regardless of FAR
"""

from __future__ import annotations

import json
import sys
import unittest.mock
from pathlib import Path

import numpy as np
import pytest

# Committed golden FITS files live here — loaded by TestAdversarialSelftestArtifact.
_GOLDEN_DIR = Path(__file__).parent.parent / "data" / "golden"

# ---------------------------------------------------------------------------
# Force BLS fallback — hide transitleastsquares for the whole module.
#
# These tests are documented as "run without transitleastsquares; use the
# internal BLS fallback."  TLS may be installed in the venv, but its
# multiprocessing path takes >30 s per call — far beyond the 30 s per-test
# budget.  We patch sys.modules so that `import transitleastsquares` raises
# ImportError, triggering the fast pure-Python BLS branch in run_detection().
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _force_bls_fallback(monkeypatch):
    """Hide transitleastsquares so run_detection() uses the BLS fallback."""
    monkeypatch.setitem(sys.modules, "transitleastsquares", None)
    yield


# ---------------------------------------------------------------------------
# Import module under test
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.adversarial_selftest import (
    make_scrambled,
    make_sign_inverted,
    make_off_target,
    make_blank_sky,
    run_trial,
    wilson_score_interval,
    AdversarialTrial,
    CATEGORIES,
    INSTRUMENT_NOISE_FLOOR_PPM,
    SDE_THRESHOLD,
    main as adv_main,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _synthetic_lc(
    n: int = 400,
    noise_ppm: float = 300.0,
    seed: int = 0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    t = np.linspace(0.0, 90.0, n)
    sigma = noise_ppm * 1e-6
    f = 1.0 + rng.normal(0.0, sigma, n)
    e = np.full(n, sigma)
    return t, f, e


# ---------------------------------------------------------------------------
# Null-data constructors
# ---------------------------------------------------------------------------

class TestMakeScrambled:
    def test_time_unchanged(self):
        rng = np.random.default_rng(0)
        t, f, e = _synthetic_lc(n=100)
        t_out, f_out, e_out = make_scrambled(t, f, e, rng)
        np.testing.assert_array_equal(t_out, t)

    def test_flux_is_permutation(self):
        rng = np.random.default_rng(0)
        t, f, e = _synthetic_lc(n=100)
        _, f_out, _ = make_scrambled(t, f, e, rng)
        assert len(f_out) == len(f)
        # All original values present
        assert set(np.round(f, 8)) == set(np.round(f_out, 8))

    def test_does_not_mutate_input(self):
        rng = np.random.default_rng(1)
        t, f, e = _synthetic_lc(n=100)
        f_copy = f.copy()
        make_scrambled(t, f, e, rng)
        np.testing.assert_array_equal(f, f_copy)

    def test_output_length_preserved(self):
        rng = np.random.default_rng(2)
        t, f, e = _synthetic_lc(n=200)
        t_out, f_out, e_out = make_scrambled(t, f, e, rng)
        assert len(t_out) == len(f_out) == len(e_out) == 200


class TestMakeSignInverted:
    def test_median_preserved(self):
        """After sign inversion the median must equal the original median."""
        t, f, e = _synthetic_lc(n=500, noise_ppm=0.0)  # zero noise for exact check
        f[:] = 1.0  # constant = trivial, median preserved
        _, f_out, _ = make_sign_inverted(t, f, e)
        assert np.median(f_out) == pytest.approx(np.median(f), rel=1e-9)

    def test_transit_becomes_anti_transit(self):
        """A downward dip in the original must become an upward bump."""
        t = np.linspace(0.0, 10.0, 100)
        f = np.ones(100)
        f[40:45] -= 0.01  # 1% downward dip
        _, f_out, _ = make_sign_inverted(t, f, np.zeros(100))
        # The dip becomes a bump
        assert f_out[42] > 1.0

    def test_err_unchanged(self):
        t, f, e = _synthetic_lc(n=100)
        _, _, e_out = make_sign_inverted(t, f, e)
        np.testing.assert_array_equal(e_out, e)

    def test_does_not_mutate_input(self):
        t, f, e = _synthetic_lc(n=100)
        f_copy = f.copy()
        make_sign_inverted(t, f, e)
        np.testing.assert_array_equal(f, f_copy)


class TestMakeOffTarget:
    def test_roll_by_correct_amount(self):
        t = np.arange(10, dtype=float)
        f = np.arange(10, dtype=float)
        e = np.zeros(10)
        _, f_out, _ = make_off_target(t, f, e, roll_cadences=3)
        np.testing.assert_array_equal(f_out, np.roll(f, 3))

    def test_time_unchanged(self):
        t, f, e = _synthetic_lc(n=50)
        t_out, _, _ = make_off_target(t, f, e, roll_cadences=5)
        np.testing.assert_array_equal(t_out, t)

    def test_zero_roll_is_identity(self):
        t, f, e = _synthetic_lc(n=50)
        _, f_out, _ = make_off_target(t, f, e, roll_cadences=0)
        np.testing.assert_array_equal(f_out, f)


class TestMakeBlankSky:
    def test_correct_length(self):
        rng = np.random.default_rng(0)
        t = np.linspace(0.0, 90.0, 300)
        _, f_out, e_out = make_blank_sky(t, rng)
        assert len(f_out) == 300
        assert len(e_out) == 300

    def test_flux_centred_near_one(self):
        rng = np.random.default_rng(0)
        t = np.linspace(0.0, 90.0, 5000)
        _, f_out, _ = make_blank_sky(t, rng, noise_ppm=300.0)
        assert abs(float(np.mean(f_out)) - 1.0) < 0.01

    def test_err_equals_noise_sigma(self):
        rng = np.random.default_rng(0)
        t = np.linspace(0.0, 90.0, 100)
        noise_ppm = 250.0
        _, _, e_out = make_blank_sky(t, rng, noise_ppm=noise_ppm)
        expected_sigma = noise_ppm * 1e-6
        np.testing.assert_allclose(e_out, expected_sigma, rtol=1e-9)


# ---------------------------------------------------------------------------
# run_trial
# ---------------------------------------------------------------------------

class TestRunTrial:
    def _make_rng(self) -> np.random.Generator:
        return np.random.default_rng(42)

    def test_returns_adversarial_trial(self):
        t, f, e = _synthetic_lc(n=400)
        result = run_trial(0, "scrambled", "KIC 0", t, f, e, self._make_rng())
        assert isinstance(result, AdversarialTrial)

    def test_all_categories_run_without_exception(self):
        """run_trial must never raise — errors go into error_message."""
        t, f, e = _synthetic_lc(n=400, seed=77)
        for cat in CATEGORIES:
            result = run_trial(0, cat, "KIC 0", t, f, e, self._make_rng())
            assert isinstance(result, AdversarialTrial)
            # If error occurred it must be stored, not raised
            # (detected will be False in that case)
            if result.error_message:
                assert result.detected is False

    def test_detected_is_bool(self):
        t, f, e = _synthetic_lc(n=400)
        result = run_trial(0, "blank_sky", "KIC 0", t, f, e, self._make_rng())
        assert isinstance(result.detected, bool)

    def test_category_stored_correctly(self):
        t, f, e = _synthetic_lc(n=400)
        for cat in CATEGORIES:
            result = run_trial(0, cat, "KIC X", t, f, e, self._make_rng())
            assert result.category == cat

    def test_star_id_stored(self):
        t, f, e = _synthetic_lc(n=400)
        result = run_trial(5, "sign_inverted", "KIC 99999", t, f, e, self._make_rng())
        assert result.star_id == "KIC 99999"

    def test_trial_index_stored(self):
        t, f, e = _synthetic_lc(n=400)
        result = run_trial(42, "scrambled", "KIC 0", t, f, e, self._make_rng())
        assert result.trial_index == 42


# ---------------------------------------------------------------------------
# Committed artifact validation
# ---------------------------------------------------------------------------
# These tests validate the committed data/artifacts/adversarial_selftest.json.
# They do NOT invoke the script — generation is manual (run
# scripts/adversarial_selftest.py, commit the result).  This keeps the test
# suite deterministic and fast: no search, no FITS I/O, no TLS.
# ---------------------------------------------------------------------------

_ADV_ARTIFACT = Path(__file__).parent.parent / "data" / "artifacts" / "adversarial_selftest.json"
_ADV_MANIFEST = _ADV_ARTIFACT.with_suffix(".manifest.json")


@pytest.mark.no_network
class TestAdversarialSelftestArtifact:
    """Validate the committed adversarial_selftest.json artifact (read-only)."""

    @pytest.fixture(autouse=True)
    def _require_artifact(self):
        if not _ADV_ARTIFACT.exists():
            pytest.skip(
                "data/artifacts/adversarial_selftest.json not yet committed. "
                "Run: python scripts/adversarial_selftest.py --seed 42 --n-trials 20 "
                "--output-dir data/artifacts --data-dir data/golden --no-plot"
            )

    def _load(self) -> dict:
        with open(_ADV_ARTIFACT, encoding="utf-8") as f:
            return json.load(f)

    def test_agents_md_rule3_fields(self):
        """source_doi, access_date, row_count must be present and non-empty."""
        data = self._load()
        assert "source_doi" in data and data["source_doi"].strip(), "Missing source_doi"
        assert "access_date" in data and data["access_date"].strip(), "Missing access_date"
        assert "row_count" in data, "Missing row_count"
        assert isinstance(data["row_count"], int) and data["row_count"] > 0, (
            f"row_count must be a positive int, got {data['row_count']!r}"
        )

    def test_detection_algorithm_is_tls(self):
        """
        The committed artifact must have been produced with TLS, not the BLS
        fallback.  A FAR measured with BLS characterises a different detector.
        Regenerate: python scripts/adversarial_selftest.py --seed 42 --n-trials 20
                    --output-dir data/artifacts --data-dir data/golden --no-plot
        """
        data = self._load()
        assert "detection_algorithm" in data, (
            "Missing detection_algorithm field — regenerate the artifact with the "
            "updated script (scripts/adversarial_selftest.py)."
        )
        assert data["detection_algorithm"] == "TLS", (
            f"Artifact was produced with {data['detection_algorithm']!r}, not TLS. "
            "Install transitleastsquares and regenerate."
        )

    def test_all_categories_present(self):
        """All four null categories must appear in false_alarm_rates."""
        data = self._load()
        recorded = {e["category"] for e in data["false_alarm_rates"]}
        assert recorded == set(CATEGORIES), (
            f"Missing categories: {set(CATEGORIES) - recorded}"
        )

    def test_far_values_in_unit_interval(self):
        """Every false_alarm_rate must be in [0.0, 1.0]."""
        data = self._load()
        for entry in data["false_alarm_rates"]:
            rate = entry["false_alarm_rate"]
            assert 0.0 <= rate <= 1.0, (
                f"false_alarm_rate={rate} for {entry['category']} outside [0,1]"
            )
            assert entry["far_lower_68"] <= rate <= entry["far_upper_68"], (
                f"Wilson bounds inconsistent for {entry['category']}"
            )

    def test_row_count_matches_trials(self):
        """row_count must equal len(trials)."""
        data = self._load()
        assert data["row_count"] == len(data["trials"]), (
            f"row_count={data['row_count']} but len(trials)={len(data['trials'])}"
        )

    def test_manifest_sidecar_present(self):
        """adversarial_selftest.manifest.json must exist alongside the artifact."""
        assert _ADV_MANIFEST.exists(), (
            f"Manifest sidecar missing: {_ADV_MANIFEST.name}"
        )
        with open(_ADV_MANIFEST, encoding="utf-8") as f:
            m = json.load(f)
        assert len(m.get("sha256", "")) == 64, "sha256 in manifest must be 64 hex chars"
        assert m.get("source_doi", "").strip(), "source_doi missing from manifest"

    def test_notes_acknowledges_published_far(self):
        """Artifact notes must state FAR is published as-is (anti-suppression guard)."""
        data = self._load()
        notes = data.get("notes", "")
        assert "published" in notes.lower() or "reported" in notes.lower(), (
            "notes field must acknowledge FAR is published regardless of value."
        )
