"""
tests/test_no_leakage.py
========================
Host-star split leakage test.

Policy: ML train/test splits are grouped by host star ID. Never random-split.
(AGENTS.md Rule 4)

This test reads ``data/splits/classify_split_indices.json`` using stdlib only
(no falsifier imports required) and asserts that the sets of host star IDs in
the train and test partitions are completely disjoint.

The split file is written by ``falsifier.pipeline.classify.split.write_split_indices``
after each training run and committed to the repository.  If the file does not
exist, the test is skipped with an informative message directing the developer
to run ``python -m falsifier.pipeline.classify.train`` first.

Schema validated here (schema_version == "1"):
  {
    "schema_version": "1",
    "split_method": "GroupShuffleSplit",
    "group_key": "host_star_id",
    "train": { "host_star_ids": [...] },
    "test":  { "host_star_ids": [...] }
  }
"""

import json
from pathlib import Path

import pytest

SPLIT_PATH = Path("data/splits/classify_split_indices.json")

_MISSING_MSG = (
    f"{SPLIT_PATH} not found.\n"
    "Run training first to generate the split file:\n"
    "  python -m falsifier.pipeline.classify.train\n"
    "Then commit the resulting data/splits/classify_split_indices.json."
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def split_data() -> dict:
    """Load and return the parsed split-index JSON."""
    if not SPLIT_PATH.exists():
        pytest.skip(_MISSING_MSG)
    with open(SPLIT_PATH, encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Schema integrity
# ---------------------------------------------------------------------------

def test_schema_version_is_1(split_data):
    """Split file must declare schema_version == '1'."""
    assert split_data.get("schema_version") == "1", (
        f"Expected schema_version '1', got {split_data.get('schema_version')!r}"
    )


def test_split_method_is_group_shuffle(split_data):
    """split_method must be 'GroupShuffleSplit' — random splits are prohibited."""
    assert split_data.get("split_method") == "GroupShuffleSplit", (
        f"Expected split_method 'GroupShuffleSplit', got {split_data.get('split_method')!r}\n"
        "AGENTS.md Rule 4: train/test splits must be grouped by host_star_id."
    )


def test_group_key_is_host_star_id(split_data):
    """group_key must be 'host_star_id'."""
    assert split_data.get("group_key") == "host_star_id", (
        f"Expected group_key 'host_star_id', got {split_data.get('group_key')!r}"
    )


def test_train_partition_present(split_data):
    """Split file must contain a non-empty 'train' partition."""
    train = split_data.get("train", {})
    host_ids = train.get("host_star_ids", [])
    assert len(host_ids) > 0, (
        "train.host_star_ids is empty — no training examples recorded."
    )


def test_test_partition_present(split_data):
    """Split file must contain a non-empty 'test' partition."""
    test = split_data.get("test", {})
    host_ids = test.get("host_star_ids", [])
    assert len(host_ids) > 0, (
        "test.host_star_ids is empty — no test examples recorded."
    )


# ---------------------------------------------------------------------------
# Core leakage assertion
# ---------------------------------------------------------------------------

def test_no_host_star_leakage(split_data):
    """
    No host star ID may appear in both train and test partitions.

    This is the primary AGENTS.md Rule 4 gate.  A single overlap means the
    model saw a system during training and is evaluated on data from the same
    system, which inflates performance estimates through period-alias and
    system-structure leakage.
    """
    train_hosts = set(split_data["train"]["host_star_ids"])
    test_hosts = set(split_data["test"]["host_star_ids"])

    overlap = train_hosts & test_hosts
    assert overlap == set(), (
        f"Host star leakage detected — {len(overlap)} star(s) appear in both "
        f"train and test partitions:\n  {sorted(overlap)}\n\n"
        "AGENTS.md Rule 4: splits must be grouped by host_star_id. "
        "Use GroupShuffleSplit — never random-split."
    )


# ---------------------------------------------------------------------------
# TCE ↔ host_star_id length consistency
# ---------------------------------------------------------------------------

def test_train_tce_and_host_lengths_match(split_data):
    """train.tce_ids and train.host_star_ids must have equal length."""
    train = split_data["train"]
    n_tce = len(train.get("tce_ids", []))
    n_host = len(train.get("host_star_ids", []))
    assert n_tce == n_host, (
        f"train partition: len(tce_ids)={n_tce} != len(host_star_ids)={n_host}"
    )


def test_test_tce_and_host_lengths_match(split_data):
    """test.tce_ids and test.host_star_ids must have equal length."""
    test = split_data["test"]
    n_tce = len(test.get("tce_ids", []))
    n_host = len(test.get("host_star_ids", []))
    assert n_tce == n_host, (
        f"test partition: len(tce_ids)={n_tce} != len(host_star_ids)={n_host}"
    )


# ---------------------------------------------------------------------------
# No duplicate TCE IDs within a partition
# ---------------------------------------------------------------------------

def test_no_duplicate_tce_ids_in_train(split_data):
    """Each TCE may appear at most once in the train partition."""
    tce_ids = split_data["train"].get("tce_ids", [])
    dupes = {t for t in tce_ids if tce_ids.count(t) > 1}
    assert not dupes, (
        f"Duplicate TCE IDs in train partition: {sorted(dupes)}"
    )


def test_no_duplicate_tce_ids_in_test(split_data):
    """Each TCE may appear at most once in the test partition."""
    tce_ids = split_data["test"].get("tce_ids", [])
    dupes = {t for t in tce_ids if tce_ids.count(t) > 1}
    assert not dupes, (
        f"Duplicate TCE IDs in test partition: {sorted(dupes)}"
    )


def test_no_tce_id_in_both_partitions(split_data):
    """No TCE ID may appear in both train and test partitions."""
    train_tces = set(split_data["train"].get("tce_ids", []))
    test_tces = set(split_data["test"].get("tce_ids", []))
    overlap = train_tces & test_tces
    assert overlap == set(), (
        f"TCE ID leakage: {len(overlap)} TCE(s) appear in both partitions:\n"
        f"  {sorted(overlap)}"
    )


# ---------------------------------------------------------------------------
# Test-size sanity (informational, not policy)
# ---------------------------------------------------------------------------

def test_test_fraction_is_reasonable(split_data):
    """
    Test partition should be between 10 % and 40 % of all examples.

    This is a sanity guard, not a strict policy — a test_size outside this
    range could be intentional for small datasets.  The test issues a warning
    rather than failing hard.
    """
    n_train = len(split_data["train"].get("host_star_ids", []))
    n_test = len(split_data["test"].get("host_star_ids", []))
    n_total = n_train + n_test
    if n_total == 0:
        pytest.skip("Both partitions empty — nothing to check.")
    fraction = n_test / n_total
    assert 0.05 <= fraction <= 0.50, (
        f"test fraction = {fraction:.2%} (test={n_test}, total={n_total}) is "
        "outside the expected [5%, 50%] range.  "
        "Verify that test_size in grouped_split() was set intentionally."
    )
