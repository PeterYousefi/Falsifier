"""
falsifier.pipeline.classify.train
====================================
``run_training`` — train the XGBoost classifier on Kepler DR25 dispositions.

Data source
-----------
Kepler DR25 Threshold Crossing Event (TCE) catalog:
  Thompson et al. 2018, ApJS 235, 38
  DOI: 10.3847/1538-4365/aab4f9
  NASA Exoplanet Archive: https://exoplanetarchive.ipac.caltech.edu

The catalog provides the seven vetting diagnostic metrics and the DR25
disposition (PC / FP / EB / etc.).  These are encoded to binary labels
(see ``features.encode_label``).

Training pipeline
-----------------
1. Load feature matrix X (N×7) and labels y (N,) from ``VetOutput`` records
   or from the DR25 CSV directly.
2. Group split by host star ID using ``GroupShuffleSplit`` (test_size=0.2).
3. Fit XGBoost on the train fold.
4. Calibrate on the test fold using isotonic regression.
5. Evaluate: precision, recall, Brier score, ECE, reliability diagram.
6. Persist: model (.ubj), calibrator (.pkl), split indices (.json),
   evaluation metrics (.json), reliability diagram (.png).

All output paths are content-addressed under ``artifacts/classify/``.

Saved artifacts
---------------
``run_training`` returns a ``TrainingResult`` dataclass containing paths to:
  - model_path          : XGBoost model in UBJ format
  - calibrator_path     : pickled IsotonicRegression calibrator
  - split_indices_path  : JSON split file (read by test_no_leakage.py)
  - eval_metrics_path   : JSON evaluation metrics
  - reliability_diagram : ArtifactRef for the PNG

Model version
-------------
The version string is the SHA-256 of the model file bytes (first 12 hex
characters), prefixed with the training date: ``"20240601-abc123def456"``.
This is recorded in the model sidecar JSON so ``ClassifyOutput.model_version``
is always traceable.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import pickle
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import numpy as np

from .calibrate import (
    bootstrap_uncertainty,
    calibrated_predict,
    compute_brier_score,
    compute_ece,
    fit_calibrator,
)
from .features import FEATURE_NAMES, encode_label, extract_feature_matrix
from .metrics import EvalMetrics, compute_eval_metrics
from .split import DEFAULT_SPLIT_PATH, grouped_split, write_split_indices
from ..contracts.classify import CalibrationMeta
from ..contracts.vet import VetOutput

DR25_DOI = "10.3847/1538-4365/aab4f9"
"""DOI for the Kepler DR25 TCE catalog (Thompson et al. 2018)."""

DEFAULT_OUTPUT_DIR = Path("artifacts/classify")


# ---------------------------------------------------------------------------
# TrainingResult
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TrainingResult:
    """Paths and metrics produced by a single training run."""

    model_path: Path
    """XGBoost model saved in UBJ (Universal Binary JSON) format."""

    model_version: str
    """``"YYYYMMDD-{sha256[:12]}"`` string recorded in the sidecar."""

    calibrator_path: Path
    """Pickled ``IsotonicRegression`` calibrator."""

    split_indices_path: Path
    """JSON split file; read by ``tests/test_no_leakage.py``."""

    eval_metrics_path: Path
    """JSON file containing precision, recall, Brier, ECE."""

    reliability_diagram_path: Path | None
    """PNG reliability diagram, or None if matplotlib was unavailable."""

    eval_metrics: EvalMetrics
    """In-memory evaluation metrics."""

    calibration_meta: CalibrationMeta
    """Embedded in every ClassifyOutput produced by this model."""


# ---------------------------------------------------------------------------
# Model sidecar
# ---------------------------------------------------------------------------

def _write_model_sidecar(
    model_path: Path,
    version: str,
    feature_names: list[str],
    calibrator_path: Path,
    split_indices_path: Path,
    eval_metrics_path: Path,
    diagram_path: Path | None,
) -> Path:
    """Write a JSON sidecar alongside *model_path*."""
    sidecar = model_path.with_suffix(".json")
    data: dict[str, Any] = {
        "model_version": version,
        "feature_names": feature_names,
        "calibrator_path": str(calibrator_path),
        "split_indices_path": str(split_indices_path),
        "eval_metrics_path": str(eval_metrics_path),
        "reliability_diagram_path": str(diagram_path) if diagram_path else None,
        "training_date": datetime.date.today().isoformat(),
        "dr25_doi": DR25_DOI,
    }
    sidecar.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return sidecar


# ---------------------------------------------------------------------------
# XGBoost hyperparameters
# ---------------------------------------------------------------------------

_XGBOOST_PARAMS: dict[str, Any] = {
    "n_estimators": 300,
    "max_depth": 4,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 5,
    "scale_pos_weight": 1,   # will be overridden from class counts
    "eval_metric": "logloss",
    "random_state": 42,
    "n_jobs": -1,
    "missing": float("nan"),  # native NaN handling for missing metrics
}


# ---------------------------------------------------------------------------
# run_training
# ---------------------------------------------------------------------------

def run_training(
    vet_outputs: list[VetOutput],
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    split_path: Path = DEFAULT_SPLIT_PATH,
    test_size: float = 0.2,
    random_state: int = 42,
    xgb_params: dict[str, Any] | None = None,
    n_bootstrap: int = 100,
    draw_diagram: bool = True,
) -> TrainingResult:
    """
    Train the classify model from a list of ``VetOutput`` records.

    Parameters
    ----------
    vet_outputs : list[VetOutput]
        One entry per TCE, drawn from the Kepler DR25 catalog.
    output_dir : Path
        Root directory for all output artifacts.
    split_path : Path
        Where to write the split-index JSON.
    test_size : float
        Fraction of host stars to hold out for calibration + evaluation.
    random_state : int
    xgb_params : dict | None
        Override default XGBoost hyperparameters.
    n_bootstrap : int
        Bootstrap resamples for uncertainty estimation.
    draw_diagram : bool
        Whether to render the reliability diagram PNG (requires matplotlib).

    Returns
    -------
    TrainingResult
    """
    try:
        import xgboost as xgb
    except ImportError as exc:
        raise ImportError(
            "xgboost is required for run_training.  Install it with: "
            "pip install xgboost"
        ) from exc

    if not vet_outputs:
        raise ValueError("run_training requires at least one VetOutput record")

    # ------------------------------------------------------------------
    # 1. Build feature matrix and labels
    # ------------------------------------------------------------------
    tce_ids = [v.tce_id for v in vet_outputs]
    host_star_ids = [v.host_star_id for v in vet_outputs]
    X = extract_feature_matrix(vet_outputs)
    y = np.array([encode_label(v.disposition) for v in vet_outputs], dtype=np.int32)

    # ------------------------------------------------------------------
    # 2. Grouped split by host star
    # ------------------------------------------------------------------
    train_idx, test_idx = grouped_split(
        tce_ids, host_star_ids, y,
        test_size=test_size,
        random_state=random_state,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    write_split_indices(
        tce_ids, host_star_ids, train_idx, test_idx,
        test_size=test_size,
        random_state=random_state,
        path=split_path,
    )

    X_train, y_train = X[train_idx], y[train_idx]
    X_test, y_test = X[test_idx], y[test_idx]

    # ------------------------------------------------------------------
    # 3. Fit XGBoost on training fold
    # ------------------------------------------------------------------
    params = {**_XGBOOST_PARAMS, **(xgb_params or {})}

    # Balance positive/negative class weights in training data
    n_neg = int((y_train == 0).sum())
    n_pos = int((y_train == 1).sum())
    if n_pos > 0 and n_neg > 0:
        params["scale_pos_weight"] = n_neg / n_pos

    clf = xgb.XGBClassifier(**params)
    clf.fit(X_train, y_train)

    # Raw predicted probabilities on test fold (before calibration)
    y_raw_test = clf.predict_proba(X_test)[:, 1]

    # ------------------------------------------------------------------
    # 4. Calibrate on test fold
    # ------------------------------------------------------------------
    calibrator, brier_cal, ece_cal = fit_calibrator(y_test, y_raw_test)
    y_cal_test = calibrated_predict(calibrator, y_raw_test)

    # ------------------------------------------------------------------
    # 5. Evaluate
    # ------------------------------------------------------------------
    diagram_path: Path | None = None
    if draw_diagram:
        diagram_path = output_dir / "reliability_diagram.png"

    eval_metrics = compute_eval_metrics(
        y_test, y_cal_test,
        threshold=0.5,
        diagram_path=diagram_path,
        pipeline_run_id="classify_training",
    )

    # ------------------------------------------------------------------
    # 6. Save model
    # ------------------------------------------------------------------
    model_path = output_dir / "xgb_classifier.ubj"
    clf.save_model(str(model_path))

    # Model version: training-date prefix + first 12 hex chars of file SHA-256
    raw_model = model_path.read_bytes()
    sha_hex = hashlib.sha256(raw_model).hexdigest()
    version = f"{datetime.date.today().strftime('%Y%m%d')}-{sha_hex[:12]}"

    # ------------------------------------------------------------------
    # 7. Save calibrator
    # ------------------------------------------------------------------
    calibrator_path = output_dir / "isotonic_calibrator.pkl"
    with open(calibrator_path, "wb") as f:
        pickle.dump(calibrator, f, protocol=pickle.HIGHEST_PROTOCOL)

    # ------------------------------------------------------------------
    # 8. Save evaluation metrics JSON
    # ------------------------------------------------------------------
    eval_metrics_path = output_dir / "eval_metrics.json"
    eval_dict: dict[str, Any] = {
        "precision": eval_metrics.precision,
        "recall": eval_metrics.recall,
        "brier_score": eval_metrics.brier_score,
        "ece": eval_metrics.ece,
        "n_positive": eval_metrics.n_positive,
        "n_negative": eval_metrics.n_negative,
        "threshold": eval_metrics.threshold,
        "calibration_brier_score_on_test_fold": brier_cal,
        "calibration_ece_on_test_fold": ece_cal,
        "n_calibration_samples": len(y_test),
        "model_version": version,
        "dr25_doi": DR25_DOI,
        "training_date": datetime.date.today().isoformat(),
        "feature_names": FEATURE_NAMES,
    }
    eval_metrics_path.write_text(
        json.dumps(eval_dict, indent=2) + "\n", encoding="utf-8"
    )

    # ------------------------------------------------------------------
    # 9. Write model sidecar
    # ------------------------------------------------------------------
    _write_model_sidecar(
        model_path, version, FEATURE_NAMES,
        calibrator_path, split_path, eval_metrics_path, diagram_path,
    )

    calibration_meta = CalibrationMeta(
        method="isotonic",
        calibration_dataset_doi=DR25_DOI,
        calibration_date=datetime.date.today(),
        brier_score=brier_cal,
        ece=ece_cal,
        n_calibration_samples=len(y_test),
    )

    return TrainingResult(
        model_path=model_path,
        model_version=version,
        calibrator_path=calibrator_path,
        split_indices_path=split_path,
        eval_metrics_path=eval_metrics_path,
        reliability_diagram_path=diagram_path,
        eval_metrics=eval_metrics,
        calibration_meta=calibration_meta,
    )
