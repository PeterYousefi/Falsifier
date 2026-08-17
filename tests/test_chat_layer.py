"""
tests/test_chat_layer.py
=========================
Tests for the chat layer: tools, Guardian screening, session degradation.

All tests run without a network connection or LLM API key.
They verify:

  T1. Tools return only artifact-backed numbers (not_available for missing data)
  T2. explain_metric reads only from the committed artifact, never invents text
  T3. Guardian blocks a fabricated number without a source citation
  T4. Guardian blocks a biosignature claim unconditionally
  T5. Guardian passes clean artifact-backed text
  T6. refit_with_params returns a pending_enqueue marker (not a new job itself)
  T7. Session offline_mode responds with templated text when no API key is set
  T8. system_prompt contains the locked claim and all tool names
"""

from __future__ import annotations

import os
import pytest
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fake_job_store():
    """
    Inject a synthetic done job into _job_store for tool tests.

    The job has one TCE with stub vet and search outputs.
    """
    from falsifier.api.chat.tools import _get_job_store
    from falsifier.pipeline.contracts.search import TCE, SearchOutput
    from falsifier.pipeline.contracts.vet import (
        VetOutput, VetInput, VettingTestResult, VETTING_TEST_ORDER,
    )
    from falsifier.pipeline.contracts.manifest import (
        ArtifactRef, StageManifest, UnitedArray,
    )
    from falsifier.api.models import (
        JobRecord, JobRequest, DetectionReport,
        SearchResult, VetResult,
    )
    import datetime
    import uuid
    from pathlib import Path

    run_id = str(uuid.uuid4())
    job_id = "test-job-001"

    def _ref(stage):
        return ArtifactRef(
            path=Path("/dev/null"),
            sha256="a" * 64,
            stage=stage,
            pipeline_run_id=run_id,
        )

    def _manifest(stage, wall=0.1):
        return StageManifest(
            stage=stage,
            code_version="0.1.0-dev",
            input_hash="b" * 64,
            wall_time_seconds=wall,
            provenance=[],
            artifact=_ref(stage),
        )

    tce = TCE(
        tce_id="KIC-11904151-00",
        period=UnitedArray(values=[3.14159], unit="d"),
        period_uncertainty=UnitedArray(values=[0.00001], unit="d"),
        epoch=UnitedArray(values=[2454833.0], unit="bkjd"),
        duration=UnitedArray(values=[1.5], unit="h"),
        depth=UnitedArray(values=[500.0], unit="ppm"),
        sde=12.3,
        snr=8.7,
        odd_even_mismatch=0.02,
    )

    from falsifier.pipeline.contracts.search import SearchInput
    search_input = SearchInput(
        detrend_artifact=_ref("detrend"),
        period_min=UnitedArray(values=[0.5], unit="d"),
        period_max=UnitedArray(values=[30.0], unit="d"),
        snr_threshold=7.0,
        pipeline_run_id=run_id,
    )
    search_out = SearchOutput(
        input=search_input,
        tces=[tce],
        host_star_id="KIC-11904151",
        tls_version="1.0.31",
        manifest=_manifest("search"),
        artifact=_ref("search"),
    )

    vet_input = VetInput(
        search_artifact=_ref("search"),
        tce_id="KIC-11904151-00",
        pipeline_run_id=run_id,
    )
    test_results = [
        VettingTestResult(
            test_name=name,
            outcome="PASS",
            reason=f"{name} passed",
        )
        for name in VETTING_TEST_ORDER
    ]
    vet_out = VetOutput(
        input=vet_input,
        tce_id="KIC-11904151-00",
        host_star_id="KIC-11904151",
        test_results=test_results,
        disposition="candidate",
        triggering_test=None,
        triggering_reason=None,
        manifest=_manifest("vet"),
        artifact=_ref("vet"),
    )

    report = DetectionReport(
        job_id=job_id,
        target_id="KIC 11904151",
        pipeline_run_id=run_id,
        started_at=datetime.datetime.now(tz=datetime.timezone.utc),
        finished_at=datetime.datetime.now(tz=datetime.timezone.utc),
        search=SearchResult(
            host_star_id="KIC-11904151",
            n_tces=1,
            tls_version="1.0.31",
            wall_time_seconds=0.1,
            tce_ids=["KIC-11904151-00"],
        ),
        vet=[VetResult(
            tce_id="KIC-11904151-00",
            disposition="candidate",
            triggering_test=None,
            triggering_reason=None,
            wall_time_seconds=0.1,
        )],
    )

    req = JobRequest(target_id="KIC 11904151")
    record = JobRecord(
        job_id=job_id,
        status="done",
        request=req,
        pipeline_run_id=run_id,
        report=report,
    )
    # Attach raw outputs (normally set by queue worker)
    record._search_out = search_out  # type: ignore[attr-defined]
    record._vet_outs = [vet_out]  # type: ignore[attr-defined]

    store = _get_job_store()
    original = dict(store)
    store[job_id] = record
    yield job_id, tce, vet_out
    # Restore store
    store.clear()
    store.update(original)


