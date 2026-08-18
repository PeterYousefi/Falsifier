"""
scripts/train_classifier_dr25.py
==================================
DR25 data fetch and class-balance audit.  Training is NOT yet implemented.

``--dry-run`` (the only currently usable mode) fetches the Kepler DR25
Threshold Crossing Event (TCE) catalog from the NASA Exoplanet Archive
``cumulative`` table and reports:

  - Total row count
  - Class balance (PC / FP / AFP / NTP counts)
  - Number of distinct KIC host stars
  - Column availability for the seven vet metrics

Training is blocked by a ``NotImplementedError`` until the feature skew
described below is resolved.

Why training is not yet implemented
--------------------------------------
The XGBoost classifier is trained on features extracted from ``VetOutput``
records by ``falsifier.pipeline.classify.features.extract_features``.
That function reads ``VettingTestResult.metric_value`` for each of the seven
canonical vet tests:

  odd_even_depth_metric          — the odd/even depth asymmetry ratio
                                   produced by _compute_odd_even_excess
  secondary_eclipse_metric       — secondary eclipse depth / primary depth
  centroid_shift_metric          — centroid offset in arcsec
  transit_shape_metric           — transit depth in ppm
  stellar_density_metric         — stellar density consistency statistic
  gaia_ruwe_metric               — Gaia DR3 RUWE value
  systematics_coincidence_metric — systematics coincidence flag

At inference time (``run_vet`` → ``run_classify``) these features are real
quantities on well-defined scales produced by the seven vet modules.

The DR25 cumulative table does NOT contain these quantities.  Every plausible
DR25 column is a different physical quantity on a different numeric scale:

  odd_even_depth_metric      ← koi_ldm_coeff4   4th limb-darkening coeff — NOT asymmetry
  secondary_eclipse_metric   ← koi_model_snr    primary model SNR — NOT secondary depth
  centroid_shift_metric      ← koi_dicco_msky_err  centroid offset uncertainty — NOT offset
  transit_shape_metric       ← koi_ldm_coeff1   1st limb-darkening coeff — NOT depth
  stellar_density_metric     ← koi_steff        stellar Teff — NOT density
  gaia_ruwe_metric           ← (no DR25 column available)
  systematics_coincidence_metric ← koi_robstat  rolling-band stat — closest match

Training on these proxies and running inference on vet-stage outputs is a
**train/serve skew defect**: the XGBoost decision boundaries and the
isotonic calibrator are both fitted to one numeric domain and applied to
another.  The resulting ``ClassifyOutput.probability`` would be meaningless.

What correct training requires
--------------------------------
Option A — pipeline features on Kepler targets (preferred):
  1. Fetch light curves for all DR25 KOIs from MAST.
  2. Run the full ingest → detrend → search → vet pipeline on each.
  3. Collect the resulting VetOutput records (real metric_value fields).
  4. Call run_training on those records.

  This is expensive (thousands of TLS runs) but produces features on
  exactly the same scale as inference.  It is the only option that does
  not require documenting a calibration caveat.

Option B — DR25 DV metrics with documented domain shift:
  Use the DR25 Data Validation (DV) diagnostic metrics directly as features
  (koi_model_chisq, koi_prad, koi_slogg, koi_dicco_msky, koi_max_sngle_ev,
  etc.) and train a separate model on those.  The classify stage must then
  extract the same DV diagnostics from the pipeline's own detrend/search
  output at inference time — not the vet metrics.  This requires a separate
  feature contract and a model trained on matched features.

  If this option is chosen, the model is not a "vet metric re-scorer" but a
  "DV metric classifier".  The feature names, extract_features function, and
  ClassifyOutput schema must be updated accordingly, and the domain shift
  between Kepler DV and this pipeline's TLS output must be characterised and
  documented.

Until one of these options is implemented:
  - ``data/splits/classify_split_indices.json`` is not committed
  - ``tests/test_no_leakage.py`` skips (12 tests, correctly)
  - The classify stage can load a model if one is committed, but no valid
    model exists

DR25 citation
--------------
Thompson et al. 2018, ApJS 235, 38
DOI: 10.3847/1538-4365/aab4f9
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

DR25_DOI = "10.3847/1538-4365/aab4f9"
TAP_URL = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"

# DR25 cumulative table columns fetched for the audit report.
# These are NOT used as training features — they are fetched to characterise
# the class balance and verify column availability.
_AUDIT_COLUMNS = [
    "kepid",
    "kepoi_name",
    "koi_disposition",
    # Candidate diagnostic columns — reported only, NOT mapped to vet metrics
    "koi_period",
    "koi_depth",
    "koi_model_snr",
    "koi_ldm_coeff1",
    "koi_ldm_coeff4",
    "koi_dicco_msky_err",
    "koi_steff",
    "koi_robstat",
]

# DR25 disposition codes → human-readable
_DISP_LABELS = {
    "PC":  "Planet Candidate (PC)",
    "AFP": "Astrophysical False Positive (AFP)",
    "NTP": "Not Transit-like (NTP)",
    "FP":  "False Positive (FP)",
    "KP":  "Known Planet (KP)",
    "CP":  "Confirmed Planet (CP)",
}


def _fetch_dr25() -> "pandas.DataFrame":
    """Fetch DR25 cumulative table from the Exoplanet Archive."""
    try:
        from astroquery.utils.tap.core import Tap
        import pandas as pd
        import warnings
    except ImportError as exc:
        print(f"ERROR: {exc}\nInstall: pip install astroquery pandas", file=sys.stderr)
        sys.exit(1)

    cols_sql = ", ".join(_AUDIT_COLUMNS)
    adql = f"SELECT {cols_sql} FROM cumulative"

    print(f"Fetching DR25 cumulative table from {TAP_URL} …")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        tap = Tap(url=TAP_URL)
        job = tap.launch_job(adql)
        result = job.get_results()

    df = result.to_pandas()
    print(f"  Fetched {len(df)} rows from cumulative table\n")
    return df


def _report(df: "pandas.DataFrame") -> None:
    """Print class balance, host-star count, and column availability."""
    import numpy as np

    print("=" * 60)
    print("DR25 cumulative table — audit report")
    print("=" * 60)

    print(f"\nTotal TCE rows : {len(df)}")
    print(f"Distinct KIC host stars : {df['kepid'].nunique()}")

    print("\nClass distribution:")
    for code, count in df["koi_disposition"].value_counts().items():
        label = _DISP_LABELS.get(str(code), str(code))
        print(f"  {str(code):<6s} {count:>5d}   {label}")

    pc = (df["koi_disposition"] == "PC").sum()
    fp = df["koi_disposition"].isin(["AFP", "NTP", "FP"]).sum()
    total = len(df)
    print(f"\n  → Candidate (PC): {pc} ({100*pc/total:.1f}%)")
    print(f"  → False positive (AFP+NTP+FP): {fp} ({100*fp/total:.1f}%)")

    print("\nColumn availability (non-null counts):")
    feature_cols = [c for c in _AUDIT_COLUMNS
                    if c not in ("kepid", "kepoi_name", "koi_disposition")]
    for col in feature_cols:
        n_present = df[col].notna().sum()
        pct = 100 * n_present / len(df)
        print(f"  {col:<25s} {n_present:>5d} / {len(df)}  ({pct:.1f}%)")

    print()
    print("Feature skew note")
    print("-" * 40)
    print("The seven vet-stage metric_value fields expected by the classifier")
    print("at inference time are NOT equivalent to any DR25 column:")
    print()
    rows = [
        ("odd_even_depth_metric",          "koi_ldm_coeff4",      "4th LDM coeff ≠ asymmetry ratio"),
        ("secondary_eclipse_metric",       "koi_model_snr",       "primary SNR ≠ secondary depth ratio"),
        ("centroid_shift_metric",          "koi_dicco_msky_err",  "centroid offset err ≠ offset itself"),
        ("transit_shape_metric",           "koi_ldm_coeff1",      "1st LDM coeff ≠ transit depth ppm"),
        ("stellar_density_metric",         "koi_steff",           "Teff ≠ density consistency stat"),
        ("gaia_ruwe_metric",               "(no DR25 column)",    "Gaia not in DR25"),
        ("systematics_coincidence_metric", "koi_robstat",         "closest match; still different"),
    ]
    print(f"  {'Inference feature':<35s} {'DR25 proxy':<25s} {'Problem'}")
    print(f"  {'-'*35} {'-'*25} {'-'*30}")
    for feat, proxy, problem in rows:
        print(f"  {feat:<35s} {proxy:<25s} {problem}")

    print()
    print("Training is blocked until this skew is resolved.")
    print("See the module docstring for the two resolution options.")
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch DR25 data and report class balance. Training is not yet implemented."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="(Default and only supported mode) Fetch and report; do not train.",
    )
    parser.add_argument(
        "--train",
        action="store_true",
        help="Attempt to run training (currently raises NotImplementedError).",
    )
    args = parser.parse_args()

    df = _fetch_dr25()
    _report(df)

    if args.train:
        raise NotImplementedError(
            "\n"
            "Training is blocked due to train/serve feature skew.\n"
            "\n"
            "The classifier's extract_features() reads VettingTestResult.metric_value\n"
            "fields produced by the vet stage at inference time.  No DR25 column maps\n"
            "to the same physical quantity on the same numeric scale as those fields.\n"
            "Training on DR25 proxies and running inference on vet-stage metrics would\n"
            "produce a model whose decision boundaries and calibration are both invalid.\n"
            "\n"
            "Resolution options are documented in the module docstring of this file.\n"
            "Remove this guard only after implementing one of them."
        )

    print(
        "\nRun with --dry-run (default) to fetch and report only.\n"
        "Run with --train to see the blocking error message.\n"
        "Training requires resolving the feature skew first."
    )


if __name__ == "__main__":
    main()
