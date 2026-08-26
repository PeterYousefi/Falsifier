"""
falsifier.api.models
=====================
Pydantic models for the API layer only.

These models live here, not in falsifier.pipeline.contracts, because they are
HTTP-transport concerns (job lifecycle, SSE events, provenance report).  They
hold no scientific values and make no computation claims.

JobStatus lifecycle
-------------------
    queued → running → done
                     → failed

The final report (`DetectionReport`) is assembled from the four pipeline
*Output artifacts once all stages complete.  It never stores hardcoded
numbers; every field is read from an artifact produced by a stage run.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared sub-models
# ---------------------------------------------------------------------------

class PhasedLC(BaseModel):
    """Phase-folded light curve arrays for 3-D / chart display."""

    phase: list[float]
    flux: list[float]


class VettingTestResultSummary(BaseModel):
    """Slimmed test result forwarded to the API layer."""

    test_name: str
    outcome: str
    metric_value: float | None = None
    metric_unit: str | None = None
    reason: str


class StellarParamsSummary(BaseModel):
    """Subset of ingest StellarParams included in the detection report."""

    teff_K: float
    """Effective temperature in Kelvin."""

    radius_rsun: float
    """Stellar radius in solar radii."""

    luminosity_lsun: float | None = None
    """Luminosity in solar luminosities (optional; absent if not in Gaia DR3)."""

# ---------------------------------------------------------------------------
# Job lifecycle
# ---------------------------------------------------------------------------

JobStatus = Literal["queued", "running", "done", "failed"]


class JobRequest(BaseModel):
    """POST /jobs body — what the caller wants to run."""

    target_id: str
    """Canonical target identifier, e.g. ``"KIC 11904151"`` or ``"TIC 261136679"``."""

    mission: Literal["Kepler", "K2", "TESS"] = "Kepler"
    author: str = "Kepler"
    cadence: Literal["short", "long", "fast"] = "long"
    sectors: list[int] | None = None

    # Stage-specific toggles (all default to running the stage)
    run_classify: bool = True
    """
    When False, the classify stage is skipped and ClassifyResult will be
    absent from the final report.
    """


class JobID(BaseModel):
    """Response body for POST /jobs."""

    job_id: str
    status: JobStatus = "queued"


class StageEvent(BaseModel):
    """
    One SSE payload emitted while a job is running.

    ``stage`` names the pipeline stage that just completed or errored.
    ``status`` mirrors the stage outcome.
    ``detail`` is a human-readable one-liner for log display.
    ``artifact_path`` is set only when the stage wrote a committed artifact.
    """

    event: Literal["stage_start", "stage_done", "stage_error", "job_done", "job_failed"]
    stage: str
    status: Literal["ok", "error", "skipped"]
    detail: str
    artifact_path: str | None = None
    elapsed_seconds: float | None = None


class IngestResult(BaseModel):
    """Subset of IngestOutput fields safe for JSON serialisation."""

    host_star_id: str
    n_segments: int
    has_stellar_params: bool
    code_version: str
    input_hash: str
    wall_time_seconds: float


class DetrendResult(BaseModel):
    """Subset of DetrendOutput fields."""

    host_star_id: str
    n_segments: int
    detrending_method: str
    wall_time_seconds: float


class SearchResult(BaseModel):
    """Subset of SearchOutput fields."""

    host_star_id: str
    n_tces: int
    tls_version: str
    wall_time_seconds: float
    tce_ids: list[str]


class VetResult(BaseModel):
    """Per-TCE vet result for the report."""

    tce_id: str
    disposition: str
    triggering_test: str | None
    triggering_reason: str | None
    wall_time_seconds: float

    # TCE orbital parameters — populated from TCE when available
    period_days: float | None = None
    depth_ppm: float | None = None
    duration_hours: float | None = None
    epoch_bkjd: float | None = None
    inclination_deg: float | None = None

    # Full test-result list for the 3-D scene branching
    test_results: list[VettingTestResultSummary] | None = None

    # Phase-folded LC for the synced chart
    phased_lc: PhasedLC | None = None


class ClassifyResult(BaseModel):
    """Per-TCE classify result.  Absent when run_classify=False or xgboost unavailable."""

    tce_id: str
    probability: float
    probability_uncertainty: float
    model_version: str


class DetectionReport(BaseModel):
    """
    The complete, self-contained report produced by one detection run.

    All numeric fields are read from stage artifacts, never hardcoded.
    The report is the definitive scientific output; the classifier probability
    is a *ranking score only* — it carries no disposition.
    """

    job_id: str
    target_id: str
    pipeline_run_id: str
    started_at: datetime.datetime
    finished_at: datetime.datetime

    ingest: IngestResult | None = None
    detrend: DetrendResult | None = None
    search: SearchResult | None = None
    vet: list[VetResult] = Field(default_factory=list)
    classify: list[ClassifyResult] = Field(default_factory=list)

    stellar_params: StellarParamsSummary | None = None
    """Host-star parameters included when ingest found Gaia DR3 stellar data."""

    non_claims: list[str] = Field(
        default_factory=lambda: [
            "This project is not a biosignature detector.",
            "No exoplanet biosignature has ever been confirmed.",
            "The classifier probability is a ranking score only, not a verdict.",
            "Disposition is determined exclusively by the vet stage.",
        ]
    )


class JobRecord(BaseModel):
    """In-memory record for one job in the queue."""

    job_id: str
    status: JobStatus
    request: JobRequest
    pipeline_run_id: str
    started_at: datetime.datetime | None = None
    finished_at: datetime.datetime | None = None
    report: DetectionReport | None = None
    error: str | None = None
    events: list[StageEvent] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# /provenance response
# ---------------------------------------------------------------------------

class ModuleStatus(BaseModel):
    """One pipeline module's wired/aspirational status."""

    module: str
    status: Literal["wired", "aspirational"]
    note: str


