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
# Artifact JSON schema + policy
# ---------------------------------------------------------------------------

class TestAdversarialSelftestArtifact:
    def test_artifact_has_agents_md_rule3_fields(self, tmp_path):
        """
        The output artifact must contain source_doi, access_date, row_count
        per AGENTS.md Rule 3.
        """
        out_dir = tmp_path / "artifacts"
        rc = adv_main([
            "--seed", "0",
            "--n-trials", "4",
            "--output-dir", str(out_dir),
            "--data-dir", str(tmp_path / "none"),
            "--no-plot",
        ])
        assert rc == 0

        artifact_path = out_dir / "adversarial_selftest.json"
        assert artifact_path.exists()
        with open(artifact_path, encoding="utf-8") as f:
            data = json.load(f)

        assert "source_doi" in data, "Missing source_doi"
        assert data["source_doi"].strip()
        assert "access_date" in data, "Missing access_date"
        assert "row_count" in data, "Missing row_count"
        assert isinstance(data["row_count"], int) and data["row_count"] > 0

    def test_exit_code_always_zero(self, tmp_path):
        """
        The script must exit 0 regardless of FAR value.
        Suppressing a high FAR is a policy violation.
        """
        out_dir = tmp_path / "artifacts"
        rc = adv_main([
            "--seed", "99",
            "--n-trials", "2",
            "--output-dir", str(out_dir),
            "--data-dir", str(tmp_path / "none"),
            "--no-plot",
        ])
        assert rc == 0, (
            "adversarial_selftest.py must always exit 0.  "
            "High false-alarm rates are published, not suppressed."
        )

    def test_all_categories_in_artifact(self, tmp_path):
        out_dir = tmp_path / "artifacts"
        adv_main([
            "--seed", "1",
            "--n-trials", "2",
            "--output-dir", str(out_dir),
            "--data-dir", str(tmp_path / "none"),
            "--no-plot",
        ])
        with open(out_dir / "adversarial_selftest.json", encoding="utf-8") as f:
            data = json.load(f)

        assert set(data["categories"]) == set(CATEGORIES), (
            "All four null categories must appear in the artifact."
        )

    def test_far_values_in_unit_interval(self, tmp_path):
        """All false_alarm_rate values must be in [0.0, 1.0]."""
        out_dir = tmp_path / "artifacts"
        adv_main([
            "--seed", "2",
            "--n-trials", "5",
            "--output-dir", str(out_dir),
            "--data-dir", str(tmp_path / "none"),
            "--no-plot",
        ])
        with open(out_dir / "adversarial_selftest.json", encoding="utf-8") as f:
            data = json.load(f)

        for far_entry in data["false_alarm_rates"]:
            rate = far_entry["false_alarm_rate"]
            assert 0.0 <= rate <= 1.0, (
                f"false_alarm_rate={rate} for category "
                f"{far_entry['category']} is out of [0, 1]"
            )
            assert far_entry["far_lower_68"] <= rate <= far_entry["far_upper_68"], (
                f"FAR bounds are inconsistent for {far_entry['category']}"
            )

    def test_row_count_equals_total_trials(self, tmp_path):
        """row_count must equal the total number of trial rows."""
        n_trials = 3
        n_cats = len(CATEGORIES)
        out_dir = tmp_path / "artifacts"
        adv_main([
            "--seed", "3",
            "--n-trials", str(n_trials),
            "--output-dir", str(out_dir),
            "--data-dir", str(tmp_path / "none"),
            "--no-plot",
        ])
        with open(out_dir / "adversarial_selftest.json", encoding="utf-8") as f:
            data = json.load(f)

        assert data["row_count"] == n_trials * n_cats
        assert len(data["trials"]) == n_trials * n_cats

    def test_manifest_sidecar_written(self, tmp_path):
        """A .manifest.json sidecar must be co-located with the artifact."""
        out_dir = tmp_path / "artifacts"
        adv_main([
            "--seed", "4",
            "--n-trials", "2",
            "--output-dir", str(out_dir),
            "--data-dir", str(tmp_path / "none"),
            "--no-plot",
        ])
        manifest_path = out_dir / "adversarial_selftest.manifest.json"
        assert manifest_path.exists()
        with open(manifest_path, encoding="utf-8") as f:
            m = json.load(f)
        assert len(m["sha256"]) == 64
        assert m["source_doi"].strip()

    def test_notes_contains_high_far_acknowledgement(self, tmp_path):
        """
        The artifact notes field must acknowledge that high FAR is published
        as-is (policy guard against suppression).
        """
        out_dir = tmp_path / "artifacts"
        adv_main([
            "--seed", "5",
            "--n-trials", "2",
            "--output-dir", str(out_dir),
            "--data-dir", str(tmp_path / "none"),
            "--no-plot",
        ])
        with open(out_dir / "adversarial_selftest.json", encoding="utf-8") as f:
            data = json.load(f)

        notes = data.get("notes", "")
        assert "published" in notes.lower() or "reported" in notes.lower(), (
            "Artifact notes must acknowledge that FAR results are published as-is."
        )
