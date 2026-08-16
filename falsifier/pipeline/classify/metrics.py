"""
falsifier.pipeline.classify.metrics
======================================
Evaluation metrics and reliability diagram artifact for the classify stage.

Outputs
-------
``compute_eval_metrics`` returns a ``EvalMetrics`` dataclass with:
  - precision, recall (at threshold=0.5)
  - Brier score
  - Expected Calibration Error
  - path to the reliability diagram PNG artifact

``save_reliability_diagram`` writes a PNG reliability diagram to a given
path and returns an ``ArtifactRef``.  The diagram plots:
  - Fraction of positives vs mean predicted probability per bin
  - The diagonal (perfect calibration)
  - A histogram of prediction confidence in the background

Policy
------
The reliability diagram is a committed artifact — the path and SHA-256 are
recorded in the model metadata so the diagram is reproducible and auditable.
"""

from __future__ import annotations

import datetime
import hashlib
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ..contracts.manifest import ArtifactRef
from .calibrate import compute_brier_score, compute_ece

__all__ = [
    "EvalMetrics",
    "compute_eval_metrics",
    "save_reliability_diagram",
]


# ---------------------------------------------------------------------------
# EvalMetrics dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EvalMetrics:
    """Frozen snapshot of evaluation metrics for one model-evaluation run."""

    precision: float
    recall: float
    brier_score: float
    ece: float
    n_positive: int
    n_negative: int
    threshold: float
    reliability_diagram: ArtifactRef | None
    """ArtifactRef for the saved PNG.  None if diagram was not requested."""


# ---------------------------------------------------------------------------
# Precision / recall
# ---------------------------------------------------------------------------

def _precision_recall_at(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    threshold: float = 0.5,
) -> tuple[float, float]:
    """Return (precision, recall) at *threshold*.  Returns (0, 0) if no predictions."""
    y_pred = (y_prob >= threshold).astype(int)
    tp = int(((y_pred == 1) & (y_true == 1)).sum())
    fp = int(((y_pred == 1) & (y_true == 0)).sum())
    fn = int(((y_pred == 0) & (y_true == 1)).sum())
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    return precision, recall


# ---------------------------------------------------------------------------
# Reliability diagram
# ---------------------------------------------------------------------------

def save_reliability_diagram(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    path: Path,
    *,
    n_bins: int = 10,
    pipeline_run_id: str = "eval",
) -> ArtifactRef:
    """
    Render a reliability (calibration) diagram and save it as a PNG.

    The diagram shows:
      - Fraction of positives vs mean predicted probability per bin
        (solid blue line with markers)
      - The diagonal representing perfect calibration (dashed grey)
      - A bar histogram of prediction confidence in each bin (transparent)

    Parameters
    ----------
    y_true : np.ndarray, shape (N,)
    y_prob : np.ndarray, shape (N,), range [0, 1]
    path : Path
        Destination path for the PNG file.
    n_bins : int
        Number of equal-width calibration bins.
    pipeline_run_id : str
        Embedded in the ArtifactRef.

    Returns
    -------
    ArtifactRef  — points to the saved PNG with its SHA-256.
    """
    import matplotlib
    matplotlib.use("Agg")  # non-interactive backend; safe in CI
    import matplotlib.pyplot as plt

    y_true = np.asarray(y_true, dtype=np.float64)
    y_prob = np.clip(np.asarray(y_prob, dtype=np.float64), 0.0, 1.0)

    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    bin_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])
    fraction_pos = np.full(n_bins, np.nan)
    mean_conf = np.full(n_bins, np.nan)
    bin_counts = np.zeros(n_bins, dtype=int)

    for i, (lo, hi) in enumerate(zip(bin_edges[:-1], bin_edges[1:])):
        mask = (y_prob >= lo) & (y_prob < hi)
        if mask.sum() > 0:
            fraction_pos[i] = y_true[mask].mean()
            mean_conf[i] = y_prob[mask].mean()
            bin_counts[i] = mask.sum()

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(6, 7),
                                   gridspec_kw={"height_ratios": [3, 1]})

    # Top panel: calibration curve
    valid = ~np.isnan(fraction_pos)
    ax1.plot(
        mean_conf[valid], fraction_pos[valid],
        "o-", color="#3b82d4", linewidth=2, markersize=5,
        label="Classifier",
    )
    ax1.plot([0, 1], [0, 1], "--", color="#888", linewidth=1, label="Perfect")
    ax1.set_xlim(0, 1)
    ax1.set_ylim(0, 1)
    ax1.set_xlabel("Mean predicted probability")
    ax1.set_ylabel("Fraction of positives")
    ax1.set_title("Reliability diagram (calibrated)")
    ax1.legend(loc="upper left", fontsize=9)

    # Add ECE annotation
    ece = compute_ece(y_true, y_prob, n_bins=n_bins)
    bs = compute_brier_score(y_true, y_prob)
    ax1.text(
        0.98, 0.04,
        f"ECE = {ece:.4f}\nBrier = {bs:.4f}",
        transform=ax1.transAxes,
        ha="right", va="bottom", fontsize=8,
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.7),
    )

    # Bottom panel: prediction histogram
    ax2.bar(
        bin_centers, bin_counts,
        width=1.0 / n_bins * 0.9,
        color="#3b82d4", alpha=0.5,
        edgecolor="none",
    )
    ax2.set_xlim(0, 1)
    ax2.set_xlabel("Mean predicted probability")
    ax2.set_ylabel("Count")

    plt.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)

    # Compute SHA-256 of the saved PNG
    raw = path.read_bytes()
    sha256 = hashlib.sha256(raw).hexdigest()

    return ArtifactRef(
        path=path.resolve(),
        sha256=sha256,
        stage="classify_eval",
        pipeline_run_id=pipeline_run_id,
    )


# ---------------------------------------------------------------------------
# compute_eval_metrics
# ---------------------------------------------------------------------------

def compute_eval_metrics(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    *,
    threshold: float = 0.5,
    diagram_path: Path | None = None,
    pipeline_run_id: str = "eval",
    n_bins: int = 10,
) -> EvalMetrics:
    """
    Compute all evaluation metrics and optionally save the reliability diagram.

    Parameters
    ----------
    y_true : np.ndarray
    y_prob : np.ndarray  (calibrated)
    threshold : float
        Classification threshold for precision/recall.
    diagram_path : Path | None
        If given, save the reliability diagram PNG here.
    pipeline_run_id : str
    n_bins : int

    Returns
    -------
    EvalMetrics
    """
    precision, recall = _precision_recall_at(y_true, y_prob, threshold)
    bs = compute_brier_score(y_true, y_prob)
    ece = compute_ece(y_true, y_prob, n_bins=n_bins)

    diagram_ref: ArtifactRef | None = None
    if diagram_path is not None:
        diagram_ref = save_reliability_diagram(
            y_true, y_prob, diagram_path,
            n_bins=n_bins,
            pipeline_run_id=pipeline_run_id,
        )

    return EvalMetrics(
        precision=precision,
        recall=recall,
        brier_score=bs,
        ece=ece,
        n_positive=int(y_true.sum()),
        n_negative=int((1 - y_true).sum()),
        threshold=threshold,
        reliability_diagram=diagram_ref,
    )
