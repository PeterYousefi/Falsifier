"""
falsifier.pipeline.classify.calibrate
========================================
Isotonic regression calibration for XGBoost raw scores.

Design
------
The calibrator is fitted on the held-out test fold (not the train fold) to
avoid contaminating the training set.  It maps raw XGBoost predicted
probabilities to calibrated probabilities.

``fit_calibrator`` returns the fitted calibrator and its evaluation metrics
(Brier score, ECE) on the same held-out fold.

Bootstrap uncertainty
---------------------
``bootstrap_uncertainty`` estimates the standard deviation of the calibrated
probability for a single prediction by re-fitting the calibrator on B bootstrap
resamples of the calibration fold and computing the standard deviation of
the resulting predictions.  B defaults to 100 — enough for a reliable
standard deviation estimate at low computational cost.

ECE computation
---------------
Expected Calibration Error is computed with 10 equal-width bins over [0, 1].
Bins with zero predicted samples contribute zero to the weighted sum.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.isotonic import IsotonicRegression

__all__ = [
    "fit_calibrator",
    "calibrated_predict",
    "bootstrap_uncertainty",
    "compute_brier_score",
    "compute_ece",
]


# ---------------------------------------------------------------------------
# Brier score
# ---------------------------------------------------------------------------

def compute_brier_score(y_true: np.ndarray, y_prob: np.ndarray) -> float:
    """
    Brier score: mean squared error between predicted probabilities and
    binary labels.

    Parameters
    ----------
    y_true : np.ndarray, shape (N,), dtype int {0, 1}
    y_prob : np.ndarray, shape (N,), dtype float, range [0, 1]

    Returns
    -------
    float in [0.0, 1.0]
    """
    y_true = np.asarray(y_true, dtype=np.float64)
    y_prob = np.clip(np.asarray(y_prob, dtype=np.float64), 0.0, 1.0)
    return float(np.mean((y_prob - y_true) ** 2))


# ---------------------------------------------------------------------------
# Expected Calibration Error
# ---------------------------------------------------------------------------

def compute_ece(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    n_bins: int = 10,
) -> float:
    """
    Expected Calibration Error with equal-width bins.

    ECE = Σ_b (|B_b| / N) * |acc(B_b) - conf(B_b)|

    where acc(B_b) is the fraction of positives in bin b and conf(B_b) is
    the mean predicted probability in bin b.

    Parameters
    ----------
    y_true : np.ndarray, shape (N,)
    y_prob : np.ndarray, shape (N,), range [0, 1]
    n_bins : int
        Number of equal-width bins.

    Returns
    -------
    float >= 0.0
    """
    y_true = np.asarray(y_true, dtype=np.float64)
    y_prob = np.clip(np.asarray(y_prob, dtype=np.float64), 0.0, 1.0)
    n = len(y_true)
    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    for lo, hi in zip(bin_edges[:-1], bin_edges[1:]):
        mask = (y_prob >= lo) & (y_prob < hi)
        if mask.sum() == 0:
            continue
        acc = y_true[mask].mean()
        conf = y_prob[mask].mean()
        ece += (mask.sum() / n) * abs(acc - conf)
    return float(ece)


# ---------------------------------------------------------------------------
# Calibrator fit
# ---------------------------------------------------------------------------

def fit_calibrator(
    y_true_cal: np.ndarray,
    y_raw_cal: np.ndarray,
) -> tuple[IsotonicRegression, float, float]:
    """
    Fit an isotonic regression calibrator on a held-out calibration fold.

    Parameters
    ----------
    y_true_cal : np.ndarray, shape (N,)
        True binary labels on the calibration fold.
    y_raw_cal : np.ndarray, shape (N,)
        Raw XGBoost predicted probabilities on the calibration fold.

    Returns
    -------
    (calibrator, brier_score, ece)
        calibrator  — fitted IsotonicRegression instance
        brier_score — Brier score on the calibration fold after calibration
        ece         — Expected Calibration Error after calibration
    """
    calibrator = IsotonicRegression(out_of_bounds="clip")
    y_raw_cal = np.clip(y_raw_cal, 0.0, 1.0)
    calibrator.fit(y_raw_cal, y_true_cal)
    y_cal = calibrator.predict(y_raw_cal)
    bs = compute_brier_score(y_true_cal, y_cal)
    ece = compute_ece(y_true_cal, y_cal)
    return calibrator, bs, ece


def calibrated_predict(
    calibrator: IsotonicRegression,
    y_raw: np.ndarray,
) -> np.ndarray:
    """Apply a fitted isotonic calibrator to raw predictions."""
    return np.clip(calibrator.predict(np.clip(y_raw, 0.0, 1.0)), 0.0, 1.0)


# ---------------------------------------------------------------------------
# Bootstrap uncertainty
# ---------------------------------------------------------------------------

def bootstrap_uncertainty(
    y_true_cal: np.ndarray,
    y_raw_cal: np.ndarray,
    y_raw_pred: float,
    *,
    n_bootstrap: int = 100,
    random_state: int = 0,
) -> float:
    """
    Estimate the standard deviation of the calibrated probability for a single
    prediction by bootstrapping the calibration fold.

    For each of *n_bootstrap* resamples, a new calibrator is fitted on the
    resample and applied to *y_raw_pred*.  The standard deviation of the
    resulting predictions is returned as the uncertainty estimate.

    Parameters
    ----------
    y_true_cal, y_raw_cal : np.ndarray
        Calibration fold data.
    y_raw_pred : float
        The raw prediction for which uncertainty is sought.
    n_bootstrap : int
        Number of bootstrap resamples.
    random_state : int
        RNG seed.

    Returns
    -------
    float >= 0.0 — standard deviation of bootstrap predictions.
    """
    rng = np.random.default_rng(random_state)
    n = len(y_true_cal)
    preds = np.empty(n_bootstrap, dtype=np.float64)
    for i in range(n_bootstrap):
        idx = rng.integers(0, n, size=n)
        cal = IsotonicRegression(out_of_bounds="clip")
        cal.fit(np.clip(y_raw_cal[idx], 0.0, 1.0), y_true_cal[idx])
        preds[i] = float(np.clip(cal.predict([y_raw_pred]), 0.0, 1.0)[0])
    return float(preds.std())
