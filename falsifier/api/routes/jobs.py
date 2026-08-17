"""
falsifier.api.routes.jobs
==========================
Detection-run job endpoints.

POST /jobs
    Enqueue a new detection run.  Returns ``{"job_id": "...", "status": "queued"}``.

GET /jobs/{job_id}
    Poll the current status / report for a job.
    Returns the full ``JobRecord`` JSON (excluding the internal event queue).

GET /jobs/{job_id}/stream
    SSE stream of stage events while the job runs.
    Each ``data:`` frame is a JSON-serialised ``StageEvent``.
    The stream closes when the worker emits the sentinel (job done or failed).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..models import JobID, JobRequest, JobRecord
from ..queue import enqueue_job, get_job_store
from ..sse import event_stream

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=JobID, status_code=202)
async def create_job(req: JobRequest) -> JobID:
    """
    Enqueue a new detection run.

    The pipeline stages (ingest → detrend → search → vet → classify) run
    asynchronously.  Poll ``GET /jobs/{job_id}`` or stream
    ``GET /jobs/{job_id}/stream`` for progress.
    """
    job_id = await enqueue_job(req)
    return JobID(job_id=job_id, status="queued")


@router.get("/{job_id}", response_model=JobRecord)
async def get_job(job_id: str) -> JobRecord:
    """
    Return the current state of a job.

    The ``report`` field is populated once status is ``"done"``.
    """
    job_store = get_job_store()
    record = job_store.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")
    return record


@router.get("/{job_id}/stream")
async def stream_job(job_id: str) -> StreamingResponse:
    """
    SSE stream of stage events for a running job.

    Content-Type is ``text/event-stream``.  Each ``data:`` frame carries a
    JSON ``StageEvent``.  The stream closes automatically when the job
    transitions to ``done`` or ``failed``.
    """
    job_store = get_job_store()
    if job_id not in job_store:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")

    return StreamingResponse(
        event_stream(job_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )
