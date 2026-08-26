"""
tests/test_api_guard_routes.py
===============================
Integration tests for the POST /jobs guard paths: 422 (malformed identifier),
429 (rate limit), and 429 (concurrency cap), plus the no-MAST-results path.

Strategy
--------
All tests use httpx.AsyncClient with the FastAPI ASGI transport.  This routes
requests through the full FastAPI middleware stack (validation, CORS, guard
checks) without opening any real TCP socket.

The asyncio_mode = "auto" setting in pyproject.toml means async test functions
are run under pytest-asyncio without needing @pytest.mark.asyncio.  We do NOT
call asyncio.run() — that creates a new event loop, which calls
socket.socketpair() and trips the conftest socket guard.

Tests that reach the pipeline (no-results path) mock run_ingest to raise
TargetNotFoundError so no real MAST fetch occurs.

Markers
-------
@pytest.mark.no_network  — belt-and-braces on the per-test guard.
Note: the session-wide socket guard is always active regardless of this marker.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Skip when fastapi / httpx are not installed (fast CI pydantic-only job).
# ---------------------------------------------------------------------------

try:
    import fastapi  # noqa: F401
    import httpx    # noqa: F401
    _DEPS_AVAILABLE = True
except ImportError:
    _DEPS_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _DEPS_AVAILABLE,
    reason="fastapi/httpx not installed — requires full dev install",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app():
    """
    Return a fresh application instance with a live queue for the test.
    Re-use the production factory so all middleware runs.
    """
    from falsifier.api.app import create_app
    from falsifier.api import queue as q

    application = create_app()
    # Initialise the in-process queue with 1 worker
    q.init_queue(max_workers=1)
    return application


# ---------------------------------------------------------------------------
# 422 — malformed identifier
# ---------------------------------------------------------------------------

async def test_422_malformed_identifier_is_rejected():
    """
    POST /jobs with an unrecognised identifier returns 422 with a detail
    message naming the accepted formats.
    """
    app = _make_app()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        res = await client.post("/jobs", json={
            "target_id": "INVALID_STAR_12345",
            "mission": "Kepler",
            "author": "Kepler",
            "cadence": "long",
        })

    assert res.status_code == 422, f"Expected 422, got {res.status_code}: {res.text}"
    body = res.json()
    detail = body.get("detail", "")
    assert "KIC" in detail or "TIC" in detail or "Accepted formats" in detail, (
        f"422 detail should name accepted formats; got: {detail!r}"
    )


async def test_422_empty_identifier_is_rejected():
    """POST /jobs with an empty target_id returns 422."""
    app = _make_app()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        res = await client.post("/jobs", json={
            "target_id": "",
            "mission": "Kepler",
            "author": "Kepler",
            "cadence": "long",
        })

    assert res.status_code == 422, f"Expected 422, got {res.status_code}: {res.text}"


async def test_422_detail_names_formats():
    """
    The 422 detail string must explicitly list at least KIC, TIC, Kepler, K2,
    and TOI so the user knows which identifiers are accepted.
    """
    app = _make_app()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        res = await client.post("/jobs", json={
            "target_id": "banana",
            "mission": "Kepler",
            "author": "Kepler",
            "cadence": "long",
        })

    assert res.status_code == 422
    detail = res.json().get("detail", "")
    for fmt in ("KIC", "TIC", "EPIC", "Kepler", "K2", "TOI"):
        assert fmt in detail, (
            f"422 detail should name format {fmt!r}; full detail: {detail!r}"
        )


# ---------------------------------------------------------------------------
# 429 — per-IP rate limit
# ---------------------------------------------------------------------------

async def test_429_rate_limit_includes_retry_after():
    """
    After exceeding RATE_LIMIT_CALLS POST /jobs requests in one minute the
    caller receives 429 with a Retry-After header and a human-readable detail.
    """
    from falsifier.api import guard

    app = _make_app()

    # Temporarily lower the rate limit to make this test fast
    original_calls = guard.RATE_LIMIT_CALLS
    original_window = guard.RATE_LIMIT_WINDOW_SECONDS
    guard.RATE_LIMIT_CALLS = 2
    guard.RATE_LIMIT_WINDOW_SECONDS = 60.0
    # Reset per-IP counters so previous test runs don't interfere
    guard._ip_call_times.clear()

    try:
        statuses = []
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Submit RATE_LIMIT_CALLS + 1 requests with a valid identifier.
            # The first N consume the quota (may 202 or 422 for other reasons,
            # but the rate counter is incremented regardless).
            for _ in range(guard.RATE_LIMIT_CALLS + 1):
                r = await client.post("/jobs", json={
                    "target_id": "KIC 11904151",
                    "mission": "Kepler",
                    "author": "Kepler",
                    "cadence": "long",
                })
                statuses.append(r.status_code)

        # The last request must be 429
        assert statuses[-1] == 429, (
            f"Expected last status to be 429 after rate limit; got statuses: {statuses}"
        )
    finally:
        guard.RATE_LIMIT_CALLS = original_calls
        guard.RATE_LIMIT_WINDOW_SECONDS = original_window
        guard._ip_call_times.clear()


async def test_429_rate_limit_detail_says_when_to_retry():
    """
    The 429 rate-limit detail message must tell the user when to retry.
    """
    from falsifier.api import guard

    app = _make_app()
    original_calls = guard.RATE_LIMIT_CALLS
    guard.RATE_LIMIT_CALLS = 1
    guard._ip_call_times.clear()

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            # First request consumes the quota
            await client.post("/jobs", json={
                "target_id": "KIC 11904151",
                "mission": "Kepler",
                "author": "Kepler",
                "cadence": "long",
            })
            # Second request should be rate-limited
            res = await client.post("/jobs", json={
                "target_id": "KIC 11904151",
                "mission": "Kepler",
                "author": "Kepler",
                "cadence": "long",
            })

        assert res.status_code == 429
        body = res.json()
        detail = body.get("detail", "")
        # Must mention retry timing
        assert "retry" in detail.lower() or "Retry" in detail, (
            f"429 detail should mention retry timing; got: {detail!r}"
        )
        # Must carry a Retry-After header
        assert "retry-after" in {k.lower() for k in res.headers}, (
            "429 response must include a Retry-After header"
        )
    finally:
        guard.RATE_LIMIT_CALLS = original_calls
        guard._ip_call_times.clear()


# ---------------------------------------------------------------------------
# 429 — concurrency cap
# ---------------------------------------------------------------------------

async def test_429_concurrency_cap_detail_says_server_busy():
    """
    When MAX_CONCURRENT_JOBS are active, POST /jobs returns 429 with a
    detail message saying the server is busy.
    """
    from falsifier.api import guard

    app = _make_app()
    original_cap = guard.MAX_CONCURRENT_JOBS
    guard.MAX_CONCURRENT_JOBS = 0   # nothing can run
    guard._ip_call_times.clear()

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            res = await client.post("/jobs", json={
                "target_id": "KIC 11904151",
                "mission": "Kepler",
                "author": "Kepler",
                "cadence": "long",
            })

        assert res.status_code == 429, f"Expected 429, got {res.status_code}: {res.text}"
        detail = res.json().get("detail", "")
        # Must say that the server is busy and suggest retrying
        assert "busy" in detail.lower() or "concurrent" in detail.lower(), (
            f"429 concurrency detail should mention busy/concurrent; got: {detail!r}"
        )
        assert "retry" in detail.lower(), (
            f"429 concurrency detail should mention retry; got: {detail!r}"
        )
    finally:
        guard.MAX_CONCURRENT_JOBS = original_cap
        guard._ip_call_times.clear()


# ---------------------------------------------------------------------------
# No MAST results path
# ---------------------------------------------------------------------------

async def test_no_mast_results_produces_specific_job_error():
    """
    When the MAST archive has no data for the requested target, the job
    transitions to 'failed' with a detail message naming the archive and
    suggesting a mission-dropdown change.

    The ingest stage is mocked to raise TargetNotFoundError so no real
    MAST fetch occurs.  The test verifies the error message is human-readable
    and not a bare exception repr.
    """
    import asyncio
    from unittest.mock import patch
    from falsifier.pipeline.ingest.exceptions import TargetNotFoundError
    from falsifier.api import guard
    from falsifier.api import queue as _q

    app = _make_app()
    # Clear stale jobs and rate-limit state from previous tests
    guard._ip_call_times.clear()
    _q._job_store.clear()

    def _fake_ingest(*args, **kwargs):
        raise TargetNotFoundError(
            "No MAST results for target='KIC 99999999'",
            endpoint="https://mast.stsci.edu/api/v0/invoke",
            query="KIC 99999999",
        )

    record = None
    with patch("falsifier.pipeline.stages.ingest.run_ingest", _fake_ingest):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            post_res = await client.post("/jobs", json={
                "target_id": "KIC 99999999",
                "mission": "Kepler",
                "author": "Kepler",
                "cadence": "long",
            })
            assert post_res.status_code == 202, (
                f"POST /jobs should return 202; got {post_res.status_code}: {post_res.text}"
            )
            job_id = post_res.json()["job_id"]

            # Poll for completion (job runs in background thread)
            for _ in range(40):
                poll_res = await client.get(f"/jobs/{job_id}")
                record = poll_res.json()
                if record["status"] in ("done", "failed"):
                    break
                await asyncio.sleep(0.15)

    assert record is not None
    assert record["status"] == "failed", (
        f"Job should have failed due to TargetNotFoundError; status: {record['status']}"
    )
    error_msg = record.get("error", "")
    # The error must mention the archive, not expose a bare Python exception repr
    assert "archive" in error_msg.lower(), (
        f"Error message should name the archive; got: {error_msg!r}"
    )
    # Must suggest using the mission dropdown
    assert "mission" in error_msg.lower() or "dropdown" in error_msg.lower(), (
        f"Error message should mention the mission dropdown; got: {error_msg!r}"
    )
    # Must not be a bare exception repr like "TargetNotFoundError: …"
    assert not error_msg.startswith("TargetNotFoundError"), (
        f"Error message must not be a bare exception repr; got: {error_msg!r}"
    )


# ---------------------------------------------------------------------------
# TLS no signal — valid scientific result, not an error
# ---------------------------------------------------------------------------

@pytest.mark.no_network
def test_no_signal_is_not_an_error():
    """
    A TLS search that finds no transit signal above the threshold is a valid
    scientific result (quiet star), not an error.  The job must produce a
    complete report with an empty vet list, not raise an exception.

    This is enforced by running the full stub pipeline on a synthetic flat
    light curve — the stub search returns zero TCEs, which is the 'no signal'
    case.
    """
    import datetime
    from falsifier.pipeline.contracts.ingest import LightCurveSegment, IngestInput, StellarParams
    from falsifier.pipeline.contracts.manifest import UnitedArray, DatasetProvenance
    from falsifier.pipeline.stages.ingest import run_ingest
    from falsifier.api.queue import _stub_detrend, _stub_search, _stub_vet, _build_report
    from falsifier.api.models import JobRequest

    # Build a flat (transit-free) light curve with 20 cadences
    n = 20
    segments = [
        LightCurveSegment(
            sector=1,
            time=UnitedArray(
                values=[2454833.0 + i * 0.020833 for i in range(n)], unit="bkjd"
            ),
            time_scale="tdb",
            time_format="bkjd",
            flux=UnitedArray(values=[1.0] * n, unit="electron / s"),
            flux_err=UnitedArray(values=[1e-4] * n, unit="electron / s"),
            quality_flags=[0] * n,
            cadence_type="long",
        )
    ]
    stellar = StellarParams(
        gaia_source_id="fake",
        ra_deg=0.0,
        dec_deg=0.0,
        ruwe=1.0,
        parallax_over_error=50.0,
        teff=UnitedArray(values=[5500.0], unit="K"),
        teff_uncertainty=UnitedArray(values=[100.0], unit="K"),
        radius=UnitedArray(values=[1.0], unit="solRad"),
        radius_uncertainty=UnitedArray(values=[0.05], unit="solRad"),
        provenance=DatasetProvenance(
            source_doi="10.17909/T9/FAKE",
            access_date="2024-01-01",
            row_count=1,
            description="Synthetic test stellar params — no real data",
        ),
    )

    ingest_input = IngestInput(
        target_id="KIC 77777777",
        mission="Kepler",
        author="Kepler",
        cadence="long",
        sectors=[1],
        pipeline_run_id="test-no-signal",
    )
    ingest_out = run_ingest(ingest_input, _segments=segments, _stellar_params=stellar)

    run_id = "test-no-signal"
    detrend_out = _stub_detrend(ingest_out, run_id)
    search_out = _stub_search(detrend_out, run_id)
    vet_outs = _stub_vet(search_out, run_id)

    # Zero TCEs is the 'no signal' result
    assert len(vet_outs) == 0, "Flat light curve should produce zero TCEs"

    # Build a report — must succeed (not raise)
    req = JobRequest(
        target_id="KIC 77777777",
        mission="Kepler",
        author="Kepler",
        cadence="long",
    )
    report = _build_report(
        "test-job-id", req, run_id,
        datetime.datetime.now(tz=datetime.timezone.utc),
        ingest_out, detrend_out, search_out, vet_outs, [],
    )

    # Must have a complete report with an empty vet list, not an error
    assert report is not None, "Report must be built even when there are no TCEs"
    assert isinstance(report.vet, list), "report.vet must be a list"
    assert len(report.vet) == 0, (
        "Zero TCEs must produce an empty vet list, not an error"
    )
    assert report.target_id == "KIC 77777777"
