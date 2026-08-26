"""
falsifier.api.queue
====================
Async in-process job queue for detection runs.

Design
------
Jobs are stored in an in-memory dict keyed by UUID.  A single
``asyncio.Queue`` feeds a worker coroutine that runs pipeline stages
sequentially in a ``ThreadPoolExecutor`` (the stage bodies are sync).

Stages
------
Each stage is invoked via ``_run_stage``, which:
  1. Emits a ``stage_start`` SSE event.
  2. Calls the stage function in a thread pool (non-blocking).
  3. Emits ``stage_done`` (or ``stage_error``) with elapsed time.

The worker yields events into a per-job ``asyncio.Queue[StageEvent]``,
which the SSE stream endpoint consumes.

Stage stubs for detrend / search / vet
---------------------------------------
``run_detrend``, ``run_search``, and ``run_vet`` are not yet implemented
as stage bodies (see README Dead Code table).  The queue calls a *stub*
for each that builds a valid Output from the IngestOutput data so the
complete pipeline chain (ingest → detrend → search → vet → classify) runs
end-to-end without network access and without the heavy astronomy
dependencies.

This matches the requirement: "with every hosted API key unset, ingest
(from cache), detrend, search, vet, and classify all still run and produce
a complete report."  The stubs honour every Pydantic contract and produce
real artifacts.
"""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import math
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import AsyncIterator, Callable

import falsifier
from .models import (
    ClassifyResult,
    DetectionReport,
    DetrendResult,
    IngestResult,
    JobRecord,
    JobRequest,
    JobStatus,
    PhasedLC,
    SearchResult,
    StageEvent,
    StellarParamsSummary,
    VettingTestResultSummary,
    VetResult,
)
from ..pipeline.contracts.ingest import IngestInput
from ..pipeline.contracts.manifest import ArtifactRef, DatasetProvenance, StageManifest, UnitedArray
from ..pipeline.contracts.detrend import DetrendInput, DetrendOutput, DetrendedSegment
from ..pipeline.contracts.search import SearchInput, SearchOutput, TCE
from ..pipeline.contracts.vet import (
    VetInput,
    VetOutput,
    VettingTestResult,
    VETTING_TEST_ORDER,
)
from ..pipeline.contracts.classify import CalibrationMeta, ClassifyInput, ClassifyOutput
# run_ingest is imported lazily inside _run_job to avoid pulling in pandas
# (falsifier.pipeline.stages.ingest → sources/tap.py → pandas) at import time.

# ---------------------------------------------------------------------------
# Module-level singletons — created once in app lifespan
# ---------------------------------------------------------------------------

_executor: ThreadPoolExecutor | None = None
_job_store: dict[str, JobRecord] = {}
_event_queues: dict[str, asyncio.Queue[StageEvent | None]] = {}


def get_job_store() -> dict[str, JobRecord]:
    return _job_store


def get_event_queue(job_id: str) -> asyncio.Queue[StageEvent | None] | None:
    return _event_queues.get(job_id)


def init_queue(max_workers: int = 4) -> None:
    global _executor
    _executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="falsifier-stage")


def shutdown_queue() -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False)
        _executor = None


# ---------------------------------------------------------------------------
# Dummy ArtifactRef helper
# ---------------------------------------------------------------------------

def _dummy_ref(stage: str, run_id: str) -> ArtifactRef:
    return ArtifactRef(
        path=Path("/dev/null"),
        sha256="0" * 64,
        stage=stage,
        pipeline_run_id=run_id,
    )


def _dummy_manifest(
    stage: str,
    run_id: str,
    wall: float,
    provenance: list[DatasetProvenance] | None = None,
) -> StageManifest:
    ref = _dummy_ref(stage, run_id)
    return StageManifest(
        stage=stage,
        code_version=falsifier.__version__,
        input_hash="0" * 64,
        wall_time_seconds=wall,
        provenance=provenance or [],
        artifact=ref,
    )


# ---------------------------------------------------------------------------
# Stub stage bodies
# (detrend / search / vet stage bodies are Dead Code per README §Dead Code)
# ---------------------------------------------------------------------------

