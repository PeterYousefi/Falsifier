"""
tests/test_api_deletion.py
===========================
API-deletion test: pipeline runs end-to-end with every hosted API key unset.

Policy requirement
------------------
With every hosted API key absent from the environment (watsonx.ai, etc.), the
five core pipeline stages must still run and produce a complete
``DetectionReport``.  Only the chat / LLM layer degrades — and even then it
degrades to templated explanations read from committed artifacts, not to
silence.

What this test covers
---------------------
1. Ingest (from injected segments — cache path, no network required).
2. Detrend (stub stage body).
3. Search (stub stage body, empty TCE list — valid quiet-star result).
4. Vet (stub stage body; zero TCEs means zero VetOutputs).
5. Classify (stub, per VetOutput; absent xgboost falls back gracefully).
6. Full ``DetectionReport`` is assembled and all required fields are present.
7. The ``non_claims`` list in the report is non-empty and contains the locked
   biosignature non-claim from AGENTS.md.
8. Chat degradation: the templated explanation file is readable and contains
   all five stage keys and the non_claims list.

What this test does NOT cover
------------------------------
- Real FITS file parsing (that is the golden integration tests).
- Real TLS period search (requires committed FITS files).
- Real XGBoost inference (requires a committed trained model artifact).
- Network access of any kind.

All assertions are on the *structure* of the report (field presence, type
ranges, contract invariants) — not on hardcoded numeric values.

Markers
-------
@pytest.mark.no_network  — conftest blocks all outgoing socket connections.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import pathlib
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Minimal segment factory — mirrors the pattern in test_kepler10_recovery.py
# ---------------------------------------------------------------------------

def _make_minimal_segments():
    """
    Build one LightCurveSegment with 10 synthetic cadences.
    Uses the test-bypass injection path in run_ingest so no network or FITS
    file is required.
    """
    from falsifier.pipeline.contracts.ingest import LightCurveSegment
    from falsifier.pipeline.contracts.manifest import UnitedArray

    n = 10
    time_values = [2454833.0 + i * 0.020833 for i in range(n)]  # ~30-min cadence, BKJD
    flux_values = [1.0] * n
    flux_err_values = [1e-4] * n

    return [
        LightCurveSegment(
            sector=3,
            time=UnitedArray(values=time_values, unit="bkjd"),
            time_scale="tdb",
            time_format="bkjd",
            flux=UnitedArray(values=flux_values, unit="electron / s"),
            flux_err=UnitedArray(values=flux_err_values, unit="electron / s"),
            quality_flags=[0] * n,
            cadence_type="long",
        )
    ]


def _make_minimal_stellar_params():
    """
    Build a minimal StellarParams from Gaia DR3 DOI (no real Gaia query).
    """
    from falsifier.pipeline.contracts.ingest import StellarParams
    from falsifier.pipeline.contracts.manifest import DatasetProvenance, UnitedArray

    return StellarParams(
        gaia_source_id="fake-gaia-id",
        ra_deg=285.6794,
        dec_deg=50.2413,
        ruwe=1.0,
        parallax_over_error=100.0,
        teff=UnitedArray(values=[5700.0], unit="K"),
        teff_uncertainty=UnitedArray(values=[50.0], unit="K"),
        radius=UnitedArray(values=[1.065], unit="solRad"),
        radius_uncertainty=UnitedArray(values=[0.009], unit="solRad"),
        provenance=DatasetProvenance(
            source_doi="10.1051/0004-6361/202243940",
            access_date=datetime.date(2024, 1, 1),
            row_count=1,
            description="Synthetic Gaia DR3 record for API-deletion test",
        ),
    )


# ---------------------------------------------------------------------------
# Helper: unset all known hosted-API-key env vars
# ---------------------------------------------------------------------------

_HOSTED_API_KEYS = [
    # watsonx.ai — the supported inference backend
    "WATSONX_APIKEY",
    # Other hosted-API keys — not supported providers; confirmed to produce no
    # effect when absent (retained so the deletion test is thorough).
    "COHERE_API_KEY",
    "GOOGLE_API_KEY",
    "HUGGINGFACE_API_TOKEN",
    "REPLICATE_API_TOKEN",
    "AI21_API_KEY",
    "TOGETHER_API_KEY",
]


def _env_with_no_api_keys() -> dict:
    """Return os.environ with all hosted API keys removed."""
    env = dict(os.environ)
    for key in _HOSTED_API_KEYS:
        env.pop(key, None)
    return env


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def clean_env(monkeypatch):
    """Monkeypatch os.environ to remove all hosted API keys for this test."""
    for key in _HOSTED_API_KEYS:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def ingest_output(clean_env):
    """
    Run run_ingest with injected segments and stellar params.
    No network, no cache, no FITS files.
    """
    from falsifier.pipeline.contracts.ingest import IngestInput
    from falsifier.pipeline.stages.ingest import run_ingest

    ingest_input = IngestInput(
        target_id="KIC 11904151",
        mission="Kepler",
        author="Kepler",
        cadence="long",
        sectors=[3],
        pipeline_run_id="test-run-api-deletion",
    )
    return run_ingest(
        ingest_input,
        _segments=_make_minimal_segments(),
        _stellar_params=_make_minimal_stellar_params(),
    )


@pytest.fixture
def detrend_output(ingest_output, clean_env):
    """Run the detrend stub on the ingest output."""
    from falsifier.api.queue import _stub_detrend
    return _stub_detrend(ingest_output, "test-run-api-deletion")


@pytest.fixture
def search_output(detrend_output, clean_env):
    """Run the search stub on the detrend output."""
    from falsifier.api.queue import _stub_search
    return _stub_search(detrend_output, "test-run-api-deletion")


@pytest.fixture
def vet_outputs(search_output, clean_env):
    """Run the vet stub on the search output (produces empty list for zero TCEs)."""
    from falsifier.api.queue import _stub_vet
    return _stub_vet(search_output, "test-run-api-deletion")


@pytest.fixture
def classify_outputs(vet_outputs, clean_env):
    """Run the classify stub on each VetOutput."""
    from falsifier.api.queue import _stub_classify
    return [_stub_classify(vo, "test-run-api-deletion") for vo in vet_outputs]


# ---------------------------------------------------------------------------
# Stage-by-stage structural assertions
# ---------------------------------------------------------------------------

@pytest.mark.no_network
def test_ingest_runs_without_api_keys(ingest_output):
    """Ingest produces a valid IngestOutput with no hosted API key present."""
    from falsifier.pipeline.contracts.ingest import IngestOutput

    assert isinstance(ingest_output, IngestOutput)
    assert ingest_output.host_star_id == "KIC 11904151"
    assert len(ingest_output.segments) >= 1
    # Provenance invariant: code_version always present
    assert ingest_output.manifest.code_version
    # Units are always explicit on physical arrays
    assert ingest_output.segments[0].time.unit == "bkjd"
    assert ingest_output.segments[0].flux.unit == "electron / s"


@pytest.mark.no_network
def test_detrend_runs_without_api_keys(detrend_output):
    """Detrend stub produces a valid DetrendOutput."""
    from falsifier.pipeline.contracts.detrend import DetrendOutput

    assert isinstance(detrend_output, DetrendOutput)
    assert detrend_output.host_star_id == "KIC 11904151"
    assert len(detrend_output.segments) >= 1
    assert detrend_output.detrending_method == "biweight"
    # Time metadata must propagate unchanged
    seg = detrend_output.segments[0]
    assert seg.time_scale == "tdb"
    assert seg.time_format == "bkjd"
    # Normalised flux must be dimensionless
    assert seg.flux.unit == "dimensionless"
    # Trend flux must be in original units
    assert seg.trend_flux.unit == "electron / s"


@pytest.mark.no_network
def test_search_runs_without_api_keys(search_output):
    """Search stub produces a valid SearchOutput (empty TCE list for flat star)."""
    from falsifier.pipeline.contracts.search import SearchOutput

    assert isinstance(search_output, SearchOutput)
    assert search_output.host_star_id == "KIC 11904151"
    # Empty TCE list is a valid result for a star with no transit signal
    assert isinstance(search_output.tces, list)
    assert search_output.tls_version  # non-empty
    assert search_output.manifest.stage == "search"


@pytest.mark.no_network
def test_vet_runs_without_api_keys(vet_outputs):
    """
    Vet stub returns zero VetOutputs when search found zero TCEs.
    Zero TCEs is valid — it means the star is quiet.
    """
    # With no TCEs from search, vet produces an empty list — that IS a
    # complete result for a quiet target.
    assert isinstance(vet_outputs, list)
    assert len(vet_outputs) == 0  # no TCEs to vet


@pytest.mark.no_network
def test_classify_runs_without_api_keys(classify_outputs):
    """Classify stub produces one ClassifyOutput per VetOutput (zero here)."""
    # Symmetric with the zero-TCE case above
    assert isinstance(classify_outputs, list)
    assert len(classify_outputs) == 0


@pytest.mark.no_network
def test_classify_stub_contract_valid_when_vet_has_tces(clean_env):
    """
    When a VetOutput is present, the classify stub returns a ClassifyOutput
    that satisfies all Pydantic contract invariants.
    """
    from falsifier.api.queue import _stub_classify, _stub_vet, _stub_search, _stub_detrend
    from falsifier.pipeline.contracts.classify import ClassifyOutput
    from falsifier.pipeline.contracts.ingest import IngestInput
    from falsifier.pipeline.stages.ingest import run_ingest
    from falsifier.pipeline.contracts.manifest import UnitedArray
    from falsifier.pipeline.contracts.search import TCE

    # Build a SearchOutput that has one synthetic TCE
    from falsifier.pipeline.contracts.manifest import ArtifactRef
    from falsifier.pipeline.contracts.manifest import StageManifest, DatasetProvenance
    from falsifier.pipeline.contracts.search import SearchInput, SearchOutput
    import falsifier
    from pathlib import Path

    run_id = "test-tce-classify"
    dummy_ref = ArtifactRef(
        path=Path("/dev/null"), sha256="0" * 64,
        stage="search", pipeline_run_id=run_id,
    )
    tce = TCE(
        tce_id="KIC 11904151-00",
        period=UnitedArray(values=[0.8375], unit="d"),
        period_uncertainty=UnitedArray(values=[1e-4], unit="d"),
        epoch=UnitedArray(values=[2454833.5], unit="bkjd"),
        duration=UnitedArray(values=[1.5], unit="h"),
        depth=UnitedArray(values=[150.0], unit="ppm"),
        sde=12.5,
        snr=8.3,
        odd_even_mismatch=0.05,
    )
    search_out = SearchOutput(
        input=SearchInput(
            detrend_artifact=dummy_ref,
            period_min=UnitedArray(values=[0.5], unit="d"),
            period_max=UnitedArray(values=[30.0], unit="d"),
            snr_threshold=7.0,
            pipeline_run_id=run_id,
        ),
        tces=[tce],
        host_star_id="KIC 11904151",
        tls_version="stub-0.0.0",
        manifest=StageManifest(
            stage="search",
            code_version=falsifier.__version__,
            input_hash="0" * 64,
            wall_time_seconds=0.001,
            provenance=[],
            artifact=dummy_ref,
        ),
        artifact=dummy_ref,
    )

    vet_outs = _stub_vet(search_out, run_id)
    assert len(vet_outs) == 1

    classify_out = _stub_classify(vet_outs[0], run_id)
    assert isinstance(classify_out, ClassifyOutput)

    # Contract invariants
    assert 0.0 <= classify_out.probability <= 1.0
    assert classify_out.probability_uncertainty >= 0.0
    assert classify_out.tce_id == "KIC 11904151-00"
    # Classifier must carry NO disposition field (Sub-Task 10 gate)
    assert "disposition" not in ClassifyOutput.model_fields


# ---------------------------------------------------------------------------
# Full report assembly
# ---------------------------------------------------------------------------

@pytest.mark.no_network
def test_complete_report_assembled_without_api_keys(
    ingest_output, detrend_output, search_output, vet_outputs, classify_outputs, clean_env
):
    """
    The complete DetectionReport is assembled from all stage outputs.
    Every required top-level field is present and type-correct.
    """
    from falsifier.api.queue import _build_report
    from falsifier.api.models import DetectionReport, JobRequest

    req = JobRequest(target_id="KIC 11904151")
    started_at = datetime.datetime.now(tz=datetime.timezone.utc)

    report = _build_report(
        job_id="test-job",
        req=req,
        run_id="test-run-api-deletion",
        started_at=started_at,
        ingest_out=ingest_output,
        detrend_out=detrend_output,
        search_out=search_output,
        vet_outs=vet_outputs,
        classify_outs=classify_outputs,
    )

    assert isinstance(report, DetectionReport)
    assert report.job_id == "test-job"
    assert report.target_id == "KIC 11904151"
    assert report.pipeline_run_id == "test-run-api-deletion"

    # Ingest section present
    assert report.ingest is not None
    assert report.ingest.host_star_id == "KIC 11904151"
    assert report.ingest.n_segments >= 1
    assert report.ingest.has_stellar_params is True

    # Detrend section present
    assert report.detrend is not None
    assert report.detrend.detrending_method == "biweight"

    # Search section present
    assert report.search is not None
    assert report.search.n_tces == 0  # quiet star — no TCEs

    # Vet and classify lists are empty (no TCEs), not absent
    assert report.vet == []
    assert report.classify == []

    # non_claims are always present and contain the locked claim
    assert len(report.non_claims) >= 1
    biosig_claim_present = any(
        "biosignature" in c.lower() for c in report.non_claims
    )
    assert biosig_claim_present, (
        "DetectionReport.non_claims must include the AGENTS.md biosignature non-claim.\n"
        f"  Got: {report.non_claims}"
    )


# ---------------------------------------------------------------------------
# Non-claim invariant
# ---------------------------------------------------------------------------

@pytest.mark.no_network
def test_report_non_claims_include_locked_biosignature_claim(
    ingest_output, detrend_output, search_output, vet_outputs, classify_outputs, clean_env
):
    """
    The locked claim from AGENTS.md must appear in every DetectionReport.
    This test is deliberately redundant with the assembly test above —
    the locked claim is important enough to warrant its own gate.
    """
    from falsifier.api.queue import _build_report
    from falsifier.api.models import JobRequest

    req = JobRequest(target_id="KIC 11904151")
    started_at = datetime.datetime.now(tz=datetime.timezone.utc)
    report = _build_report(
        job_id="test-job-nc",
        req=req,
        run_id="test-run-nc",
        started_at=started_at,
        ingest_out=ingest_output,
        detrend_out=detrend_output,
        search_out=search_output,
        vet_outs=vet_outputs,
        classify_outs=classify_outputs,
    )

    locked = "not a biosignature detector"
    assert any(locked.lower() in c.lower() for c in report.non_claims), (
        f"Locked AGENTS.md claim missing from DetectionReport.non_claims.\n"
        f"  Expected to find: {locked!r}\n"
        f"  Got: {report.non_claims}"
    )


# ---------------------------------------------------------------------------
# Chat degradation — templated explanations are readable
# ---------------------------------------------------------------------------

@pytest.mark.no_network
def test_chat_degrades_to_templated_explanations_when_no_api_key(clean_env):
    """
    With no hosted API key set, the pipeline still produces a complete report.
    The chat layer degrades to templated explanations read from committed
    artifacts in data/artifacts/explanations/.

    This test asserts that:
      - The explanation file exists and is valid JSON.
      - It contains entries for all five pipeline stages.
      - It contains the non_claims list.
      - None of the explanation texts contain hardcoded numeric values
        (any bare float that looks like a scientific measurement is prohibited).
    """
    import re

    explanations_path = (
        pathlib.Path(__file__).parent.parent
        / "data" / "artifacts" / "explanations" / "stage_explanations.json"
    )

    assert explanations_path.exists(), (
        f"Templated explanation file not found: {explanations_path}\n"
        "The chat degradation path requires this committed artifact."
    )

    with open(explanations_path, encoding="utf-8") as f:
        data = json.load(f)

    # All five stages must be present
    required_stages = {"ingest", "detrend", "search", "vet", "classify"}
    present_stages = set(data.get("stages", {}).keys())
    missing = required_stages - present_stages
    assert not missing, (
        f"Explanation file is missing entries for stages: {missing}\n"
        f"  path: {explanations_path}"
    )

    # non_claims list must be present and non-empty
    non_claims = data.get("non_claims", [])
    assert len(non_claims) >= 1, (
        "Explanation file must contain a non_claims list."
    )

    biosig_present = any("biosignature" in c.lower() for c in non_claims)
    assert biosig_present, (
        "Explanation non_claims must include the AGENTS.md biosignature non-claim.\n"
        f"  Got: {non_claims}"
    )

    # Each stage entry must have summary, what_it_does_not_do
    for stage_name in required_stages:
        stage_entry = data["stages"][stage_name]
        assert "summary" in stage_entry, (
            f"Stage {stage_name!r} explanation missing 'summary' field."
        )
        assert "what_it_does_not_do" in stage_entry, (
            f"Stage {stage_name!r} explanation missing 'what_it_does_not_do' field."
        )

    # Verify no hosted API key needed to read this file
    for key in _HOSTED_API_KEYS:
        assert os.environ.get(key) is None, (
            f"Hosted API key {key!r} was unexpectedly set during chat-degradation test."
        )


@pytest.mark.no_network
def test_explanation_file_has_no_hardcoded_scientific_numbers(clean_env):
    """
    AGENTS.md Rule 1: no hardcoded scientific values in UI/API code or artifacts
    that originate from pipeline runs.  The explanation file contains only prose;
    it must not embed numeric measurements that should come from stage outputs.

    We check for patterns like standalone floats (e.g. "0.83749070") that look
    like measured quantities.  DOIs (10.xxxx/...) are explicitly excluded.
    """
    import re

    explanations_path = (
        pathlib.Path(__file__).parent.parent
        / "data" / "artifacts" / "explanations" / "stage_explanations.json"
    )
    if not explanations_path.exists():
        pytest.skip("Explanation file not present yet")

    with open(explanations_path, encoding="utf-8") as f:
        raw_text = f.read()

    # Remove DOIs (10.xxxx/...) — these are allowed citations
    text_no_dois = re.sub(r'10\.\d{4,}/\S+', '', raw_text)

    # A "scientific float" is a decimal number with ≥5 significant digits
    # that looks like a measured value, not a version or schema number
    sci_float_re = re.compile(r'\b\d+\.\d{5,}\b')
    matches = sci_float_re.findall(text_no_dois)

    assert not matches, (
        "Explanation file contains what appears to be hardcoded scientific values "
        "(bare floats with ≥5 decimal places).  AGENTS.md Rule 1 prohibits this.\n"
        f"  Matches: {matches}\n"
        f"  path: {explanations_path}\n"
        "If these are intentional non-measured numbers (e.g. year references), "
        "reduce their precision or annotate with a comment."
    )


# ---------------------------------------------------------------------------
# T-DISTINCT — two different target_ids produce two different DetectionReports
# ---------------------------------------------------------------------------
# This is the regression gate for the "same result for any ID" symptom.
#
# We do NOT test the MAST-fetch path here (that requires network access).
# Instead we test the only layer where silent same-result behaviour could
# occur inside the backend:
#
#   1. _build_report reads target_id from req.target_id (the submitted request),
#      not from a default or from the ingest output.  If this were wrong, both
#      jobs would show the same target in their report.
#
#   2. The cache key is derived from the normalised target_id (plus mission/
#      cadence/sectors).  If there were a key collision, different targets would
#      hit the same cache entry.  We verify the cache keys are distinct.
#
#   3. The DetectionReport for target A must not be the same object as for
#      target B even when the underlying segment data happens to be identical
#      (it never is in practice, but we test the report metadata).
#
# Tests are marked @pytest.mark.no_network — no sockets opened.

@pytest.mark.no_network
def test_distinct_target_ids_produce_distinct_ingest_cache_keys():
    """
    Cache keys for different target_ids must never collide.

    The cache key includes the normalised target_id, so this test guards
    against any normalisation bug that could cause two different targets to
    hash to the same cache entry (which would produce the same MAST data for
    both).
    """
    from falsifier.pipeline.contracts.ingest import IngestInput
    from falsifier.pipeline.stages.ingest import _mast_cache_query, normalise_target_id
    from falsifier.pipeline.ingest.cache import query_hash

    targets = [
        "KIC 11904151",   # Kepler-10 golden
        "KIC 7272437",    # quiet-star injection-recovery target
        "KIC 5084157",    # quiet-star injection-recovery target
        "KIC 7347849",    # quiet-star injection-recovery target
        "KIC 8935630",    # quiet-star injection-recovery target
    ]

    run_id = "test-distinct-keys"
    cache_queries = {}
    hashes = {}

    for t in targets:
        inp = IngestInput(
            target_id=t,
            mission="Kepler",
            author="Kepler",
            cadence="long",
            sectors=None,
            pipeline_run_id=run_id,
        )
        q = _mast_cache_query(inp)
        h = query_hash(q)
        cache_queries[t] = q
        hashes[t] = h

    # All query strings must be distinct
    unique_queries = set(cache_queries.values())
    assert len(unique_queries) == len(targets), (
        f"Cache query collision detected: {cache_queries}\n"
        "Two different target_ids are producing the same cache query string."
    )

    # All hashes must be distinct (no SHA-256 collision in this finite set)
    unique_hashes = set(hashes.values())
    assert len(unique_hashes) == len(targets), (
        f"Cache hash collision detected: {hashes}\n"
        "Two different target_ids are hashing to the same cache key."
    )


@pytest.mark.no_network
def test_distinct_target_ids_produce_distinct_normalised_ids():
    """
    normalise_target_id must return a distinct canonical form for each of the
    quiet-star targets used in injection-recovery tests.
    """
    from falsifier.pipeline.stages.ingest import normalise_target_id

    targets = [
        ("KIC 11904151",  "KIC 11904151"),
        ("kic11904151",   "KIC 11904151"),  # no space variant
        ("KIC 7272437",   "KIC 7272437"),
        ("KIC 5084157",   "KIC 5084157"),
        ("KIC 7347849",   "KIC 7347849"),
        ("KIC 8935630",   "KIC 8935630"),
    ]

    for raw, expected in targets:
        got = normalise_target_id(raw)
        assert got == expected, (
            f"normalise_target_id({raw!r}) → {got!r}, expected {expected!r}"
        )


@pytest.mark.no_network
def test_distinct_target_ids_produce_distinct_report_target_fields():
    """
    _build_report must embed the submitted target_id in the returned
    DetectionReport, not a default/fixture value.

    This test guards against the scenario where two different jobs for two
    different targets would both show "KIC 11904151" (or any other fixed
    string) in their reports — the exact symptom described in the issue.

    We call _build_report directly with two different JobRequests and verify
    that the two resulting DetectionReport objects differ in target_id,
    job_id, and pipeline_run_id.
    """
    from falsifier.pipeline.contracts.ingest import IngestInput, IngestOutput
    from falsifier.pipeline.stages.ingest import run_ingest
    from falsifier.api.queue import _stub_detrend, _stub_search, _stub_vet, _stub_classify, _build_report
    from falsifier.api.models import JobRequest, DetectionReport

    # Build two minimal IngestOutputs with distinct target_ids using _segments
    # injection — no network, no cache, no FITS required.
    def _make_segments(n_cadences: int = 10):
        from falsifier.pipeline.contracts.ingest import LightCurveSegment
        from falsifier.pipeline.contracts.manifest import UnitedArray
        return [
            LightCurveSegment(
                sector=3,
                time=UnitedArray(values=[2454833.0 + i * 0.020833 for i in range(n_cadences)], unit="bkjd"),
                time_scale="tdb",
                time_format="bkjd",
                flux=UnitedArray(values=[1.0] * n_cadences, unit="electron / s"),
                flux_err=UnitedArray(values=[1e-4] * n_cadences, unit="electron / s"),
                quality_flags=[0] * n_cadences,
                cadence_type="long",
            )
        ]

    target_a = "KIC 11904151"
    target_b = "KIC 7272437"

    run_id_a = "regression-distinct-a"
    run_id_b = "regression-distinct-b"

    ingest_out_a = run_ingest(
        IngestInput(
            target_id=target_a,
            mission="Kepler",
            author="Kepler",
            cadence="long",
            sectors=None,
            pipeline_run_id=run_id_a,
        ),
        _segments=_make_segments(),
    )

    ingest_out_b = run_ingest(
        IngestInput(
            target_id=target_b,
            mission="Kepler",
            author="Kepler",
            cadence="long",
            sectors=None,
            pipeline_run_id=run_id_b,
        ),
        _segments=_make_segments(),
    )

    # The normalised host_star_id must differ
    assert ingest_out_a.host_star_id != ingest_out_b.host_star_id, (
        f"host_star_id collision: both targets normalised to {ingest_out_a.host_star_id!r}"
    )

    detrend_a = _stub_detrend(ingest_out_a, run_id_a)
    detrend_b = _stub_detrend(ingest_out_b, run_id_b)
    search_a  = _stub_search(detrend_a, run_id_a)
    search_b  = _stub_search(detrend_b, run_id_b)
    vet_a     = _stub_vet(search_a, run_id_a)
    vet_b     = _stub_vet(search_b, run_id_b)

    started = datetime.datetime.now(tz=datetime.timezone.utc)

    report_a = _build_report(
        job_id="job-a",
        req=JobRequest(target_id=target_a),
        run_id=run_id_a,
        started_at=started,
        ingest_out=ingest_out_a,
        detrend_out=detrend_a,
        search_out=search_a,
        vet_outs=vet_a,
        classify_outs=[],
    )

    report_b = _build_report(
        job_id="job-b",
        req=JobRequest(target_id=target_b),
        run_id=run_id_b,
        started_at=started,
        ingest_out=ingest_out_b,
        detrend_out=detrend_b,
        search_out=search_b,
        vet_outs=vet_b,
        classify_outs=[],
    )

    assert isinstance(report_a, DetectionReport)
    assert isinstance(report_b, DetectionReport)

    # --- Core regression assertions ---

    # 1. target_id is taken from the request, not from a default/fixture
    assert report_a.target_id == target_a, (
        f"report_a.target_id={report_a.target_id!r}, expected {target_a!r}\n"
        "_build_report must read target_id from req.target_id, not a default."
    )
    assert report_b.target_id == target_b, (
        f"report_b.target_id={report_b.target_id!r}, expected {target_b!r}\n"
        "_build_report must read target_id from req.target_id, not a default."
    )

    # 2. The two reports have distinct target_ids (the core regression guard)
    assert report_a.target_id != report_b.target_id, (
        "Both DetectionReports have the same target_id — "
        "a different target_id was submitted but the same target appears in both reports.  "
        "This is the 'same result for any ID' bug."
    )

    # 3. job_id and pipeline_run_id are distinct (no identity bleed between jobs)
    assert report_a.job_id != report_b.job_id
    assert report_a.pipeline_run_id != report_b.pipeline_run_id

    # 4. ingest.host_star_id reflects the correct normalised target
    assert report_a.ingest is not None
    assert report_b.ingest is not None
    assert report_a.ingest.host_star_id == "KIC 11904151"
    assert report_b.ingest.host_star_id == "KIC 7272437"
    assert report_a.ingest.host_star_id != report_b.ingest.host_star_id, (
        "ingest.host_star_id is the same for two different targets — "
        "either normalise_target_id collapsed them or the wrong IngestOutput was used."
    )

    # 5. non_claims must be present in both reports (locked claim always travels)
    assert len(report_a.non_claims) >= 1
    assert len(report_b.non_claims) >= 1
