"""
falsifier.pipeline.contracts.classify
=======================================
Pydantic contracts for the classify pipeline stage.

  CalibrationMeta  — metadata about the isotonic calibrator
  ClassifyInput    — pointers to VetOutput and model artifact
  ClassifyOutput   — calibrated probability + uncertainty (no disposition)

Policy
------
ClassifyOutput is a **ranking tool only**.  It carries no disposition field
and must not reference Disposition in any way.  Rankers rank; vetters vet.
Any code that reads ClassifyOutput and branches on a verdict is a policy
violation.
"""

from __future__ import annotations

import datetime
from typing import Literal

from pydantic import BaseModel, field_validator

from .manifest import ArtifactRef, DatasetProvenance, StageManifest

__all__ = [
    "CalibrationMeta",
    "ClassifyInput",
    "ClassifyOutput",
]


# ---------------------------------------------------------------------------
# CalibrationMeta
# ---------------------------------------------------------------------------

class CalibrationMeta(BaseModel):
    """
    Metadata describing the calibrator fitted to the raw XGBoost scores.

    All fields are required so the calibration is fully reproducible from
    the artifact alone.
    """

    method: Literal["isotonic", "platt", "beta"]
    """Calibration method used.  Only isotonic regression is supported in train.py."""

    calibration_dataset_doi: str
    """DOI of the dataset used to fit the calibrator (the held-out fold)."""

    calibration_date: datetime.date
    """ISO-8601 date on which the calibrator was fitted."""

    brier_score: float
    """
    Brier score on the calibration fold.  Lower is better.
    Dimensionless; range [0, 1].
    """

    ece: float
    """
    Expected Calibration Error on the calibration fold.  Lower is better.
    Dimensionless; computed with 10 equal-width bins by default.
    """

    n_calibration_samples: int
    """Number of samples used to fit and evaluate the calibrator."""

    @field_validator("n_calibration_samples")
    @classmethod
    def _n_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(
                f"CalibrationMeta.n_calibration_samples must be >= 1, got {v}"
            )
        return v

    @field_validator("brier_score")
    @classmethod
    def _brier_range(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(
                f"CalibrationMeta.brier_score must be in [0, 1], got {v}"
            )
        return v

    @field_validator("ece")
    @classmethod
    def _ece_nonneg(cls, v: float) -> float:
        if v < 0.0:
            raise ValueError(
                f"CalibrationMeta.ece must be >= 0.0, got {v}"
            )
        return v


# ---------------------------------------------------------------------------
# ClassifyInput
# ---------------------------------------------------------------------------

class ClassifyInput(BaseModel):
    """Pointers to the upstream artifacts consumed by the classify stage."""

    vet_artifact: ArtifactRef
    """Points to the serialised VetOutput on disk."""

    model_artifact: ArtifactRef
    """Points to the serialised XGBoost model artifact (.ubj file) on disk."""

    pipeline_run_id: str


# ---------------------------------------------------------------------------
# ClassifyOutput  — ranking score, no verdict
# ---------------------------------------------------------------------------

class ClassifyOutput(BaseModel):
    """
    Calibrated probability score for one TCE.

    This model deliberately contains no ``disposition`` field and no field
    that could be interpreted as a verdict.  The Sub-Task 10 CI gate asserts:

        assert "disposition" not in ClassifyOutput.model_fields

    Downstream code must read the ``disposition`` from the ``VetOutput``
    artifact, not from this model.
    """

    input: ClassifyInput
    tce_id: str
    host_star_id: str

    probability: float
    """
    Calibrated probability that this TCE is a genuine planet candidate.
    Range [0.0, 1.0].  This is a ranking score, not a verdict.
    """

    probability_uncertainty: float
    """
    Bootstrap uncertainty on ``probability``.  Non-optional: explicit
    uncertainty is required by the project policy (AGENTS.md).
    """

    calibration: CalibrationMeta

    model_version: str
    """
    Semantic version of the trained model, read from the model artifact's
    own metadata JSON sidecar.
    """

    feature_importances: dict[str, float]
    """
    Feature name → SHAP value for this TCE.  Empty dict is valid when SHAP
    was not computed (e.g. in a fast-inference path).
    """

    manifest: StageManifest
    artifact: ArtifactRef

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------

    @field_validator("probability")
    @classmethod
    def _probability_range(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(
                f"ClassifyOutput.probability must be in [0.0, 1.0], got {v}"
            )
        return v

    @field_validator("probability_uncertainty")
    @classmethod
    def _uncertainty_nonneg(cls, v: float) -> float:
        if v < 0.0:
            raise ValueError(
                f"ClassifyOutput.probability_uncertainty must be >= 0.0, got {v}"
            )
        return v
