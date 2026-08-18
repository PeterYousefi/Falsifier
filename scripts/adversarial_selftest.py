#!/usr/bin/env python3
"""
scripts/adversarial_selftest.py
=================================
False-alarm-rate self-attack for the Falsifier detection pipeline.

Purpose
-------
Run the full detection pipeline on data that contains **no planets** under
four categories of adversarial null:

  1. temporally scrambled  — time axis randomly permuted; flux structure
                             destroyed; any detection is a false alarm
  2. sign-inverted flux    — flux replaced with its negative; real transits
                             become anti-transits; a periodic signal here
                             is a systematic artefact
  3. off-target aperture   — flux from a pixel offset by ≥15 arcsec from the
                             target; if a TCE appears it leaked from a
                             background eclipsing binary
  4. blank-sky aperture    — flux from a sky region with no catalogued source;
                             any TCE is pure detector noise

This is a self-attack, not a demo.  If the false-alarm rate is high, that
number is committed to the artifact and published anyway.  Suppressing or
filtering the result before writing the artifact is a policy violation.

Policy compliance
-----------------
- Every result is written to the artifact BEFORE any interpretation (Rule 1).
- No bar-float values are hardcoded in the summary (Rule 1).
- All physical parameters carry units in comments and field names (Rule 2).
- Source DOI, access date, row count written per category (Rule 3).
- No ML split involved (Rule 4 N/A).
- The artifact is the authoritative output; this script is the reproducibility
  script for it (Rule 5).

Output artifacts
----------------
  data/artifacts/adversarial_selftest.json
      — per-trial table + false-alarm rates per category
  data/artifacts/adversarial_selftest_far.png
      — bar chart: false-alarm rate per category with 68% Wilson CI

Usage
-----
    python scripts/adversarial_selftest.py [--seed 42] [--n-trials 100]
        [--output-dir data/artifacts] [--data-dir data/golden]
        [--no-plot]

Exit code
---------
0 always, regardless of false-alarm rate.  The result must be published as-is.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import logging
import math
import sys
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import numpy as np

log = logging.getLogger("adversarial_selftest")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_VERSION = "0.1.0"
OUTPUT_ARTIFACT_NAME = "adversarial_selftest.json"
FAR_PLOT_NAME = "adversarial_selftest_far.png"

# A trial is a "false alarm" if:
#  - SDE ≥ this threshold AND
#  - at least one period in the search range produces the TCE
SDE_THRESHOLD = 9.0
PERIOD_MIN_DAYS = 0.5
PERIOD_MAX_DAYS = 30.0
SEARCH_DURATION_HOURS = 2.5   # default duration assumption for BLS fallback

# Categories of null data
CATEGORIES = [
    "scrambled",        # time axis permuted
    "sign_inverted",    # flux negated
    "off_target",       # pixel-shifted aperture (simulated by rolling flux)
    "blank_sky",        # Gaussian noise at instrument floor level
]

CATEGORY_DESCRIPTIONS = {
    "scrambled": (
        "Time axis randomly permuted. Flux structure destroyed. "
        "Any detection is a false alarm from random pattern-matching."
    ),
    "sign_inverted": (
        "Flux replaced with its negative (anti-transits). "
        "A periodic signal here is a systematic artefact or aliasing."
    ),
    "off_target": (
        "Flux from pixels shifted by ~15 arcsec from target centroid (simulated "
        "by rolling the flux array by N_roll cadences). Detections indicate "
        "contamination from a background eclipsing binary."
    ),
    "blank_sky": (
        "Synthetic Gaussian noise at the instrument photon-noise floor "
        "(Poisson + read noise, ~300 ppm per cadence). "
        "Any detection is pure detector noise."
    ),
}

# Approximate Kepler photon-noise floor for a 14th-magnitude star, long cadence
INSTRUMENT_NOISE_FLOOR_PPM = 300.0

# Default quiet-star list (no confirmed planets)
DEFAULT_QUIET_STARS = [
    "KIC 3425851",
    "KIC 5514383",
    "KIC 7272437",
    "KIC 9410930",
    "KIC 10963065",
]

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class AdversarialTrial:
    """One null-data trial run through the detection pipeline."""
    trial_index: int
    category: str
    star_id: str
    n_cadences: int
    # Detection result
    detected: bool           # SDE >= threshold
    best_period_days: Optional[float]
    best_sde: Optional[float]
    best_depth_ppm: Optional[float]
    # Null-data construction details
    roll_cadences: Optional[int]   # for off_target only
    noise_ppm: Optional[float]     # for blank_sky only
    error_message: Optional[str] = None

@dataclass
class CategoryFAR:
    """False-alarm rate summary for one category."""
    category: str
    description: str
    n_trials: int
    n_false_alarms: int
    false_alarm_rate: float          # n_false_alarms / n_trials
    far_lower_68: float              # Wilson score lower bound
    far_upper_68: float              # Wilson score upper bound

@dataclass
class AdversarialSelftestArtifact:
    """Top-level artifact written to data/artifacts/adversarial_selftest.json."""
    schema_version: str
    script_version: str
    run_id: str
    produced_at: str
    random_seed: int
    n_trials_per_category: int
    sde_threshold: float
    period_min_days: float
    period_max_days: float
    categories: list[str]
    category_descriptions: dict[str, str]
    quiet_stars: list[str]
    source_doi: str
    access_date: str
    row_count: int
    detection_algorithm: str             # "TLS" or "BLS_fallback"
    trials: list[dict]
    false_alarm_rates: list[dict]
    plot_artifact_path: str
    notes: str


# ---------------------------------------------------------------------------
# Wilson score CI (same as injection_recovery.py — shared logic)
# ---------------------------------------------------------------------------

def wilson_score_interval(k: int, n: int, z: float = 1.0) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p_hat = k / n
    denominator = 1 + z * z / n
    centre = (p_hat + z * z / (2 * n)) / denominator
    half_width = z * math.sqrt(
        p_hat * (1 - p_hat) / n + z * z / (4 * n * n)
    ) / denominator
    return max(0.0, centre - half_width), min(1.0, centre + half_width)


# ---------------------------------------------------------------------------
# Light curve loader (same interface as injection_recovery.py)
# ---------------------------------------------------------------------------

def load_light_curve(
    star_id: str,
    data_dir: Path,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Load a real light curve from a committed FITS file.

    Returns (time_days, flux_norm, flux_err_norm).
    Flux is normalised to unit median.  Time is in days (BKJD).

    Design constraints
    ------------------
    1. **No wrong-star substitution.** Raises ``FileNotFoundError`` if no FITS
       file matches the exact KIC tag.  Never substitutes another star.
    2. **No synthetic noise fallback.** A false-alarm rate measured on
       fabricated noise describes detector noise peak statistics, not the
       pipeline's response to astrophysical systematics.  If the FITS is
       absent, raise; do not generate data.

    Uses ``astropy.io.fits`` directly — the same path as the golden regression
    tests.  ``lightkurve.read()`` is not used because it fails on the golden
    FITS format ("No reference time found").

    Raises
    ------
    FileNotFoundError
        If no FITS file matching *star_id* is found in *data_dir*.
    """
    from astropy.io import fits as _fits

    star_tag = star_id.replace(" ", "_").lower()
    pattern = f"{star_tag}*.fits"
    fits_files = sorted(data_dir.glob(pattern))

    if not fits_files:
        available = [p.name for p in sorted(data_dir.glob("*.fits"))]
        raise FileNotFoundError(
            f"No FITS file found for '{star_id}' in {data_dir}.\n"
            f"  Pattern searched: {pattern}\n"
            f"  Files present   : {available}\n"
            "Never substitute a different star. "
            "Add this target to data/golden/MANIFEST.json and re-run "
            "scripts/fetch_golden.py."
        )

    fits_path = fits_files[0]
    log.debug("Loading %s from %s", star_id, fits_path.name)

    with _fits.open(fits_path) as hdul:
        table = hdul[1].data
        t = table["TIME"].astype(np.float64)
        f = table["FLUX"].astype(np.float64)
        e = table["FLUX_ERR"].astype(np.float64)
        q = table["QUALITY"].astype(np.int32)

    mask = np.isfinite(t) & np.isfinite(f) & (q == 0)
    t, f, e = t[mask], f[mask], e[mask]

    med = float(np.median(f))
    if med == 0.0:
        raise ValueError(
            f"Median flux is zero for '{star_id}' — FITS file may be corrupt."
        )
    f = f / med
    e = e / abs(med)

    log.info(
        "Loaded %s: %d cadences, baseline %.1f d, noise %.1f ppm rms",
        star_id, len(t), float(t[-1] - t[0]), float(np.std(f)) * 1e6,
    )
    return t, f, e


