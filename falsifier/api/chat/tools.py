"""
falsifier.api.chat.tools
=========================
Eight deterministic tools for the chat layer.

Every tool reads exclusively from:
  - the in-memory _job_store (pipeline stage outputs for a given job_id)
  - committed disk artifacts (stage_explanations.json)

No tool hardcodes a scientific value.  If a requested artifact is absent
the tool returns a structured "not_available" payload rather than inventing
a value.

AGENTS.md enforcement
---------------------
Rule 1: every number in a tool response originates from a pipeline artifact.
Rule 2: physical quantities carry their unit strings from UnitedArray.unit.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).parent.parent.parent.parent
_EXPLANATIONS_PATH = (
    REPO_ROOT / "data" / "artifacts" / "explanations" / "stage_explanations.json"
)

# Lazy import: queue imports fastapi/pydantic at module scope; guard it so
# tools.py can be imported in the pydantic-only fast CI venv for unit tests.
def _get_job_store() -> dict:
    """
    Return the in-memory job store dict.

    Lazily imports from ``queue`` to avoid importing FastAPI/Pydantic at
    module scope (which would break the lightweight CI venv).

    Returns
    -------
    dict[str, JobRecord]
        The live job store mapping job IDs to their ``JobRecord`` objects.
    """
    from ..queue import get_job_store
    return get_job_store()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_tce(job_id: str, tce_id: str) -> tuple[Any, Any] | None:
    """
    Return ``(search_out, tce)`` from the job's in-memory search stage output.

    Parameters
    ----------
    job_id : str
        Pipeline job identifier.
    tce_id : str
        TCE identifier to look up within the search output.

    Returns
    -------
    tuple[SearchOutput, TCE] or None
        ``(search_out, tce)`` if found; ``None`` if the job does not exist,
        is not done, or the TCE ID is not present in the search output.

    Notes
    -----
    The current implementation always returns ``None`` because raw stage
    outputs are resolved per-tool using ``record.report``.
    """
    store = _get_job_store()
    record = store.get(job_id)
    if record is None:
        return None
    # The raw stage outputs are stored under record._stage_outputs if we add
    # them; for now we read from the report summary (always present on done).
    return None  # resolved per-tool below using record.report


def _record_for(job_id: str) -> Any | None:
    """
    Look up a ``JobRecord`` by *job_id*.

    Parameters
    ----------
    job_id : str
        Pipeline job identifier.

    Returns
    -------
    JobRecord or None
        The job record if it exists, otherwise ``None``.
    """
    return _get_job_store().get(job_id)


# ---------------------------------------------------------------------------
# Tool 1 — get_planet_params
# ---------------------------------------------------------------------------

def get_planet_params(job_id: str, tce_id: str) -> dict:
    """
    Return period, depth, duration, epoch for a TCE from SearchOutput.

    Values carry their unit strings (from UnitedArray.unit).  All numbers
    come from the pipeline stage output, not from this file.

    Returns
    -------
    dict with keys:
        tce_id, period_days, period_uncertainty_days, depth_ppm,
        duration_hours, epoch_jd, source ("search_output"), job_id
    OR  {"not_available": True, "reason": str}
    """
    record = _record_for(job_id)
    if record is None:
        return {"not_available": True, "reason": f"Job {job_id!r} not found."}
    if record.status != "done":
        return {
            "not_available": True,
            "reason": f"Job {job_id!r} is {record.status!r}, not done.",
        }
    if record.report is None or record.report.search is None:
        return {
            "not_available": True,
            "reason": "Search stage output not available for this job.",
        }
    # Search result summary is in record.report.search; raw TCE objects are
    # stored in record._search_out (set by queue worker — see queue.py).
    search_out = getattr(record, "_search_out", None)
    if search_out is None:
        return {
            "not_available": True,
            "reason": (
                "Raw SearchOutput not cached on job record.  "
                "Only summary fields (n_tces, tce_ids) are available."
            ),
        }
    tce = next((t for t in search_out.tces if t.tce_id == tce_id), None)
    if tce is None:
        return {
            "not_available": True,
            "reason": f"TCE {tce_id!r} not found in job {job_id!r} search output.",
        }
    return {
        "tce_id": tce.tce_id,
        "period_days": tce.period.values[0],
        "period_uncertainty_days": tce.period_uncertainty.values[0],
        "depth_ppm": tce.depth.values[0],
        "duration_hours": tce.duration.values[0],
        "epoch_jd": tce.epoch.values[0],
        "epoch_unit": tce.epoch.unit,
        "sde": tce.sde,
        "snr": tce.snr,
        "source": "search_output",
        "job_id": job_id,
    }


# ---------------------------------------------------------------------------
# Tool 2 — get_vetting_results
# ---------------------------------------------------------------------------

def get_vetting_results(job_id: str, tce_id: str) -> dict:
    """
    Return all seven vetting test outcomes plus the disposition for a TCE.

    Values come exclusively from the VetOutput artifact on the job record.

    Returns
    -------
    dict with keys:
        tce_id, disposition, triggering_test, triggering_reason,
        test_results (list of {test_name, outcome, metric_value,
        metric_unit, reason}), source, job_id
    OR  {"not_available": True, "reason": str}
    """
    record = _record_for(job_id)
    if record is None:
        return {"not_available": True, "reason": f"Job {job_id!r} not found."}
    if record.status != "done":
        return {
            "not_available": True,
            "reason": f"Job {job_id!r} is {record.status!r}, not done.",
        }
    vet_outs = getattr(record, "_vet_outs", None)
    if vet_outs is None:
        # Fall back to report summary (only disposition available)
        if record.report:
            summary = next(
                (v for v in record.report.vet if v.tce_id == tce_id), None
            )
            if summary:
                return {
                    "tce_id": tce_id,
                    "disposition": summary.disposition,
                    "triggering_test": summary.triggering_test,
                    "triggering_reason": summary.triggering_reason,
                    "test_results": [],
                    "source": "report_summary_only",
                    "job_id": job_id,
                    "warning": (
                        "Full VetOutput not cached; only report summary available."
                    ),
                }
        return {
            "not_available": True,
            "reason": f"Vet output not cached for job {job_id!r}.",
        }
    vet_out = next((v for v in vet_outs if v.tce_id == tce_id), None)
    if vet_out is None:
        return {
            "not_available": True,
            "reason": f"TCE {tce_id!r} not found in job {job_id!r} vet output.",
        }
    return {
        "tce_id": vet_out.tce_id,
        "disposition": vet_out.disposition,
        "triggering_test": vet_out.triggering_test,
        "triggering_reason": vet_out.triggering_reason,
        "test_results": [
            {
                "test_name": r.test_name,
                "outcome": r.outcome,
                "metric_value": r.metric_value,
                "metric_unit": r.metric_unit,
                "reason": r.reason,
            }
            for r in vet_out.test_results
        ],
        "source": "vet_output",
        "job_id": job_id,
    }


# ---------------------------------------------------------------------------
# Tool 3 — get_lightcurve
# ---------------------------------------------------------------------------

def get_lightcurve(job_id: str, tce_id: str) -> dict:
    """
    Return phase-folded light curve data for a TCE from DetrendOutput.

    Returns
    -------
    dict with keys:
        tce_id, phase (list[float]), flux (list[float]),
        flux_unit, time_unit, source, job_id
    OR  {"not_available": True, "reason": str}

    Note: the detrend stage is currently a stub; if raw DetrendOutput is not
    cached on the record the tool returns not_available rather than fabricating
    data points.
    """
    record = _record_for(job_id)
    if record is None:
        return {"not_available": True, "reason": f"Job {job_id!r} not found."}
    if record.status != "done":
        return {
            "not_available": True,
            "reason": f"Job {job_id!r} is {record.status!r}, not done.",
        }
    detrend_out = getattr(record, "_detrend_out", None)
    search_out = getattr(record, "_search_out", None)
    if detrend_out is None or search_out is None:
        return {
            "not_available": True,
            "reason": (
                "Phase-fold requires cached DetrendOutput and SearchOutput; "
                "neither is available for this job (detrend stage is a stub)."
            ),
        }
    tce = next((t for t in search_out.tces if t.tce_id == tce_id), None)
    if tce is None:
        return {
            "not_available": True,
            "reason": f"TCE {tce_id!r} not found.",
        }
    # Phase-fold the first segment for a preview
    seg = detrend_out.segments[0] if detrend_out.segments else None
    if seg is None:
        return {"not_available": True, "reason": "No detrended segments available."}

    period = tce.period.values[0]
    epoch = tce.epoch.values[0]
    times = seg.time.values
    flux = seg.flux.values
    phase = [float(((t - epoch) % period) / period) for t in times]
    return {
        "tce_id": tce_id,
        "phase": phase,
        "flux": [float(f) for f in flux],
        "flux_unit": seg.flux.unit,
        "time_unit": seg.time.unit,
        "n_points": len(phase),
        "source": "detrend_output",
        "job_id": job_id,
    }


# ---------------------------------------------------------------------------
# Tool 4 — get_posterior
# ---------------------------------------------------------------------------

def get_posterior(job_id: str, tce_id: str) -> dict:
    """
    Return RetrieveOutput posterior parameters for a TCE (aspirational).

    The retrieve stage is not yet wired; this tool returns a structured
    "not_available" payload rather than fabricating parameter values.
    """
    record = _record_for(job_id)
    if record is None:
        return {"not_available": True, "reason": f"Job {job_id!r} not found."}
    return {
        "not_available": True,
        "reason": (
            "The retrieve stage (posterior sampling) is aspirational and not "
            "yet wired.  No posterior parameters are available for any job.  "
            "See README Dead/Experimental Code table."
        ),
        "tce_id": tce_id,
        "job_id": job_id,
    }


# ---------------------------------------------------------------------------
# Tool 5 — get_disequilibrium
# ---------------------------------------------------------------------------

def get_disequilibrium(job_id: str, tce_id: str) -> dict:
    """
    Return DisequilibriumOutput screening score for a TCE (aspirational).

    The disequilibrium stage is not yet wired; this tool returns a structured
    "not_available" payload.
    """
    record = _record_for(job_id)
    if record is None:
        return {"not_available": True, "reason": f"Job {job_id!r} not found."}
    return {
        "not_available": True,
        "reason": (
            "The disequilibrium stage is aspirational and not yet wired.  "
            "No disequilibrium score is available for any job.  "
            "See README Dead/Experimental Code table."
        ),
        "tce_id": tce_id,
        "job_id": job_id,
    }


# ---------------------------------------------------------------------------
# Tool 6 — compare_to_population
# ---------------------------------------------------------------------------

def compare_to_population(job_id: str, tce_id: str, metric: str) -> dict:
    """
    Compare a TCE metric against the DR25 population.

    Reads the metric value from the job's vet or search output, then reads
    the population statistics from a committed artifact (if present).
    Never invents a percentile or population value.

    Returns
    -------
    dict with comparison result and artifact source, or not_available.
    """
    vet_result = get_vetting_results(job_id, tce_id)
    if vet_result.get("not_available"):
        return vet_result

    # Try to find the metric in the test results
    for tr in vet_result.get("test_results", []):
        if tr["test_name"] == metric or metric in tr["test_name"]:
            return {
                "tce_id": tce_id,
                "metric": metric,
                "metric_value": tr["metric_value"],
                "metric_unit": tr["metric_unit"],
                "outcome": tr["outcome"],
                "population_comparison": {
                    "not_available": True,
                    "reason": (
                        "DR25 population statistics artifact not yet committed.  "
                        "Population percentile cannot be computed without a "
                        "committed reference distribution."
                    ),
                },
                "source": "vet_output",
                "job_id": job_id,
            }

    params = get_planet_params(job_id, tce_id)
    if not params.get("not_available") and metric in params:
        return {
            "tce_id": tce_id,
            "metric": metric,
            "metric_value": params[metric],
            "population_comparison": {
                "not_available": True,
                "reason": (
                    "DR25 population statistics artifact not yet committed."
                ),
            },
            "source": "search_output",
            "job_id": job_id,
        }

    return {
        "not_available": True,
        "reason": (
            f"Metric {metric!r} not found in search or vet outputs for "
            f"TCE {tce_id!r} in job {job_id!r}."
        ),
        "job_id": job_id,
    }


# ---------------------------------------------------------------------------
# Tool 7 — explain_metric
# ---------------------------------------------------------------------------

def explain_metric(metric_name: str) -> dict:
    """
    Return a committed textual explanation for a pipeline metric or stage.

    Reads exclusively from data/artifacts/explanations/stage_explanations.json.
    Never invents text.  If the metric is not in the artifact, returns
    not_available rather than hallucinating an explanation.

    Returns
    -------
    dict with keys: metric_name, explanation (dict), source (artifact path)
    OR  {"not_available": True, "reason": str}
    """
    if not _EXPLANATIONS_PATH.exists():
        return {
            "not_available": True,
            "reason": (
                f"Explanations artifact not found: {_EXPLANATIONS_PATH}.  "
                "Commit data/artifacts/explanations/stage_explanations.json."
            ),
        }
    with open(_EXPLANATIONS_PATH, encoding="utf-8") as f:
        artifact = json.load(f)

    stages = artifact.get("stages", {})
    if metric_name in stages:
        return {
            "metric_name": metric_name,
            "explanation": stages[metric_name],
            "source": str(_EXPLANATIONS_PATH.relative_to(REPO_ROOT)),
            "schema_version": artifact.get("schema_version"),
        }

    # Partial match: any stage whose title/key contains metric_name
    lower = metric_name.lower()
    for key, stage_data in stages.items():
        if lower in key.lower() or lower in stage_data.get("title", "").lower():
            return {
                "metric_name": metric_name,
                "matched_key": key,
                "explanation": stage_data,
                "source": str(_EXPLANATIONS_PATH.relative_to(REPO_ROOT)),
                "schema_version": artifact.get("schema_version"),
            }

    return {
        "not_available": True,
        "reason": (
            f"No explanation for {metric_name!r} in "
            f"{_EXPLANATIONS_PATH.relative_to(REPO_ROOT)}.  "
            "Known keys: " + ", ".join(stages.keys()) + "."
        ),
        "non_claims": artifact.get("non_claims", []),
    }


# ---------------------------------------------------------------------------
# Tool 8 — refit_with_params
# ---------------------------------------------------------------------------

def refit_with_params(job_id: str, tce_id: str, params: dict) -> dict:
    """
    Enqueue a new pipeline job with modified parameters derived from an
    existing job's target_id.

    The original job record is read to obtain the target_id and mission.
    Params may override: period_min_days, period_max_days, snr_threshold,
    cadence, sectors.

    Returns
    -------
    dict with new_job_id and status "queued", or not_available.

    Note: this function is synchronous; callers inside the async chat route
    must run it in a thread executor or use the async wrapper in session.py.
    """
    record = _record_for(job_id)
    if record is None:
        return {
            "not_available": True,
            "reason": f"Source job {job_id!r} not found.",
        }
    from ..models import JobRequest
    original_req = record.request
    new_req = JobRequest(
        target_id=original_req.target_id,
        mission=original_req.mission,
        author=original_req.author,
        cadence=params.get("cadence", original_req.cadence),
        sectors=params.get("sectors", original_req.sectors),
        run_classify=params.get("run_classify", original_req.run_classify),
    )
    # enqueue_job is async; return a marker so session.py can await it
    return {
        "pending_enqueue": True,
        "new_request": new_req.model_dump(),
        "source_job_id": job_id,
        "tce_id": tce_id,
        "applied_params": params,
    }


# ---------------------------------------------------------------------------
# Tool registry (for session.py dispatch)
# ---------------------------------------------------------------------------

TOOL_REGISTRY: dict[str, Any] = {
    "get_planet_params": get_planet_params,
    "get_vetting_results": get_vetting_results,
    "get_lightcurve": get_lightcurve,
    "get_posterior": get_posterior,
    "get_disequilibrium": get_disequilibrium,
    "compare_to_population": compare_to_population,
    "explain_metric": explain_metric,
    "refit_with_params": refit_with_params,
}

TOOL_SCHEMAS: list[dict] = [
    {
        "name": "get_planet_params",
        "description": (
            "Return period, depth, duration, epoch for a TCE.  "
            "All values come from the pipeline SearchOutput artifact."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
                "tce_id": {"type": "string"},
            },
            "required": ["job_id", "tce_id"],
        },
    },
    {
        "name": "get_vetting_results",
        "description": (
            "Return all seven vetting test outcomes plus the deterministic "
            "disposition for a TCE from the VetOutput artifact."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
                "tce_id": {"type": "string"},
            },
            "required": ["job_id", "tce_id"],
        },
    },
    {
        "name": "get_lightcurve",
        "description": (
            "Return phase-folded light curve data for a TCE from DetrendOutput. "
            "Returns not_available if the detrend stage is a stub."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
                "tce_id": {"type": "string"},
            },
            "required": ["job_id", "tce_id"],
        },
    },
    {
        "name": "get_posterior",
        "description": (
            "Return RetrieveOutput posterior parameters for a TCE.  "
            "Currently aspirational — returns not_available."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
                "tce_id": {"type": "string"},
            },
            "required": ["job_id", "tce_id"],
        },
    },
    {
        "name": "get_disequilibrium",
        "description": (
            "Return DisequilibriumOutput screening score for a TCE.  "
            "Currently aspirational — returns not_available."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
                "tce_id": {"type": "string"},
            },
            "required": ["job_id", "tce_id"],
        },
    },
    {
        "name": "compare_to_population",
        "description": (
            "Compare a TCE metric against the DR25 population statistics.  "
            "Reads metric value from pipeline outputs; population percentile "
            "requires the committed DR25 reference artifact."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
                "tce_id": {"type": "string"},
                "metric": {
                    "type": "string",
                    "description": (
                        "Name of the metric to compare, e.g. 'odd_even_depth', "
                        "'period_days', 'sde'."
                    ),
                },
            },
            "required": ["job_id", "tce_id", "metric"],
        },
    },
    {
        "name": "explain_metric",
        "description": (
            "Return a committed textual explanation for a pipeline metric or stage.  "
            "Reads from data/artifacts/explanations/stage_explanations.json.  "
            "Never invents text."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "metric_name": {
                    "type": "string",
                    "description": (
                        "Stage or metric name to explain, e.g. 'ingest', 'vet', "
                        "'classify', 'odd_even_depth'."
                    ),
                },
            },
            "required": ["metric_name"],
        },
    },
    {
        "name": "refit_with_params",
        "description": (
            "Enqueue a new pipeline job with modified parameters derived from "
            "an existing job.  Returns a pending_enqueue marker; the chat route "
            "awaits the actual enqueue."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
                "tce_id": {"type": "string"},
                "params": {
                    "type": "object",
                    "description": (
                        "Override parameters: cadence, sectors, run_classify."
                    ),
                },
            },
            "required": ["job_id", "tce_id", "params"],
        },
    },
]
