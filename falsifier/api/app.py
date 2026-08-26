"""
falsifier.api.app
==================
FastAPI application factory.

Usage
-----
From the repo root::

    uvicorn falsifier.api.app:create_app --factory --reload

Or import the pre-built instance::

    from falsifier.api.app import app

Lifespan
--------
The ``ThreadPoolExecutor`` for stage runners is initialised on startup and
shut down gracefully on shutdown.  No other global state is mutated.

Non-claim header
----------------
Every response carries an ``X-Non-Claim`` header asserting the locked claim
from AGENTS.md so it is visible in every curl trace and client log:

    X-Non-Claim: Not a biosignature detector. No biosignature confirmed.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from .queue import init_queue, shutdown_queue
from .routes.jobs import router as jobs_router
from .routes.provenance import router as provenance_router
from .routes.chat import router as chat_router
from .routes.verify import router as verify_router

# ---------------------------------------------------------------------------
# CORS origins
# ---------------------------------------------------------------------------
# In development (env var unset), allow all origins so local testing works.
# In production (container on Code Engine), set ALLOWED_ORIGINS to the
# Vercel frontend URL, e.g.:
#   ALLOWED_ORIGINS=https://falsifier.vercel.app
# Multiple origins are comma-separated.
_raw_origins = os.environ.get("ALLOWED_ORIGINS", "*")
_CORS_ORIGINS: list[str] = (
    ["*"] if _raw_origins.strip() == "*"
    else [o.strip() for o in _raw_origins.split(",") if o.strip()]
)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def _lifespan(app: FastAPI):
    init_queue(max_workers=4)
    try:
        yield
    finally:
        shutdown_queue()


# ---------------------------------------------------------------------------
# Middleware — non-claim header on every response
# ---------------------------------------------------------------------------

_NON_CLAIM_VALUE = (
    "Not a biosignature detector. "
    "No exoplanet biosignature has ever been confirmed."
)


async def _non_claim_middleware(request: Request, call_next) -> Response:
    response = await call_next(request)
    response.headers["X-Non-Claim"] = _NON_CLAIM_VALUE
    return response


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    """
    Create and return the configured FastAPI application.

    Call this factory from uvicorn with ``--factory`` or import ``app``
    for the pre-built singleton.
    """
    application = FastAPI(
        title="Falsifier",
        description=(
            "Disequilibrium screening and false-positive triage for exoplanet "
            "candidates.  **This project is not a biosignature detector.  "
            "No exoplanet biosignature has ever been confirmed.**"
        ),
        version="0.1.0-dev",
        lifespan=_lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=_CORS_ORIGINS,
        allow_credentials=len(_CORS_ORIGINS) > 0 and _CORS_ORIGINS != ["*"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    application.middleware("http")(_non_claim_middleware)

    application.include_router(jobs_router)
    application.include_router(provenance_router)
    application.include_router(chat_router)
    application.include_router(verify_router)

    @application.get("/health", tags=["meta"])
    async def health() -> dict:
        """Liveness probe."""
        return {"status": "ok"}

    return application


# Pre-built singleton for import convenience
app = create_app()