class DataVersionEntry(BaseModel):
    """One external dataset version as reported by a committed provenance sidecar."""

    name: str
    source_doi: str
    access_date: str
    row_count: int | None
    description: str


class ProvenanceReport(BaseModel):
    """
    Response body for GET /provenance.

    Reports:
    - live data versions from committed provenance sidecars (no hardcoded numbers)
    - which pipeline modules are wired vs aspirational
    - the explicit non-claims from AGENTS.md
    - live runtime backend status (guardian, chat, artifacts, classifier)
    """

    falsifier_version: str
    """Read from falsifier.__version__ at request time."""

    data_versions: list[DataVersionEntry]
    """
    Populated by scanning data/golden/*.provenance.json.
    Every entry originates from a committed artifact — no numbers are
    hardcoded in this endpoint.
    """

    modules: list[ModuleStatus]
    """Current wired-vs-aspirational state of each pipeline module."""

    non_claims: list[str]
    """Verbatim non-claim statements from AGENTS.md."""

    golden_manifest_entry_count: int
    """Number of entries in data/golden/MANIFEST.json at request time."""

    # -----------------------------------------------------------------------
    # Runtime self-report fields (added per Task 3)
    # -----------------------------------------------------------------------

    guardian_backend: str | None = None
    """
    "granite-guardian-3.1-2b" if the model loaded from local HF cache;
    "rule_based_heuristic" if it fell back.
    Read from the actual loaded state in falsifier.api.chat.guardian at
    request time — not inferred from an env var.
    """

    chat_backend: str | None = None
    """
    "openai:<model_id>" if OPENAI_API_KEY is set and a call has succeeded;
    "templated_offline" otherwise.
    """

    artifacts_present: dict[str, bool] | None = None
    """
    Per-artifact boolean: True if the file exists on the filesystem at
    request time, False if it does not.
    Keys: "injection_recovery", "adversarial_selftest".
    Both are currently absent; this field reports False rather than
    omitting the key.
    """

    classifier_trained: bool | None = None
    """
    False while train_classifier_dr25.py raises NotImplementedError.
    See blocked_reason for the explanation.
    """

    classifier_blocked_reason: str | None = None
    """
    Human-readable explanation of why classifier_trained is False,
    pointing at docs/SKIPPED_TESTS.md.
    """
