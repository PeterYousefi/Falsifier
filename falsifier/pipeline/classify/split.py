"""
falsifier.pipeline.classify.split
====================================
Host-star-grouped train/test splitting for the classify stage.

Policy
------
Train/test splits are **always grouped by host star ID** (AGENTS.md Rule 4).
A random split is never used.  Every ``VetOutput`` belonging to the same host
star falls entirely into train or entirely into test.  This prevents
period-alias and system-structure leakage across the split boundary.

Split index file
----------------
``write_split_indices`` serialises the split to a JSON file committed to the
repository so ``tests/test_no_leakage.py`` can verify disjointness from the
standard library alone, without importing anything from falsifier.

Split index JSON schema
-----------------------
::

    {
      "schema_version": "1",
      "split_method": "GroupShuffleSplit",
      "group_key": "host_star_id",
      "test_size": 0.2,
      "random_state": 42,
      "feature_names": ["odd_even_depth_metric", ...],
      "label_encoding": {"1": "candidate_or_caveats", "0": "false_positive_or_ambiguous"},
      "train": {
        "tce_ids": ["KIC11904151-00", ...],
        "host_star_ids": ["KIC 11904151", ...]
      },
      "test": {
        "tce_ids": ["KIC 6965293-00", ...],
        "host_star_ids": ["KIC 6965293", ...]
      }
    }

The ``train.host_star_ids`` and ``test.host_star_ids`` sets must be disjoint.
``tests/test_no_leakage.py`` asserts this with one line.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from .features import FEATURE_NAMES

__all__ = [
    "grouped_split",
    "write_split_indices",
    "load_split_indices",
    "DEFAULT_SPLIT_PATH",
]

DEFAULT_SPLIT_PATH = Path("data/splits/classify_split_indices.json")
"""
Default path for the committed split-index file.
``tests/test_no_leakage.py`` reads from this path.
"""


# ---------------------------------------------------------------------------
# Grouped split
# ---------------------------------------------------------------------------

def grouped_split(
    tce_ids: list[str],
    host_star_ids: list[str],
    labels: np.ndarray,
    *,
    test_size: float = 0.2,
    random_state: int = 42,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Split *tce_ids* into train and test indices using ``GroupShuffleSplit``
    with ``groups=host_star_ids``.

    Every TCE belonging to the same host star is assigned entirely to one
    partition — never split across the boundary.

    Parameters
    ----------
    tce_ids : list[str]
        Identifiers for each example (one per row of the feature matrix).
    host_star_ids : list[str]
        Host star group key, one per TCE.  Must be the same length as
        ``tce_ids``.
    labels : np.ndarray, shape (N,)
        Binary labels (0/1).
    test_size : float
        Fraction of **host stars** (not TCEs) to hold out for test.
    random_state : int
        Seed for reproducibility.

    Returns
    -------
    (train_indices, test_indices) — 1-D integer arrays of row indices.

    Raises
    ------
    ValueError
        If ``len(tce_ids) != len(host_star_ids)`` or if any host star
        appears in both partitions (defensive check after sklearn split).
    """
    from sklearn.model_selection import GroupShuffleSplit

    n = len(tce_ids)
    if len(host_star_ids) != n or len(labels) != n:
        raise ValueError(
            f"tce_ids, host_star_ids, and labels must all have the same length; "
            f"got {n}, {len(host_star_ids)}, {len(labels)}"
        )

    gss = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=random_state)
    groups = np.array(host_star_ids)
    X_dummy = np.zeros((n, 1))

    train_idx, test_idx = next(gss.split(X_dummy, labels, groups=groups))

    # Defensive: verify no host star appears in both partitions
    train_hosts = set(groups[train_idx])
    test_hosts = set(groups[test_idx])
    overlap = train_hosts & test_hosts
    if overlap:
        raise ValueError(
            f"GroupShuffleSplit produced overlapping host star groups: {overlap}\n"
            "This is a bug in the split implementation."
        )

    return train_idx, test_idx


# ---------------------------------------------------------------------------
# Write / load split indices
# ---------------------------------------------------------------------------

def write_split_indices(
    tce_ids: list[str],
    host_star_ids: list[str],
    train_idx: np.ndarray,
    test_idx: np.ndarray,
    *,
    test_size: float,
    random_state: int,
    path: Path = DEFAULT_SPLIT_PATH,
) -> Path:
    """
    Serialise split indices to a JSON file for auditability and the
    no-leakage test.

    Parameters
    ----------
    tce_ids, host_star_ids : list[str]
        Full list of identifiers (all N examples, before splitting).
    train_idx, test_idx : np.ndarray
        Row indices output by ``grouped_split``.
    path : Path
        Destination path.  Parent directories are created if absent.

    Returns
    -------
    Path  — the path written to.
    """
    tce_arr = np.array(tce_ids)
    host_arr = np.array(host_star_ids)

    payload: dict[str, Any] = {
        "schema_version": "1",
        "split_method": "GroupShuffleSplit",
        "group_key": "host_star_id",
        "test_size": test_size,
        "random_state": random_state,
        "feature_names": FEATURE_NAMES,
        "label_encoding": {
            "1": "candidate_or_caveats",
            "0": "false_positive_or_ambiguous",
        },
        "train": {
            "tce_ids": tce_arr[train_idx].tolist(),
            "host_star_ids": host_arr[train_idx].tolist(),
        },
        "test": {
            "tce_ids": tce_arr[test_idx].tolist(),
            "host_star_ids": host_arr[test_idx].tolist(),
        },
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def load_split_indices(path: Path = DEFAULT_SPLIT_PATH) -> dict[str, Any]:
    """
    Load a previously written split-index JSON.

    Parameters
    ----------
    path : Path
        Path to the split-index JSON file.  Defaults to
        ``data/splits/classify_split_indices.json``.

    Returns
    -------
    dict
        Full split-index payload with keys ``"train"`` and ``"test"``, each
        containing ``"tce_ids"`` and ``"host_star_ids"`` lists.  Also
        includes metadata keys: ``"schema_version"``, ``"split_method"``,
        ``"group_key"``, ``"test_size"``, ``"random_state"``,
        ``"feature_names"``, ``"label_encoding"``.

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    json.JSONDecodeError
        If the file is not valid JSON.
    """
    with open(path, encoding="utf-8") as f:
        return json.load(f)