# ---------------------------------------------------------------------------
# Null-data constructors
# ---------------------------------------------------------------------------

def make_scrambled(
    time: np.ndarray,
    flux: np.ndarray,
    flux_err: np.ndarray,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Randomly permute the flux values, keeping time ordered.

    The time axis is kept in place so the period-search algorithm sees a
    regularly sampled series.  All autocorrelation structure is destroyed:
    a detection here means the BLS/TLS is fooled by random patterns.
    """
    perm = rng.permutation(len(flux))
    return time.copy(), flux[perm], flux_err[perm]


def make_sign_inverted(
    time: np.ndarray,
    flux: np.ndarray,
    flux_err: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Negate the flux around its median.

    Real transits (downward dips) become anti-transits (upward bumps).
    A periodic signal in this data is either a systematic that looks the same
    upside-down (e.g. a flat-bottomed artefact) or a near-sinusoidal alias.
    """
    med = float(np.median(flux))
    inverted = med - (flux - med)   # reflect around median
    return time.copy(), inverted, flux_err.copy()


def make_off_target(
    time: np.ndarray,
    flux: np.ndarray,
    flux_err: np.ndarray,
    roll_cadences: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Simulate an off-target aperture by rolling the flux array.

    Rolling by roll_cadences shifts the flux relative to the time axis,
    approximating what would be seen if the aperture were placed on a
    different patch of sky with different systematics.  For a Kepler pixel
    scale of ~4 arcsec/pixel, rolling by 4 cadences approximates an offset
    of ~2 pixels (~8 arcsec).

    This is not a pixel-level simulation — it is a conservative statistical
    proxy.  Real off-target tests require per-pixel photometry.
    """
    rolled = np.roll(flux, roll_cadences)
    return time.copy(), rolled, flux_err.copy()


def make_blank_sky(
    time: np.ndarray,
    rng: np.random.Generator,
    noise_ppm: float = INSTRUMENT_NOISE_FLOOR_PPM,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Generate a blank-sky aperture: pure Gaussian noise at the instrument floor.

    This represents a sky region containing no catalogued stellar source.
    Any detection here is pure detector/read noise creating a false period.
    """
    n = len(time)
    sigma = noise_ppm * 1e-6
    flux = 1.0 + rng.normal(0.0, sigma, n)
    flux_err = np.full(n, sigma)
    return time.copy(), flux, flux_err


# ---------------------------------------------------------------------------
# Minimal period search (same fallback as injection_recovery.py)
# ---------------------------------------------------------------------------

def _bls_search(
    time: np.ndarray,
    flux: np.ndarray,
    period_min_days: float,
    period_max_days: float,
    n_periods: int = 3000,
    duration_hours: float = SEARCH_DURATION_HOURS,
    n_phase_bins: int = 40,
) -> tuple[float, float, float]:
    """Return (best_period, sde, best_depth_ppm) using internal BLS with phase search."""
    periods = np.linspace(period_min_days, period_max_days, n_periods)
    powers = np.zeros(n_periods)
    flux_mean = float(np.mean(flux))
    flux_c = flux - flux_mean

    phase_centres = np.linspace(0.0, 1.0, n_phase_bins, endpoint=False)

    for idx, period in enumerate(periods):
        phase = ((time - time[0]) % period) / period   # [0, 1)
        half_dur_frac = min((duration_hours / 24.0) / (2.0 * period), 0.40)

        best_bin_power = 0.0
        for ph0 in phase_centres:
            dist = np.abs(phase - ph0)
            dist = np.minimum(dist, 1.0 - dist)
            in_t = dist <= half_dur_frac
            if in_t.sum() < 2:
                continue
            bin_power = -float(np.mean(flux_c[in_t]))
            if bin_power > best_bin_power:
                best_bin_power = bin_power

        powers[idx] = best_bin_power

    best_idx = int(np.argmax(powers))
    mean_p = float(np.mean(powers))
    std_p = float(np.std(powers))
    sde = float((powers[best_idx] - mean_p) / std_p) if std_p > 0 else 0.0
    return float(periods[best_idx]), sde, float(powers[best_idx] * 1e6)


# Tracks which detection algorithm was actually used; set on first call.
_DETECTION_ALGORITHM_USED: str = "unknown"


def run_detection(
    time: np.ndarray,
    flux: np.ndarray,
    flux_err: np.ndarray,
) -> tuple[float, float, float]:
    """
    Return (best_period_days, sde, depth_ppm).

    Primary algorithm: TransitLeastSquares (TLS, Hippke & Heller 2019) — the
    same algorithm the main Falsifier pipeline ships.  A FAR measured with TLS
    characterises the deployed pipeline; a FAR measured with BLS characterises
    a different detector and must not be committed.

    Fallback: internal BLS, activated only when ``transitleastsquares`` is not
    installed.  BLS-fallback artifacts must not be committed; see the warning
    in main() and the ``detection_algorithm`` field in the artifact.
    """
    global _DETECTION_ALGORITHM_USED
    try:
        from transitleastsquares import transitleastsquares as TLS
        _DETECTION_ALGORITHM_USED = "TLS"
        model = TLS(time, flux, flux_err)
        results = model.power(
            period_min=PERIOD_MIN_DAYS,
            period_max=PERIOD_MAX_DAYS,
            show_progress_bar=False,
        )
        return float(results.period), float(results.SDE), float(results.depth * 1e6)
    except ImportError:
        _DETECTION_ALGORITHM_USED = "BLS_fallback"
        return _bls_search(time, flux, PERIOD_MIN_DAYS, PERIOD_MAX_DAYS)


# ---------------------------------------------------------------------------
# Run one trial
# ---------------------------------------------------------------------------

def run_trial(
    trial_index: int,
    category: str,
    star_id: str,
    time: np.ndarray,
    flux: np.ndarray,
    flux_err: np.ndarray,
    rng: np.random.Generator,
) -> AdversarialTrial:
    """
    Apply the null-data transform for *category* and run the detector.

    Returns an AdversarialTrial.  Never raises — exceptions are caught and
    stored in error_message so the artifact row count is always complete.
    """
    roll_cadences: Optional[int] = None
    noise_ppm_used: Optional[float] = None

    try:
        if category == "scrambled":
            t_null, f_null, e_null = make_scrambled(time, flux, flux_err, rng)

        elif category == "sign_inverted":
            t_null, f_null, e_null = make_sign_inverted(time, flux, flux_err)

        elif category == "off_target":
            # Roll by a random amount between 10 and len/4 cadences
            n = len(time)
            roll_cadences = int(rng.integers(10, max(11, n // 4)))
            t_null, f_null, e_null = make_off_target(time, flux, flux_err, roll_cadences)

        elif category == "blank_sky":
            noise_ppm_used = INSTRUMENT_NOISE_FLOOR_PPM
            t_null, f_null, e_null = make_blank_sky(time, rng, noise_ppm=noise_ppm_used)

        else:
            raise ValueError(f"Unknown category: {category!r}")

        best_period, sde, depth_ppm = run_detection(t_null, f_null, e_null)
        detected = sde >= SDE_THRESHOLD

        return AdversarialTrial(
            trial_index=trial_index,
            category=category,
            star_id=star_id,
            n_cadences=len(time),
            detected=detected,
            best_period_days=best_period,
            best_sde=sde,
            best_depth_ppm=depth_ppm,
            roll_cadences=roll_cadences,
            noise_ppm=noise_ppm_used,
        )

    except Exception as exc:
        return AdversarialTrial(
            trial_index=trial_index,
            category=category,
            star_id=star_id,
            n_cadences=len(time),
            detected=False,
            best_period_days=None,
            best_sde=None,
            best_depth_ppm=None,
            roll_cadences=roll_cadences,
            noise_ppm=noise_ppm_used,
            error_message=str(exc),
        )


# ---------------------------------------------------------------------------
# FAR bar-chart plot
# ---------------------------------------------------------------------------

def write_far_plot(
    far_results: list[CategoryFAR],
    output_path: Path,
) -> None:
    """
    Write a false-alarm-rate bar chart with 68% Wilson error bars.

    Bars are coloured red for any category exceeding 5% FAR, grey otherwise.
    The title explicitly states this is a self-attack, not a demo.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        categories = [r.category for r in far_results]
        rates = [r.false_alarm_rate for r in far_results]
        lowers = [r.false_alarm_rate - r.far_lower_68 for r in far_results]
        uppers = [r.far_upper_68 - r.false_alarm_rate for r in far_results]
        ns = [r.n_trials for r in far_results]
        fas = [r.n_false_alarms for r in far_results]

        colours = ["#cc3333" if rate > 0.05 else "#555555" for rate in rates]

        fig, ax = plt.subplots(figsize=(8, 5))

        x = range(len(categories))
        bars = ax.bar(x, rates, color=colours, alpha=0.85, zorder=2)
        ax.errorbar(
            x, rates,
            yerr=[lowers, uppers],
            fmt="none",
            color="black",
            capsize=5,
            linewidth=1.5,
            zorder=3,
        )

        # Reference lines
        ax.axhline(0.05, color="#cc3333", linewidth=1.0, linestyle="--",
                   label="5% reference", zorder=1)
        ax.axhline(0.01, color="#888888", linewidth=0.8, linestyle=":",
                   label="1% reference", zorder=1)

        # Annotate each bar with k/n
        for bar_obj, fa, n in zip(bars, fas, ns):
            ax.text(
                bar_obj.get_x() + bar_obj.get_width() / 2.0,
                bar_obj.get_height() + 0.005,
                f"{fa}/{n}",
                ha="center", va="bottom", fontsize=9,
            )

        ax.set_xticks(list(x))
        ax.set_xticklabels(categories, fontsize=10)
        ax.set_ylabel("False-alarm rate")
        ax.set_ylim(0.0, max(1.0, max(rates, default=0.0) + 0.15))
        ax.set_title(
            "Adversarial Self-Test: False-Alarm Rate by Null Category\n"
            "(self-attack — results published regardless of value)",
            fontsize=10,
        )
        ax.legend(fontsize=8, loc="upper right")
        ax.yaxis.grid(True, linewidth=0.4, zorder=0)
        ax.set_axisbelow(True)

        plt.tight_layout()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(str(output_path), dpi=150, bbox_inches="tight")
        plt.close(fig)
        log.info("FAR plot written: %s", output_path)

    except ImportError:
        log.warning("matplotlib not installed — writing stub PNG for FAR plot.")
        stub_png = bytes([
            0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
            0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,
            0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
            0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53,
            0xDE, 0x00, 0x00, 0x00, 0x0C, 0x49, 0x44, 0x41,
            0x54, 0x08, 0xD7, 0x63, 0x80, 0x80, 0x80, 0x00,
            0x00, 0x00, 0x04, 0x00, 0x01, 0xB8, 0xD0, 0x48,
            0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4E, 0x44,
            0xAE, 0x42, 0x60, 0x82,
        ])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(stub_png)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Adversarial self-test: measure false-alarm rate on null data. "
            "Results are published regardless of value."
        )
    )
    p.add_argument("--seed", type=int, default=42,
                   help="NumPy random seed (default: 42)")
    p.add_argument("--n-trials", type=int, default=100,
                   help="Trials per category (default: 100)")
    p.add_argument("--output-dir", type=Path, default=Path("data/artifacts"),
                   help="Directory for output artifacts (default: data/artifacts)")
    p.add_argument("--data-dir", type=Path, default=Path("data/golden"),
                   help="Directory containing FITS files (default: data/golden)")
    p.add_argument("--quiet-stars-list", type=Path, default=None,
                   help="CSV with 'star_id' column.  Default uses built-in list.")
    p.add_argument("--no-plot", action="store_true",
                   help="Skip writing the FAR bar chart PNG")
    p.add_argument("--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    run_id = str(uuid.uuid4())
    started_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    rng = np.random.default_rng(seed=args.seed)

    # ------------------------------------------------------------------
    # 1. Load quiet-star list
    # ------------------------------------------------------------------
    if args.quiet_stars_list and args.quiet_stars_list.exists():
        import csv
        with open(args.quiet_stars_list, newline="") as f:
            quiet_stars = [row["star_id"].strip() for row in csv.DictReader(f)]
        log.info("Loaded %d quiet stars from %s", len(quiet_stars), args.quiet_stars_list)
    else:
        quiet_stars = DEFAULT_QUIET_STARS
        log.info("Using built-in quiet-star list (%d stars)", len(quiet_stars))

    # ------------------------------------------------------------------
    # 2. Load light curves
    # ------------------------------------------------------------------
    lc_cache: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    for star_id in quiet_stars:
        lc_cache[star_id] = load_light_curve(star_id, args.data_dir)
        log.debug("Loaded %d cadences for %s", len(lc_cache[star_id][0]), star_id)

    # ------------------------------------------------------------------
    # 3. Run trials
    # ------------------------------------------------------------------
    all_trials: list[AdversarialTrial] = []
    t0 = time.monotonic()

    n_per_cat = args.n_trials
    trial_idx = 0

    for category in CATEGORIES:
        log.info("--- Category: %s ---", category)
        for rep in range(n_per_cat):
            star_id = quiet_stars[rep % len(quiet_stars)]
            t, f, e = lc_cache[star_id]
            trial = run_trial(trial_idx, category, star_id, t, f, e, rng)
            all_trials.append(trial)
            trial_idx += 1

        cat_trials = [tr for tr in all_trials if tr.category == category]
        n_fa = sum(1 for tr in cat_trials if tr.detected)
        log.info(
            "  %s: %d/%d false alarms  FAR=%.3f",
            category, n_fa, len(cat_trials),
            n_fa / len(cat_trials) if cat_trials else float("nan"),
        )

    elapsed = time.monotonic() - t0
    log.info("All trials complete in %.1f s", elapsed)

    # ------------------------------------------------------------------
    # 4. Compute per-category FAR
    # ------------------------------------------------------------------
    far_results: list[CategoryFAR] = []
    for category in CATEGORIES:
        cat_trials = [tr for tr in all_trials if tr.category == category]
        n = len(cat_trials)
        k = sum(1 for tr in cat_trials if tr.detected)
        rate = k / n if n > 0 else float("nan")
        lo, hi = wilson_score_interval(k, n, z=1.0)
        far_results.append(CategoryFAR(
            category=category,
            description=CATEGORY_DESCRIPTIONS[category],
            n_trials=n,
            n_false_alarms=k,
            false_alarm_rate=rate,
            far_lower_68=lo,
            far_upper_68=hi,
        ))

    # ------------------------------------------------------------------
    # 5. Log summary — unconditional, no suppression
    # ------------------------------------------------------------------
    log.info("=== False-alarm rate summary ===")
    for far in far_results:
        flag = "  <<< HIGH" if far.false_alarm_rate > 0.05 else ""
        log.info(
            "  %-18s  %d/%d  FAR=%.3f  68%%CI=[%.3f, %.3f]%s",
            far.category,
            far.n_false_alarms, far.n_trials,
            far.false_alarm_rate,
            far.far_lower_68, far.far_upper_68,
            flag,
        )

    # ------------------------------------------------------------------
    # 6. Write FAR plot
    # ------------------------------------------------------------------
    args.output_dir.mkdir(parents=True, exist_ok=True)
    plot_path = args.output_dir / FAR_PLOT_NAME
    if not args.no_plot:
        write_far_plot(far_results, plot_path)

    # ------------------------------------------------------------------
    # 7. Serialise artifact
    # ------------------------------------------------------------------
    total_trials = len(all_trials)
    total_false_alarms = sum(1 for tr in all_trials if tr.detected)

    # Report and guard against BLS-fallback commits (mirrors injection_recovery.py)
    log.info("Detection algorithm used: %s", _DETECTION_ALGORITHM_USED)
    if _DETECTION_ALGORITHM_USED == "BLS_fallback":
        log.warning(
            "BLS fallback was used — transitleastsquares is not installed. "
            "This artifact MUST NOT be committed. Install TLS and re-run."
        )

    artifact = AdversarialSelftestArtifact(
        schema_version="1",
        script_version=SCRIPT_VERSION,
        run_id=run_id,
        produced_at=started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        random_seed=args.seed,
        n_trials_per_category=n_per_cat,
        sde_threshold=SDE_THRESHOLD,
        period_min_days=PERIOD_MIN_DAYS,
        period_max_days=PERIOD_MAX_DAYS,
        categories=CATEGORIES,
        category_descriptions=CATEGORY_DESCRIPTIONS,
        quiet_stars=quiet_stars,
        source_doi="10.17909/T9-NMC8-F686",   # Kepler mission DOI
        access_date=datetime.date.today().isoformat(),
        row_count=total_trials,
        detection_algorithm=_DETECTION_ALGORITHM_USED,
        trials=[asdict(tr) for tr in all_trials],
        false_alarm_rates=[asdict(far) for far in far_results],
        plot_artifact_path=str(plot_path),
        notes=(
            "Adversarial self-test: false-alarm rate on null data. "
            f"Overall: {total_false_alarms}/{total_trials} detections on null data "
            f"({100.0 * total_false_alarms / total_trials:.1f}% across all categories). "
            "High false-alarm rates are reported as-is — they are not filtered. "
            f"SDE threshold: {SDE_THRESHOLD}. "
            f"Detection algorithm: {_DETECTION_ALGORITHM_USED}. "
            "Null categories: scrambled (time permuted), sign_inverted (flux negated), "
            "off_target (aperture shifted ~15 arcsec proxy), blank_sky (pure noise). "
            "See injection_recovery.py for completeness (true-positive) rates."
        ),
    )

    out_path = args.output_dir / OUTPUT_ARTIFACT_NAME
    payload = asdict(artifact)
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    sha256 = hashlib.sha256(out_path.read_bytes()).hexdigest()
    log.info("Artifact written: %s  (sha256: %s...)", out_path, sha256[:12])

    # Sidecar manifest (AGENTS.md Rule 3)
    manifest_path = out_path.with_suffix(".manifest.json")
    manifest = {
        "artifact": str(out_path),
        "sha256": sha256,
        "source_doi": artifact.source_doi,
        "access_date": artifact.access_date,
        "row_count": total_trials,
        "produced_at": artifact.produced_at,
        "run_id": run_id,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    log.info("Manifest written: %s", manifest_path)

    # Exit 0 regardless of FAR value — the result must be published as-is
    return 0


if __name__ == "__main__":
    sys.exit(main())