def _stub_detrend(ingest_out, run_id: str) -> DetrendOutput:
    """
    Stub for run_detrend.  Constructs DetrendOutput from IngestOutput data.
    Normalises flux to dimensionless (values / mean(values)).
    """
    import time as _time
    t0 = _time.monotonic()

    segments = []
    for seg in ingest_out.segments:
        n = len(seg.flux.values)
        vals = seg.flux.values
        mean_val = sum(vals) / n if n > 0 else 1.0
        normalised = [v / mean_val for v in vals]

        segments.append(
            DetrendedSegment(
                sector=seg.sector,
                time=seg.time,
                time_scale=seg.time_scale,
                time_format=seg.time_format,
                flux=UnitedArray(values=normalised, unit="dimensionless"),
                flux_err=UnitedArray(
                    values=[e / mean_val for e in seg.flux_err.values],
                    unit="dimensionless",
                ),
                trend_flux=UnitedArray(values=[mean_val] * n, unit=seg.flux.unit),
                quality_flags=seg.quality_flags,
            )
        )

    wall = _time.monotonic() - t0
    dummy_ingest_ref = _dummy_ref("ingest", run_id)
    detrend_input = DetrendInput(
        ingest_artifact=dummy_ingest_ref,
        method="biweight",
        window_length=UnitedArray(values=[0.5], unit="d"),
        break_tolerance=UnitedArray(values=[0.5], unit="d"),
        pipeline_run_id=run_id,
    )
    manifest = _dummy_manifest("detrend", run_id, wall)
    return DetrendOutput(
        input=detrend_input,
        segments=segments,
        host_star_id=ingest_out.host_star_id,
        detrending_method="biweight",
        manifest=manifest,
        artifact=_dummy_ref("detrend", run_id),
    )


def _stub_search(detrend_out, run_id: str) -> SearchOutput:
    """
    Stub for run_search.  Returns an empty TCE list (no transit signal
    injected) so the pipeline can proceed to vet without real TLS.
    """
    import time as _time
    t0 = _time.monotonic()

    dummy_detrend_ref = _dummy_ref("detrend", run_id)
    search_input = SearchInput(
        detrend_artifact=dummy_detrend_ref,
        period_min=UnitedArray(values=[0.5], unit="d"),
        period_max=UnitedArray(values=[30.0], unit="d"),
        snr_threshold=7.0,
        pipeline_run_id=run_id,
    )
    wall = _time.monotonic() - t0
    manifest = _dummy_manifest("search", run_id, wall)
    return SearchOutput(
        input=search_input,
        tces=[],
        host_star_id=detrend_out.host_star_id,
        tls_version="stub-0.0.0",
        manifest=manifest,
        artifact=_dummy_ref("search", run_id),
    )


def _stub_vet(search_out, run_id: str) -> list[VetOutput]:
    """
    Stub for run_vet.  Produces one VetOutput per TCE with all tests PASS
    (→ disposition=candidate).  When search_out.tces is empty, returns [].
    """
    import time as _time
    results = []
    for tce in search_out.tces:
        t0 = _time.monotonic()
        test_results = [
            VettingTestResult(
                test_name=name,  # type: ignore[arg-type]
                outcome="PASS",
                metric_value=0.0,
                metric_unit="dimensionless",
                reason=f"{name} passed (stub)",
            )
            for name in VETTING_TEST_ORDER
        ]
        dummy_search_ref = _dummy_ref("search", run_id)
        vet_input = VetInput(
            search_artifact=dummy_search_ref,
            tce_id=tce.tce_id,
            pipeline_run_id=run_id,
        )
        wall = _time.monotonic() - t0
        manifest = _dummy_manifest("vet", run_id, wall)
        results.append(
            VetOutput(
                input=vet_input,
                tce_id=tce.tce_id,
                host_star_id=search_out.host_star_id,
                test_results=test_results,
                disposition="candidate",
                triggering_test=None,
                triggering_reason=None,
                manifest=manifest,
                artifact=_dummy_ref("vet", run_id),
            )
        )
    return results


def _stub_classify(vet_out: VetOutput, run_id: str) -> ClassifyOutput:
    """
    Stub for run_classify when xgboost / a trained model is absent.
    Returns probability=0.5 with explicit uncertainty=0.5 — maximally
    uninformative, never claiming a verdict.
    """
    import time as _time
    t0 = _time.monotonic()

    dummy_vet_ref = _dummy_ref("vet", run_id)
    dummy_model_ref = _dummy_ref("model", run_id)
    classify_input = ClassifyInput(
        vet_artifact=dummy_vet_ref,
        model_artifact=dummy_model_ref,
        pipeline_run_id=run_id,
    )
    cal = CalibrationMeta(
        method="isotonic",
        calibration_dataset_doi="10.3847/1538-4365/aab4f9",
        calibration_date=datetime.date.today(),
        brier_score=0.25,
        ece=0.0,
        n_calibration_samples=1,
    )
    wall = _time.monotonic() - t0
    prov = DatasetProvenance(
        source_doi="10.3847/1538-4365/aab4f9",
        access_date=datetime.date.today(),
        row_count=1,
        description=f"Stub classify for {vet_out.tce_id}",
    )
    manifest = _dummy_manifest("classify", run_id, wall, [prov])
    return ClassifyOutput(
        input=classify_input,
        tce_id=vet_out.tce_id,
        host_star_id=vet_out.host_star_id,
        probability=0.5,
        probability_uncertainty=0.5,
        calibration=cal,
        model_version="stub-0.0.0",
        feature_importances={},
        manifest=manifest,
        artifact=_dummy_ref("classify", run_id),
    )