# ---------------------------------------------------------------------------
# T1 — tools return artifact-backed numbers
# ---------------------------------------------------------------------------

@pytest.mark.no_network
def test_tool_get_planet_params_reads_artifact(fake_job_store):
    """get_planet_params returns values from the SearchOutput TCE object."""
    from falsifier.api.chat.tools import get_planet_params

    job_id, tce, _ = fake_job_store
    result = get_planet_params(job_id, tce.tce_id)

    assert not result.get("not_available"), result
    assert result["period_days"] == pytest.approx(tce.period.values[0])
    assert result["depth_ppm"] == pytest.approx(tce.depth.values[0])
    assert result["source"] == "search_output"
    assert "job_id" in result


@pytest.mark.no_network
def test_tool_get_planet_params_missing_job():
    """get_planet_params returns not_available for an unknown job_id."""
    from falsifier.api.chat.tools import get_planet_params

    result = get_planet_params("nonexistent-job", "any-tce")
    assert result["not_available"] is True
    assert "not found" in result["reason"]


# ---------------------------------------------------------------------------
# T2 — explain_metric reads only from committed artifact
# ---------------------------------------------------------------------------

@pytest.mark.no_network
def test_explain_metric_reads_artifact():
    """explain_metric returns content from stage_explanations.json."""
    from falsifier.api.chat.tools import explain_metric

    result = explain_metric("vet")
    assert not result.get("not_available"), result
    assert "explanation" in result
    assert result["source"].endswith("stage_explanations.json")
    # The explanation should contain known committed text, not invented content
    assert "seven" in result["explanation"].get("summary", "").lower() or \
           "vetting" in result["explanation"].get("title", "").lower()


@pytest.mark.no_network
def test_explain_metric_not_available_for_unknown():
    """explain_metric returns not_available for an unregistered metric name."""
    from falsifier.api.chat.tools import explain_metric

    result = explain_metric("totally_made_up_metric_xyz")
    assert result.get("not_available") is True
    assert "non_claims" in result  # non_claims returned even on not_available


# ---------------------------------------------------------------------------
# T3 — Guardian blocks unsourced number
# ---------------------------------------------------------------------------

@pytest.mark.no_network
def test_guardian_blocks_fabricated_number():
    """
    Guardian heuristic blocks a floating-point result with units but no
    [source: tool(args)] citation.
    """
    from falsifier.api.chat.guardian import screen

    bad_text = (
        "The planet has a period of 3.14159 days and a depth of 500.000 ppm."
    )
    verdict = screen(bad_text, use_model=False)
    assert not verdict.safe
    assert verdict.risk_label == "fabricated_number"
    assert "[Output blocked" in verdict.screened
    assert verdict.original == bad_text


