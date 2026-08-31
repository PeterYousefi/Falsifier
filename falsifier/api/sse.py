"""
falsifier.api.sse
==================
Server-Sent Events helpers.

Formats ``StageEvent`` instances as SSE text frames per the W3C spec:

    data: <json>\n\n

The SSE stream for a job closes when the worker pushes ``None`` (sentinel)
into the per-job event queue.

Usage in a route
----------------
::

    @router.get("/{job_id}/stream")
    async def stream(job_id: str):
        return EventSourceResponse(event_stream(job_id))
"""

from __future__ import annotations

import json
from typing import AsyncIterator

from .models import StageEvent
from .queue import get_event_queue


async def event_stream(job_id: str) -> AsyncIterator[str]:
    """
    Yield SSE-formatted text frames for *job_id* until the worker signals done.

    Each frame has the form ``data: <json>\\n\\n`` per the W3C SSE spec.
    If the job is unknown or has no active queue (e.g. it already finished),
    yields a single synthetic ``job_done`` (or ``job_failed``) event and closes.

    Parameters
    ----------
    job_id : str
        The pipeline job identifier to stream events for.

    Yields
    ------
    str
        SSE text frames ready to be sent as ``text/event-stream`` content.
    """
    from .queue import get_job_store
    job_store = get_job_store()

    eq = get_event_queue(job_id)

    # Job finished before the client connected: emit one synthetic event
    if eq is None:
        record = job_store.get(job_id)
        if record is None:
            payload = json.dumps({"event": "error", "detail": "job not found"})
        else:
            payload = json.dumps({
                "event": "job_done" if record.status == "done" else "job_failed",
                "stage": "pipeline",
                "status": "ok" if record.status == "done" else "error",
                "detail": f"job already {record.status}",
            })
        yield f"data: {payload}\n\n"
        return

    while True:
        item: StageEvent | None = await eq.get()
        if item is None:
            # Sentinel — worker is done; remove the queue
            _event_queues_cleanup(job_id)
            break
        yield f"data: {item.model_dump_json()}\n\n"


def _event_queues_cleanup(job_id: str) -> None:
    """
    Remove the per-job event queue so it can be garbage collected.

    Called after the sentinel ``None`` is dequeued, signalling that the
    worker has finished and no more events will arrive.

    Parameters
    ----------
    job_id : str
        Identifier of the job whose queue should be removed.
    """
    from .queue import _event_queues
    _event_queues.pop(job_id, None)