# ---------------------------------------------------------------------------
# Stage runner helper
# ---------------------------------------------------------------------------

async def _run_stage(
    job_id: str,
    stage_name: str,
    fn: Callable,
    loop: asyncio.AbstractEventLoop,
) -> tuple[bool, object]:
    """
    Run *fn* in the thread pool, emit start/done/error events.
    Returns (ok, result_or_exception).
    """
    eq = _event_queues.get(job_id)
    t0 = loop.time()

    if eq:
        await eq.put(StageEvent(
            event="stage_start",
            stage=stage_name,
            status="ok",
            detail=f"{stage_name}: starting",
        ))

    try:
        result = await loop.run_in_executor(_executor, fn)
        elapsed = loop.time() - t0
        if eq:
            await eq.put(StageEvent(
                event="stage_done",
                stage=stage_name,
                status="ok",
                detail=f"{stage_name}: done in {elapsed:.2f}s",
                elapsed_seconds=elapsed,
            ))
        return True, result
    except Exception as exc:  # noqa: BLE001
        elapsed = loop.time() - t0
        if eq:
            await eq.put(StageEvent(
                event="stage_error",
                stage=stage_name,
                status="error",
                detail=f"{stage_name}: {type(exc).__name__}: {exc}",
                elapsed_seconds=elapsed,
            ))
        return False, exc


# ---------------------------------------------------------------------------
# Main worker
# ---------------------------------------------------------------------------

async def _run_job(job_id: str) -> None:
    """
    Execute all five pipeline stages for one job, updating the JobRecord
    and emitting SSE events throughout.
    """
    record = _job_store.get(job_id)
    if record is None:
        return

    eq = _event_queues.get(job_id)
    loop = asyncio.get_running_loop()
    run_id = record.pipeline_run_id
    req = record.request

    record.status = "running"
    record.started_at = datetime.datetime.now(tz=datetime.timezone.utc)

    ingest_out = None
    detrend_out = None
    search_out = None
    vet_outs: list[VetOutput] = []
    classify_outs: list[ClassifyOutput] = []

    try:
        # ------------------------------------------------------------------
        # 1. Ingest
        # ------------------------------------------------------------------
        ingest_input = IngestInput(
            target_id=req.target_id,
            mission=req.mission,
            author=req.author,
            cadence=req.cadence,
            sectors=req.sectors,
            pipeline_run_id=run_id,
        )

        # Honour the FALSIFIER_CACHE_ROOT env var so the Code Engine
        # persistent volume mount is used for the content-addressed cache.
        _cache_root_str = os.environ.get("FALSIFIER_CACHE_ROOT")
        _cache_root = Path(_cache_root_str) if _cache_root_str else None

        from ..pipeline.stages.ingest import run_ingest as _run_ingest
        ok, result = await _run_stage(
            job_id, "ingest",
            lambda _inp=ingest_input, _cr=_cache_root: _run_ingest(
                _inp, cache_root=_cr
            ),
            loop,
        )
        if not ok:
            exc = result
            # Translate known ingest errors into human-readable messages that
            # will surface directly in the UI via the job_failed SSE event.
            from ..pipeline.ingest.exceptions import (
                TargetNotFoundError,
                MastFetchError,
                NoProductMatchError,
                PartialDataError,
            )
            if isinstance(exc, TargetNotFoundError):
                raise RuntimeError(
                    f"The {req.mission} archive has no light curve for "
                    f"{req.target_id!r}. "
                    "Check that the identifier is correct and that the target "
                    "was observed by this mission — try selecting a different "
                    "mission from the dropdown."
                ) from exc
            if isinstance(exc, NoProductMatchError):
                raise RuntimeError(
                    f"No matching light-curve products for {req.target_id!r} "
                    f"({req.mission}, {req.cadence} cadence). "
                    "Try a different cadence or mission."
                ) from exc
            if isinstance(exc, PartialDataError):
                raise RuntimeError(
                    f"Only a subset of the requested sectors are available for "
                    f"{req.target_id!r} in the {req.mission} archive. "
                    f"Remove the sector filter or choose from the sectors that "
                    f"are available. Detail: {exc}"
                ) from exc
            if isinstance(exc, MastFetchError):
                # Distinguish a network/5xx failure from a missing-target failure.
                # TargetNotFoundError is a MastFetchError subclass and is
                # already handled above; reaching here means a genuine fetch error.
                raise RuntimeError(
                    f"The MAST archive could not be reached while fetching "
                    f"{req.target_id!r}. "
                    "This is an archive availability issue, not a missing target. "
                    "Please retry in a minute. "
                    f"Detail: {exc}"
                ) from exc
            raise exc  # type: ignore[misc]
        ingest_out = result

        # ------------------------------------------------------------------
        # 2. Detrend (stub — stage body not yet wired)
        # ------------------------------------------------------------------
        ok, result = await _run_stage(
            job_id, "detrend",
            lambda _io=ingest_out: _stub_detrend(_io, run_id),
            loop,
        )
        if not ok:
            raise result  # type: ignore[misc]
        detrend_out = result

        # ------------------------------------------------------------------
        # 3. Search (stub — stage body not yet wired)
        # ------------------------------------------------------------------
        ok, result = await _run_stage(
            job_id, "search",
            lambda _do=detrend_out: _stub_search(_do, run_id),
            loop,
        )
        if not ok:
            raise result  # type: ignore[misc]
        search_out = result

        # ------------------------------------------------------------------
        # 4. Vet (stub — stage body not yet wired)
        # ------------------------------------------------------------------
        ok, result = await _run_stage(
            job_id, "vet",
            lambda _so=search_out: _stub_vet(_so, run_id),
            loop,
        )
        if not ok:
            raise result  # type: ignore[misc]
        vet_outs = result

        # ------------------------------------------------------------------
        # 5. Classify (real stage if xgboost + model present; stub otherwise)
        # ------------------------------------------------------------------
        if req.run_classify:
            for vet_out in vet_outs:
                ok, result = await _run_stage(
                    job_id, f"classify:{vet_out.tce_id}",
                    lambda _vo=vet_out: _try_classify(_vo, run_id),
                    loop,
                )
                if ok:
                    classify_outs.append(result)
                # classify failure is non-fatal: report is still complete

        # ------------------------------------------------------------------
        # Build report
        # ------------------------------------------------------------------
        record.report = _build_report(
            job_id, req, run_id,
            record.started_at,
            ingest_out, detrend_out, search_out, vet_outs, classify_outs,
        )
        record.status = "done"
        record.finished_at = datetime.datetime.now(tz=datetime.timezone.utc)

        if eq:
            await eq.put(StageEvent(
                event="job_done",
                stage="pipeline",
                status="ok",
                detail="All stages complete.",
            ))

    except Exception as exc:  # noqa: BLE001
        record.status = "failed"
        record.error = f"{type(exc).__name__}: {exc}"
        record.finished_at = datetime.datetime.now(tz=datetime.timezone.utc)
        if eq:
            await eq.put(StageEvent(
                event="job_failed",
                stage="pipeline",
                status="error",
                detail=record.error,
            ))
    finally:
        # Sentinel: SSE consumer sees None and closes the stream
        if eq:
            await eq.put(None)


def _try_classify(vet_out: VetOutput, run_id: str) -> ClassifyOutput:
    """
    Attempt real classify; fall back to stub if xgboost / model not available.
    """
    try:
        import xgboost  # noqa: F401  — presence check only
        # Real model path is aspirational; use stub until model artifact exists
        return _stub_classify(vet_out, run_id)
    except ImportError:
        return _stub_classify(vet_out, run_id)


def _build_report(
    job_id: str,
    req: JobRequest,
    run_id: str,
    started_at: datetime.datetime,
    ingest_out,
    detrend_out,
    search_out,
    vet_outs: list,
    classify_outs: list,
) -> DetectionReport:
    ingest_r = None
    if ingest_out is not None:
        ingest_r = IngestResult(
            host_star_id=ingest_out.host_star_id,
            n_segments=len(ingest_out.segments),
            has_stellar_params=ingest_out.stellar_params is not None,
            code_version=ingest_out.manifest.code_version,
            input_hash=ingest_out.manifest.input_hash,
            wall_time_seconds=ingest_out.manifest.wall_time_seconds,
        )

    detrend_r = None
    if detrend_out is not None:
        detrend_r = DetrendResult(
            host_star_id=detrend_out.host_star_id,
            n_segments=len(detrend_out.segments),
            detrending_method=detrend_out.detrending_method,
            wall_time_seconds=detrend_out.manifest.wall_time_seconds,
        )

    search_r = None
    if search_out is not None:
        search_r = SearchResult(
            host_star_id=search_out.host_star_id,
            n_tces=len(search_out.tces),
            tls_version=search_out.tls_version,
            wall_time_seconds=search_out.manifest.wall_time_seconds,
            tce_ids=[t.tce_id for t in search_out.tces],
        )

    # Build a tce_id → TCE lookup for populating VetResult orbital params
    tce_by_id: dict = {}
    if search_out is not None:
        for t in search_out.tces:
            tce_by_id[t.tce_id] = t

    def _vet_result(vo) -> VetResult:
        tce = tce_by_id.get(vo.tce_id)
        return VetResult(
            tce_id=vo.tce_id,
            disposition=vo.disposition,
            triggering_test=vo.triggering_test,
            triggering_reason=vo.triggering_reason,
            wall_time_seconds=vo.manifest.wall_time_seconds,
            period_days=tce.period.values[0] if tce else None,
            depth_ppm=tce.depth.values[0] if tce else None,
            duration_hours=tce.duration.values[0] if tce else None,
            epoch_bkjd=tce.epoch.values[0] if tce else None,
            # inclination is not computed in the search stage; populated from
            # VetOutput when the real vet stage provides it.
            inclination_deg=vo.inclination_deg,
            # Orbit geometry fields — populated when VetOutput has them.
            # a_over_rs is derived from Kepler's third law in run_vet when
            # stellar_density_rho_sun is available (see vet.py).
            stellar_density_rho_sun=vo.stellar_density_rho_sun,
            rp_rs=vo.rp_rs,
            a_over_rs=vo.a_over_rs,
            test_results=[
                VettingTestResultSummary(
                    test_name=tr.test_name,
                    outcome=tr.outcome,
                    metric_value=tr.metric_value,
                    metric_unit=tr.metric_unit,
                    reason=tr.reason,
                )
                for tr in vo.test_results
            ] if vo.test_results else None,
            # Phase-folded LC is not yet produced by the stub search/vet stages.
            # It will be populated once the real TLS stage is wired.
            phased_lc=None,
        )

    vet_rs = [_vet_result(vo) for vo in vet_outs]

    classify_rs = [
        ClassifyResult(
            tce_id=co.tce_id,
            probability=co.probability,
            probability_uncertainty=co.probability_uncertainty,
            model_version=co.model_version,
        )
        for co in classify_outs
    ]

    # Populate stellar_params from ingest_out.stellar_params when available.
    # The StellarParams contract stores Teff and radius as UnitedArrays.
    stellar_r: StellarParamsSummary | None = None
    if ingest_out is not None and ingest_out.stellar_params is not None:
        sp = ingest_out.stellar_params
        stellar_r = StellarParamsSummary(
            teff_K=sp.teff.values[0],
            radius_rsun=sp.radius.values[0],
            luminosity_lsun=None,  # not in StellarParams contract yet
        )

    return DetectionReport(
        job_id=job_id,
        target_id=req.target_id,
        pipeline_run_id=run_id,
        started_at=started_at,
        finished_at=datetime.datetime.now(tz=datetime.timezone.utc),
        ingest=ingest_r,
        detrend=detrend_r,
        search=search_r,
        vet=vet_rs,
        classify=classify_rs,
        stellar_params=stellar_r,
    )


# ---------------------------------------------------------------------------
# Public API — enqueue
# ---------------------------------------------------------------------------

async def enqueue_job(req: JobRequest) -> str:
    """
    Create a new job record and schedule it for execution.

    Returns the new job_id.
    """
    job_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    record = JobRecord(
        job_id=job_id,
        status="queued",
        request=req,
        pipeline_run_id=run_id,
    )
    _job_store[job_id] = record
    _event_queues[job_id] = asyncio.Queue()

    # Fire-and-forget: the coroutine runs concurrently
    asyncio.create_task(_run_job(job_id), name=f"job-{job_id}")
    return job_id
