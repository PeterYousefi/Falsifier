"""
falsifier.api.guard
====================
Public-endpoint protection for POST /jobs.

Three independent mechanisms:

1. Identifier validation
   Reject malformed catalogue identifiers before any network call.
   Accepted patterns:
     KIC <integer>         Kepler Input Catalogue
     TIC <integer>         TESS Input Catalogue
     KIC<integer>          no-space variant
     TIC<integer>          no-space variant
     Kepler-<integer>      alias (resolved by normalise_target_id)
     EPIC <integer>        K2 EPIC catalogue
     EPIC<integer>

2. Concurrent-job cap
   At most MAX_CONCURRENT_JOBS running at once.  Beyond that, the caller
   receives 429 with a queue-depth hint.  With max-scale=1 this is the only
   instance, so this is a global cap.

3. Per-IP rate limit
   At most RATE_LIMIT_CALLS calls per RATE_LIMIT_WINDOW_SECONDS.
   Implemented with a sliding-window counter in a dict keyed by IP.
   Thread-safe for the single-instance deployment.
"""

from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from fastapi import HTTPException, Request

# ---------------------------------------------------------------------------
# Configuration (tuneable via module-level assignment or env override)
# ---------------------------------------------------------------------------

MAX_CONCURRENT_JOBS: int = 3
"""Maximum number of pipeline jobs in status 'queued' or 'running' at once."""

RATE_LIMIT_CALLS: int = 10
"""Maximum POST /jobs calls per IP per window."""

RATE_LIMIT_WINDOW_SECONDS: float = 60.0
"""Sliding window for per-IP rate limiting."""

# ---------------------------------------------------------------------------
# Identifier validation
# ---------------------------------------------------------------------------

# Accepted patterns for catalogue identifiers.
# The integer portion must be 1–10 digits (rejects bare numbers and
# clearly malformed inputs such as shell injections).
_VALID_ID_RE = re.compile(
    r"""
    ^
    (
        (KIC|TIC|EPIC)   \s* \d{1,10}   # KIC 11904151 / TIC 150428135 / EPIC 246851721
      | Kepler  [-\s] \d{1,5}            # Kepler-10 / Kepler 10
      | K2      [-\s] \d{1,5}            # K2-18
      | TOI     [-\s] \d{1,6}            # TOI-700 / TOI 700
    )
    $
    """,
    re.VERBOSE | re.IGNORECASE,
)

_MAX_ID_LEN = 64


def validate_target_id(target_id: str) -> None:
    """
    Raise HTTP 422 if *target_id* does not match a known catalogue pattern.

    Called before any network request so malformed input is rejected cheaply.

    Parameters
    ----------
    target_id : str
        Raw identifier string from the POST /jobs request body.

    Raises
    ------
    HTTPException
        Status 422 if the string is empty, exceeds 64 characters, or does
        not match any of the accepted catalogue patterns (KIC, TIC, EPIC,
        Kepler, K2, TOI).
    """
    stripped = target_id.strip()
    if not stripped:
        raise HTTPException(status_code=422, detail="target_id must not be empty.")
    if len(stripped) > _MAX_ID_LEN:
        raise HTTPException(
            status_code=422,
            detail=f"target_id exceeds maximum length of {_MAX_ID_LEN} characters.",
        )
    if not _VALID_ID_RE.match(stripped):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unrecognised catalogue identifier: {stripped!r}. "
                "Accepted formats: KIC <N>, TIC <N>, EPIC <N>, "
                "Kepler-<N>, K2-<N>, TOI-<N>."
            ),
        )


# ---------------------------------------------------------------------------
# Per-IP rate limiter (sliding window)
# ---------------------------------------------------------------------------

# ip → deque of call timestamps (monotonic)
_ip_call_times: dict[str, deque] = defaultdict(deque)


def check_rate_limit(ip: str) -> None:
    """
    Raise HTTP 429 if *ip* has exceeded ``RATE_LIMIT_CALLS`` within the window.

    Implements a sliding-window counter: call timestamps older than
    ``RATE_LIMIT_WINDOW_SECONDS`` are expired on each invocation.

    Parameters
    ----------
    ip : str
        Client IP address (from ``get_client_ip``).

    Raises
    ------
    HTTPException
        Status 429 with a ``Retry-After`` header if the rate limit is exceeded.
    """
    now = time.monotonic()
    window_start = now - RATE_LIMIT_WINDOW_SECONDS
    dq = _ip_call_times[ip]

    # Expire old entries
    while dq and dq[0] < window_start:
        dq.popleft()

    if len(dq) >= RATE_LIMIT_CALLS:
        retry_after = int(RATE_LIMIT_WINDOW_SECONDS - (now - dq[0])) + 1
        raise HTTPException(
            status_code=429,
            detail=(
                f"Rate limit exceeded: at most {RATE_LIMIT_CALLS} requests "
                f"per {int(RATE_LIMIT_WINDOW_SECONDS)} seconds per IP. "
                f"Retry after {retry_after} seconds."
            ),
            headers={"Retry-After": str(retry_after)},
        )

    dq.append(now)


def get_client_ip(request: Request) -> str:
    """
    Extract the best-available client IP from a FastAPI request.

    Prefers ``X-Forwarded-For`` (set by Code Engine / Knative ingress) over
    the raw TCP client address.

    Parameters
    ----------
    request : Request
        Incoming FastAPI request object.

    Returns
    -------
    str
        The leftmost address from ``X-Forwarded-For`` (the original client),
        the raw ``request.client.host``, or ``"unknown"`` if neither is
        available.
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # X-Forwarded-For may be "client, proxy1, proxy2"; take the first.
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


# ---------------------------------------------------------------------------
# Concurrent-job cap
# ---------------------------------------------------------------------------

def check_concurrency(job_store: dict) -> None:
    """
    Raise HTTP 429 with queue position if too many jobs are active.

    Parameters
    ----------
    job_store : dict
        The in-memory ``_job_store`` dict from ``queue.py``; maps job IDs to
        ``JobRecord`` objects.

    Raises
    ------
    HTTPException
        Status 429 if the count of ``"queued"`` or ``"running"`` jobs meets or
        exceeds ``MAX_CONCURRENT_JOBS``.
    """
    active = sum(
        1 for r in job_store.values()
        if r.status in ("queued", "running")
    )
    if active >= MAX_CONCURRENT_JOBS:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Pipeline busy: {active} job(s) are currently queued or running. "
                f"Maximum concurrent jobs is {MAX_CONCURRENT_JOBS}. "
                "Please retry in a few minutes."
            ),
        )
