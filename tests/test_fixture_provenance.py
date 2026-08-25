"""
tests/test_fixture_provenance.py
==================================
Policy gates for fixture labelling and classifier unavailability.

Items covered
-------------
1. Every view that renders fixture data must expose a provenance badge.
   Gate: the frontend fixture (job.json) must carry a fixture_provenance
   sidecar field; any fixture lacking it must be treated as a policy
   violation.

2. Fixtures used by user-facing views must carry a provenance sidecar.
   Gate: ``frontend/src/fixtures/job.json`` and
   ``frontend/src/fixtures/job_false_positive.json`` must both contain
   a ``fixture_provenance`` key with the required schema fields.

3. Classifier probability must not render when no model artifact exists.
   Gate: the fixture's classify array must be empty (or absent), because
   no trained model artifact is committed. The report view must show an
   explicit unavailable state, not a number.

5. Epoch field must be in the valid BKJD range (100–1600).
   Extending test_time_systems: the epoch_bkjd value in the fixture must
   satisfy the range constraint the upload UI itself documents.

7. Chat tool-call citations must not leak the fixture job_id.
   Gate: committed fixture chat.json and the offline answers in DataSource.ts
   must not contain the string "fixture-job-001" in any source citation,
   because a fixture id in a user-facing citation is misleading.

Markers
-------
@pytest.mark.no_network — no outgoing connections.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

REPO_ROOT    = pathlib.Path(__file__).parent.parent
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"
FIXTURE_JOB  = FRONTEND_SRC / "fixtures" / "job.json"
FIXTURE_EB   = FRONTEND_SRC / "fixtures" / "job_false_positive.json"
FIXTURE_CHAT = FRONTEND_SRC / "fixtures" / "chat.json"
DATASOURCE   = FRONTEND_SRC / "data" / "DataSource.ts"
CANDIDATE_DETAIL = FRONTEND_SRC / "screens" / "CandidateDetail.tsx"
SYSTEM_SCREEN    = FRONTEND_SRC / "screens" / "SystemScreen.tsx"
CHAT_PANEL       = FRONTEND_SRC / "screens" / "ChatPanel.tsx"

# ---------------------------------------------------------------------------
# Required fields for the fixture_provenance sidecar
# ---------------------------------------------------------------------------
_REQUIRED_SIDECAR_FIELDS = frozenset({
    "schema_version",
    "fixture_id",
    "generated_date",
    "note",
})

# Valid BKJD range: Kepler science operations ran from BKJD ~131 to ~1591.
# The upload flow documents the range as 100–1600.
_BKJD_MIN = 100.0
_BKJD_MAX = 1600.0


# ---------------------------------------------------------------------------
# Gate 1 / 2 — fixture_provenance sidecar present and well-formed
# ---------------------------------------------------------------------------

@pytest.mark.no_network
def test_job_fixture_has_fixture_provenance_sidecar():
    """
    frontend/src/fixtures/job.json must carry a top-level fixture_provenance
    field under report.  A fixture lacking this field cannot be labelled in
    the UI and is a policy violation (items 1 and 2).
    """
    with open(FIXTURE_JOB, encoding="utf-8") as f:
        fixture = json.load(f)

    report = fixture.get("report", {})
    sidecar = report.get("fixture_provenance")

    assert sidecar is not None, (
        "frontend/src/fixtures/job.json is missing report.fixture_provenance.\n"
        "Every fixture used by a user-facing view must carry a provenance sidecar\n"
        "so the UI can label it as a fixture, not a live pipeline run.\n"
        "Add a fixture_provenance object with: " + str(sorted(_REQUIRED_SIDECAR_FIELDS))
    )

    missing = _REQUIRED_SIDECAR_FIELDS - set(sidecar.keys())
    assert not missing, (
        f"report.fixture_provenance in job.json is missing required fields: {sorted(missing)}\n"
        f"Required: {sorted(_REQUIRED_SIDECAR_FIELDS)}"
    )

    assert isinstance(sidecar["schema_version"], str) and sidecar["schema_version"], (
        "fixture_provenance.schema_version must be a non-empty string."
    )
    assert isinstance(sidecar["fixture_id"], str) and sidecar["fixture_id"], (
        "fixture_provenance.fixture_id must be a non-empty string."
    )
    assert isinstance(sidecar["note"], str) and sidecar["note"], (
        "fixture_provenance.note must be a non-empty string."
    )


@pytest.mark.no_network
def test_eb_fixture_has_fixture_provenance_sidecar():
    """
    frontend/src/fixtures/job_false_positive.json must also carry
    a fixture_provenance sidecar (items 1 and 2).
    """
    if not FIXTURE_EB.exists():
        pytest.skip("job_false_positive.json not found")

    with open(FIXTURE_EB, encoding="utf-8") as f:
        fixture = json.load(f)

    report = fixture.get("report", {})
    sidecar = report.get("fixture_provenance")

    assert sidecar is not None, (
        "frontend/src/fixtures/job_false_positive.json is missing report.fixture_provenance.\n"
        "All fixtures used by user-facing views must carry a provenance sidecar."
    )

    missing = _REQUIRED_SIDECAR_FIELDS - set(sidecar.keys())
    assert not missing, (
        f"report.fixture_provenance in job_false_positive.json is missing fields: {sorted(missing)}"
    )


# ---------------------------------------------------------------------------
# Gate 3 — classifier array must be empty for the Kepler-10 fixture
# ---------------------------------------------------------------------------

@pytest.mark.no_network
def test_fixture_classify_array_is_empty():
    """
    The Kepler-10 fixture's classify array must be empty (item 3).

    No trained classifier model artifact exists
    (artifacts/classify/xgb_classifier.ubj is absent and 12 leakage tests
    skip).  The fixture must not carry an invented probability, uncertainty,
    or model version string.  The report view must render the explicit
    unavailable state rather than a number.
    """
    with open(FIXTURE_JOB, encoding="utf-8") as f:
        fixture = json.load(f)

    classify = fixture.get("report", {}).get("classify", [])
    assert classify == [], (
        f"frontend/src/fixtures/job.json has a non-empty classify array: {classify}\n"
        "No trained classifier model artifact exists.  The classify array must be\n"
        "empty so the report view renders an explicit unavailable state, not an\n"
        "invented probability.  Remove the entry from the fixture."
    )


# ---------------------------------------------------------------------------
# Gate 3b — CandidateDetail renders unavailable state when classify is empty
# ---------------------------------------------------------------------------

@pytest.mark.no_network
def test_candidate_detail_renders_unavailable_when_no_classify():
    """
    CandidateDetail.tsx must contain a path that renders an explicit
    unavailable state when classifyResult is null/undefined (item 3).

    Verified by checking for the ClassifierUnavailablePanel component or
    an equivalent pattern in the source.
    """
    src = CANDIDATE_DETAIL.read_text(encoding="utf-8")
    # Strip comments
    src = re.sub(r'/\*.*?\*/', ' ', src, flags=re.DOTALL)
    src = re.sub(r'//[^\n]*', ' ', src)

    assert 'ClassifierUnavailablePanel' in src or 'unavailable' in src.lower(), (
        "CandidateDetail.tsx does not appear to render an explicit unavailable state\n"
        "when no classifier result is present.  The report view must show a named\n"
        "blocker, not silently hide the panel."
    )


# ---------------------------------------------------------------------------
# Gate 5 — epoch_bkjd must be in the valid Kepler BKJD range
# ---------------------------------------------------------------------------

@pytest.mark.no_network
def test_fixture_epoch_bkjd_in_valid_range():
    """
    The epoch_bkjd field in the fixture must be in the valid BKJD range
    (100–1600) that the upload flow documents (item 5).

    An epoch of 2454833.528 means the fixture was storing a BJD value in
    the BKJD field — one screen's documented range contradicts the other.
    """
    with open(FIXTURE_JOB, encoding="utf-8") as f:
        fixture = json.load(f)

    vet_results = fixture.get("report", {}).get("vet", [])
    for vet in vet_results:
        epoch = vet.get("epoch_bkjd")
        if epoch is None:
            continue
        assert _BKJD_MIN <= epoch <= _BKJD_MAX, (
            f"epoch_bkjd = {epoch} is outside the valid BKJD range [{_BKJD_MIN}, {_BKJD_MAX}].\n"
            f"BKJD = BJD − 2454833.0. Kepler science operations ran from BKJD ~131 to ~1591.\n"
            f"The upload flow documents the range as 100–1600. An epoch near 2,454,833 means\n"
            f"a BJD value is stored in a BKJD field."
        )


# ---------------------------------------------------------------------------
# Gate 7 — chat citations must not contain fixture job_id
# ---------------------------------------------------------------------------

@pytest.mark.no_network
def test_chat_fixture_citations_do_not_contain_fixture_job_id():
    """
    Committed chat.json must not contain 'fixture-job-001' in any
    source citation string (item 7).

    A fixture job_id in a user-facing citation is misleading: it implies
    the chat tool resolved a real job, not a committed fixture.
    """
    if not FIXTURE_CHAT.exists():
        pytest.skip("chat.json not found")

    text = FIXTURE_CHAT.read_text(encoding="utf-8")
    # Look only inside source-chip-like patterns
    source_chips = re.findall(r'\[source:[^\]]*\]', text)
    leaking = [c for c in source_chips if 'fixture-job-001' in c]
    assert not leaking, (
        f"chat.json contains source citations with the fixture job_id:\n"
        + "\n".join(f"  {c}" for c in leaking)
        + "\nChat citations must identify the TCE or tool, not the fixture id."
    )


@pytest.mark.no_network
def test_datasource_offline_answers_do_not_cite_fixture_job_id():
    """
    The offline answers assembled in DataSource.ts must not contain
    'fixture-job-001' in any [source: ...] chip string (item 7).
    """
    src = DATASOURCE.read_text(encoding="utf-8")
    source_chips = re.findall(r'\[source:[^\]]*\]', src)
    leaking = [c for c in source_chips if 'fixture-job-001' in c]
    assert not leaking, (
        f"DataSource.ts offline answers contain source citations with the fixture job_id:\n"
        + "\n".join(f"  {c}" for c in leaking)
        + "\nChat citations must identify the TCE or tool, not the fixture id.\n"
        "Remove 'fixture-job-001' from [source: ...] strings in DataSource.ts."
    )
