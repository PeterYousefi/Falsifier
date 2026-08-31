"""
falsifier.pipeline.classify.features
======================================
Extract the seven-dimensional feature vector from a VetOutput record.

Feature schema
--------------
Each of the seven vetting tests contributes exactly one numeric feature: the
``metric_value`` of its ``VettingTestResult``.  Missing metrics (``None``)
are filled with a sentinel value (``NaN`` by default; the XGBoost tree handles
NaN natively via its internal ``missing`` parameter).

The feature vector is ordered by ``VETTING_TEST_ORDER`` so the column order
is deterministic and matches the column names written into the split-index JSON
and model metadata.

Feature names
-------------
Each feature is named ``"<test_name>_metric"``, e.g.
``"odd_even_depth_metric"``.  These names appear in the model's feature
importance dict and in ``ClassifyOutput.feature_importances``.

Label encoding
--------------
Labels come from the DR25 disposition.  This module provides
``encode_label`` and ``decode_label``:

    1  → candidate (positive class)
    0  → false_positive / ambiguous (negative class)

``candidate_with_caveats`` is treated as positive (1) because it passed all
hard FAIL gates; the calibrated probability score is the tool for quantifying
the remaining uncertainty.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from ..contracts.vet import VETTING_TEST_ORDER, VetOutput

__all__ = [
    "FEATURE_NAMES",
    "extract_features",
    "encode_label",
    "decode_label",
]

# ---------------------------------------------------------------------------
# Feature names — derived from canonical test order
# ---------------------------------------------------------------------------

FEATURE_NAMES: list[str] = [f"{name}_metric" for name in VETTING_TEST_ORDER]
"""
Seven feature column names in canonical order.  These strings are written
into every model artifact sidecar and split-index JSON so the column
correspondence never depends on import order.
"""


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------

def extract_features(vet_output: VetOutput) -> np.ndarray:
    """
    Extract a ``(7,)`` float64 feature vector from *vet_output*.

    Missing ``metric_value`` entries become ``NaN`` so XGBoost can apply its
    native missing-value handling.  The outcome labels (PASS/FAIL/FLAG/INC)
    are NOT encoded as numeric features because the disposition is already
    captured in the training label; including the outcome would leak the label.

    Parameters
    ----------
    vet_output : VetOutput

    Returns
    -------
    np.ndarray, shape (7,), dtype float64
    """
    by_name = {r.test_name: r for r in vet_output.test_results}
    vec = np.empty(7, dtype=np.float64)
    for i, test_name in enumerate(VETTING_TEST_ORDER):
        result = by_name.get(test_name)
        if result is None or result.metric_value is None:
            vec[i] = np.nan
        else:
            vec[i] = float(result.metric_value)
    return vec


def extract_feature_matrix(vet_outputs: list[VetOutput]) -> np.ndarray:
    """
    Extract an ``(N, 7)`` float64 feature matrix from a list of VetOutputs.

    Parameters
    ----------
    vet_outputs : list[VetOutput]
        VetOutput records to vectorise.  An empty list returns a ``(0, 7)``
        array.

    Returns
    -------
    np.ndarray, shape (N, 7), dtype float64
        Row *i* corresponds to ``vet_outputs[i]``.  Missing metrics are
        ``NaN`` (see ``extract_features`` for details).
    """
    if not vet_outputs:
        return np.empty((0, 7), dtype=np.float64)
    return np.stack([extract_features(v) for v in vet_outputs], axis=0)


# ---------------------------------------------------------------------------
# Label encoding
# ---------------------------------------------------------------------------

def encode_label(disposition: str) -> int:
    """
    Encode a disposition string to a binary label.

    Positive class (1): "candidate", "candidate_with_caveats"
    Negative class (0): "false_positive", "ambiguous"

    Parameters
    ----------
    disposition : str

    Returns
    -------
    int — 0 or 1

    Raises
    ------
    ValueError if the disposition is not recognised.
    """
    if disposition in ("candidate", "candidate_with_caveats"):
        return 1
    if disposition in ("false_positive", "ambiguous"):
        return 0
    raise ValueError(
        f"Unknown disposition {disposition!r}; "
        "expected one of: candidate, candidate_with_caveats, false_positive, ambiguous"
    )


def decode_label(label: int) -> str:
    """
    Decode a binary label to a human-readable description.

    1 → ``"candidate_or_caveats"``
    0 → ``"false_positive_or_ambiguous"``

    Parameters
    ----------
    label : int
        Binary label produced by ``encode_label``.

    Returns
    -------
    str
        Human-readable disposition category.

    Raises
    ------
    ValueError
        If *label* is neither 0 nor 1.
    """
    if label == 1:
        return "candidate_or_caveats"
    if label == 0:
        return "false_positive_or_ambiguous"
    raise ValueError(f"Unknown label {label!r}; expected 0 or 1")