@pytest.mark.no_network
def test_guardian_passes_sourced_number():
    """Guardian allows text where every number has an adjacent source citation."""
    from falsifier.api.chat.guardian import screen

    good_text = (
        "The period is 3.14159 days "
        "[source: get_planet_params(job-001, KIC-11904151-00)]."
    )
    verdict = screen(good_text, use_model=False)
    assert verdict.safe
    assert verdict.risk_label == "safe"
    assert verdict.screened == good_text


# ---------------------------------------------------------------------------
# T4 — Guardian blocks biosignature claim
# ---------------------------------------------------------------------------

@pytest.mark.no_network
def test_guardian_blocks_biosignature_claim():
    """Guardian unconditionally blocks any biosignature language."""
    from falsifier.api.chat.guardian import screen

    bad_text = (
        "This planet shows potential biosignature gases in its atmosphere."
    )
    verdict = screen(bad_text, use_model=False)
    assert not verdict.safe
    assert verdict.risk_label == "biosignature_claim"
    assert "biosignature" in verdict.screened.lower() or "blocked" in verdict.screened.lower()


# ---------------------------------------------------------------------------
# T5 — Guardian passes clean artifact-backed text
# ---------------------------------------------------------------------------

@pytest.mark.no_network
def test_guardian_passes_clean_text():
    """Guardian passes plain explanation text with no numbers or biosignatures."""
    from falsifier.api.chat.guardian import screen

    clean_text = (
        "The vet stage applies seven named tests to each TCE. "
        "Disposition is determined exclusively by the vet stage. "
        "This project is not a biosignature detector."
    )
    verdict = screen(clean_text, use_model=False)
    assert verdict.safe
    assert verdict.screened == clean_text


# ---------------------------------------------------------------------------
# T6 — refit_with_params returns pending_enqueue marker
# ---------------------------------------------------------------------------

@pytest.mark.no_network
def test_refit_with_params_returns_pending_enqueue(fake_job_store):
    """
    refit_with_params must not synchronously enqueue a job — it returns a
    pending_enqueue marker that the async chat route handles.
    """
    from falsifier.api.chat.tools import refit_with_params

    job_id, tce, _ = fake_job_store
    result = refit_with_params(
        job_id=job_id,
        tce_id=tce.tce_id,
        params={"cadence": "short"},
    )
    assert result.get("pending_enqueue") is True
    assert "new_request" in result
    assert result["source_job_id"] == job_id
    assert result["applied_params"] == {"cadence": "short"}


# ---------------------------------------------------------------------------
# T7 — Session offline_mode with no API key
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_offline_mode_no_api_key(fake_job_store):
    """
    When all API key env vars are unset, run_turn returns offline_mode=True
    and a response assembled from committed artifact text only.
    """
    from falsifier.api.chat.session import run_turn

    job_id, tce, _ = fake_job_store
    # Ensure no API keys are set
    with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
        response = await run_turn(
            job_id=job_id,
            message="What is the disposition of the first TCE?",
            history=[],
        )

    assert response.offline_mode is True
    # Reply must be Guardian-screened (verdict is always present)
    assert isinstance(response.reply, str)
    assert len(response.reply) > 0
    # Guardian verdict must report safe (offline text is templated, not hallucinated)
    assert response.guardian_verdict.get("safe") is True


# ---------------------------------------------------------------------------
# T8 — system_prompt contains locked claim and tool names
# ---------------------------------------------------------------------------

@pytest.mark.no_network
def test_system_prompt_contains_locked_claim_and_tools():
    """
    The system prompt must contain the locked claim and every tool name.
    This ensures the LLM is always told about the non-claim and the tools.
    """
    from falsifier.api.chat.system_prompt import build_system_prompt, _LOCKED_CLAIM
    from falsifier.api.chat.tools import TOOL_REGISTRY

    prompt = build_system_prompt(job_id="test-job-001")

    assert "biosignature detector" in prompt
    assert "No exoplanet biosignature has ever been confirmed" in prompt
    for tool_name in TOOL_REGISTRY:
        assert tool_name in prompt, f"Tool {tool_name!r} missing from system prompt"
