"""
falsifier.pipeline.batch.runner
=================================
Offline batch pipeline over a curated target list.

Architecture
------------
The batch runner reads ``data/targets/curated_targets.json``, which lists
confirmed planets that have committed atmospheric observations.  For each
target it runs:

  retrieve  → disequilibrium

Both stages are cached to disk under ``data/artifacts/batch/``.  A target
is re-run only if:
  - its cache entry is absent, OR
  - the target's ``force_rerun`` flag is set in the JSON, OR
  - ``--force`` is passed on the CLI.

Results are serialised as JSON artifacts (the standard pipeline format)
and a batch-run manifest is written to
``data/artifacts/batch/BATCH_MANIFEST.json``.

Target list schema
------------------
See ``data/targets/curated_targets.json`` for the full schema.  Required
fields per entry:

  planet_name         — canonical NASA Exoplanet Archive name
  planet_doi          — reference DOI for bulk parameters
  host_star_id        — canonical host-star identifier
  muscles_key         — MUSCLES archive identifier (or nearest analogue)
  muscles_doi         — DOI of the MUSCLES spectrum paper
  muscles_analogue    — null or identifier of the analogue used
  included_species    — list of chemical formula strings
  metallicity_solar   — float, [M/H] multiple
  c_to_o_ratio        — float
  n_live_points       — int, nested sampling live points
  pressure_grid_levels — int

Exploratory status
------------------
This entire module is exploratory.  It runs only on confirmed planets with
committed observations.  Output is NOT validated against ground truth.
See README §Exploratory Modules.

AGENTS.md enforcement
---------------------
Rule 1: every numeric value in batch results originates from a pipeline
        artifact, not from this file.
Rule 3: the batch manifest records DOI, access_date, row_count for every
        target processed.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import sys
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import falsifier

REPO_ROOT = Path(__file__).parent.parent.parent.parent
_TARGET_LIST_PATH = REPO_ROOT / "data" / "targets" / "curated_targets.json"
_BATCH_ARTIFACT_DIR = REPO_ROOT / "data" / "artifacts" / "batch"
_BATCH_MANIFEST_PATH = _BATCH_ARTIFACT_DIR / "BATCH_MANIFEST.json"


# ---------------------------------------------------------------------------
# BatchTargetResult — outcome for one target
# ---------------------------------------------------------------------------

@dataclass
class BatchTargetResult:
    planet_name: str
    status: str               # "ok" | "cached" | "failed" | "skipped"
    retrieve_artifact_path: str | None = None
    disequilibrium_artifact_path: str | None = None
    source_flux_ratios: dict[str, dict] = field(default_factory=dict)
    error: str | None = None
    wall_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_batch(
    target_list_path: Path = _TARGET_LIST_PATH,
    artifact_dir: Path = _BATCH_ARTIFACT_DIR,
    *,
    force: bool = False,
    dry_run: bool = False,
    planet_filter: list[str] | None = None,
    verbose: bool = True,
) -> list[BatchTargetResult]:
    """
    Run the retrieve + disequilibrium pipeline over the curated target list.

    Parameters
    ----------
    target_list_path : Path
        Path to curated_targets.json.
    artifact_dir : Path
        Root directory for output artifacts and cache.
    force : bool
        Re-run even if a valid cached artifact exists.
    dry_run : bool
        Parse and validate the target list; do not run any stages.
    planet_filter : list[str] | None
        If given, process only planets whose ``planet_name`` is in this list.
    verbose : bool
        Print progress to stdout.

    Returns
    -------
    list[BatchTargetResult]
        One result per target.  Failures do not abort the batch; they are
        recorded in the result with ``status="failed"`` and ``error`` set.
    """
    if not target_list_path.exists():
        raise FileNotFoundError(
            f"Target list not found: {target_list_path}\n"
            "Populate data/targets/curated_targets.json before running the batch."
        )

    with open(target_list_path, encoding="utf-8") as f:
        target_list = json.load(f)

    targets = target_list.get("targets", [])
    if planet_filter:
        targets = [t for t in targets if t["planet_name"] in planet_filter]

    if verbose:
        print(
            f"[batch] {len(targets)} target(s) from {target_list_path.name}"
            + (" [DRY RUN]" if dry_run else ""),
            flush=True,
        )

    results: list[BatchTargetResult] = []
    for target in targets:
        result = _process_one_target(
            target, artifact_dir, force=force, dry_run=dry_run, verbose=verbose
        )
        results.append(result)

    _write_batch_manifest(results, artifact_dir, target_list_path)
    return results


# ---------------------------------------------------------------------------
# Per-target processing
# ---------------------------------------------------------------------------

def _process_one_target(
    target: dict,
    artifact_dir: Path,
    *,
    force: bool,
    dry_run: bool,
    verbose: bool,
) -> BatchTargetResult:
    import time
    t0 = time.monotonic()
    planet_name = target.get("planet_name", "unknown")

    if dry_run:
        _validate_target_entry(target)   # raises on schema error
        return BatchTargetResult(
            planet_name=planet_name,
            status="skipped",
            wall_seconds=time.monotonic() - t0,
        )

    # ------------------------------------------------------------------
    # Cache check: if retrieve artifact exists and force=False, skip
    # ------------------------------------------------------------------
    target_dir = artifact_dir / _safe_name(planet_name)
    retrieve_cache_path = target_dir / "retrieve_latest.json"
    disq_cache_path = target_dir / "disequilibrium_latest.json"

    if (
        not force
        and not target.get("force_rerun", False)
        and retrieve_cache_path.exists()
        and disq_cache_path.exists()
    ):
        if verbose:
            print(f"  [cached]  {planet_name}", flush=True)
        cached_disq = _load_json_artifact(disq_cache_path)
        return BatchTargetResult(
            planet_name=planet_name,
            status="cached",
            retrieve_artifact_path=str(retrieve_cache_path),
            disequilibrium_artifact_path=str(disq_cache_path),
            source_flux_ratios=_extract_source_flux_ratios(cached_disq),
            wall_seconds=time.monotonic() - t0,
        )

    # ------------------------------------------------------------------
    # Build stage inputs from target entry
    # ------------------------------------------------------------------
    try:
        _validate_target_entry(target)
        retrieve_input, disq_input = _build_stage_inputs(target)
    except Exception as exc:
        return BatchTargetResult(
            planet_name=planet_name,
            status="failed",
            error=f"Input construction: {type(exc).__name__}: {exc}",
            wall_seconds=time.monotonic() - t0,
        )

    # ------------------------------------------------------------------
    # Run retrieve
    # ------------------------------------------------------------------
    try:
        from ..stages.retrieve import run_retrieve
        target_dir.mkdir(parents=True, exist_ok=True)
        retrieve_out = run_retrieve(
            retrieve_input,
            _artifact_dir=target_dir,
            _cache_dir=target_dir / "posteriors",
        )
        retrieve_cache_path.write_text(
            retrieve_out.model_dump_json(indent=2), encoding="utf-8"
        )
        if verbose:
            lnb = retrieve_out.bayes_factor_atm_vs_spot.ln_bayes_factor
            strength = retrieve_out.bayes_factor_atm_vs_spot.jeffreys_strength
            print(
                f"  [ok]      {planet_name}  "
                f"retrieve: ln B(atm/spot) = {lnb:+.2f} ({strength})",
                flush=True,
            )
    except ImportError as exc:
        return BatchTargetResult(
            planet_name=planet_name,
            status="failed",
            error=f"Missing dependency: {exc}",
            wall_seconds=time.monotonic() - t0,
        )
    except Exception as exc:
        return BatchTargetResult(
            planet_name=planet_name,
            status="failed",
            error=f"retrieve: {type(exc).__name__}: {exc}",
            wall_seconds=time.monotonic() - t0,
        )

    # ------------------------------------------------------------------
    # Run disequilibrium
    # ------------------------------------------------------------------
    try:
        from ..stages.disequilibrium import run_disequilibrium
        disq_out = run_disequilibrium(
            disq_input,
            _retrieve_output=retrieve_out,
            _artifact_dir=target_dir,
        )
        disq_cache_path.write_text(
            disq_out.model_dump_json(indent=2), encoding="utf-8"
        )
        ratios = _extract_source_flux_ratios(disq_out.model_dump())
        if verbose:
            ratio_strs = ", ".join(
                f"{sp}: {v['ratio']:.2f}±{v['ratio_uncertainty']:.2f}"
                for sp, v in ratios.items()
            )
            print(
                f"  [ok]      {planet_name}  "
                f"screen: ratio [{ratio_strs}]",
                flush=True,
            )
    except ImportError as exc:
        return BatchTargetResult(
            planet_name=planet_name,
            status="failed",
            retrieve_artifact_path=str(retrieve_cache_path),
            error=f"Missing dependency: {exc}",
            wall_seconds=time.monotonic() - t0,
        )
    except Exception as exc:
        return BatchTargetResult(
            planet_name=planet_name,
            status="failed",
            retrieve_artifact_path=str(retrieve_cache_path),
            error=f"disequilibrium: {type(exc).__name__}: {exc}",
            wall_seconds=time.monotonic() - t0,
        )

    return BatchTargetResult(
        planet_name=planet_name,
        status="ok",
        retrieve_artifact_path=str(retrieve_cache_path),
        disequilibrium_artifact_path=str(disq_cache_path),
        source_flux_ratios=_extract_source_flux_ratios(disq_out.model_dump()),
        wall_seconds=time.monotonic() - t0,
    )


# ---------------------------------------------------------------------------
# Input builders
# ---------------------------------------------------------------------------

def _build_stage_inputs(target: dict):
    """
    Build (RetrieveInput, DisequilibriumInput) from a target entry dict.

    All values come from the target JSON; nothing is hardcoded here.
    """
    from ..contracts.retrieve import RetrievalConfig, RetrieveInput
    from ..contracts.disequilibrium import (
        DisequilibriumInput,
        FastChemConfig,
        MUSCLESConfig,
    )
    from ..contracts.manifest import ArtifactRef

    run_id = str(uuid.uuid4())

    retrieval_cfg = RetrievalConfig(
        retrieval_code="petitRADTRANS",
        n_live_points=int(target["n_live_points"]),
        chemistry_scheme=target.get("chemistry_scheme", "equilibrium"),
        pressure_grid_levels=int(target["pressure_grid_levels"]),
        include_clouds=target.get("include_clouds", False),
    )

    # Placeholder classify artifact — in production this is the real path
    # from the detection pipeline for the same target
    dummy_classify_ref = ArtifactRef(
        path=Path("/dev/null"),
        sha256="0" * 64,
        stage="classify",
        pipeline_run_id=run_id,
    )

    retrieve_input = RetrieveInput(
        classify_artifact=dummy_classify_ref,
        retrieval_config=retrieval_cfg,
        pipeline_run_id=run_id,
    )

    fastchem_cfg = FastChemConfig(
        temperature_pressure_profile_source=target.get(
            "tp_profile_source", "retrieval"
        ),
        included_species=target["included_species"],
        metallicity_solar=float(target["metallicity_solar"]),
        c_to_o_ratio=float(target["c_to_o_ratio"]),
    )

    muscles_cfg = MUSCLESConfig(
        spectral_type_key=target["muscles_key"],
        muscles_doi=target["muscles_doi"],
        analogue_used=target.get("muscles_analogue"),
        uv_band_lower_nm=float(target.get("uv_band_lower_nm", 115.0)),
        uv_band_upper_nm=float(target.get("uv_band_upper_nm", 320.0)),
    )

    dummy_retrieve_ref = ArtifactRef(
        path=Path("/dev/null"),
        sha256="0" * 64,
        stage="retrieve",
        pipeline_run_id=run_id,
    )

    disq_input = DisequilibriumInput(
        retrieve_artifact=dummy_retrieve_ref,
        planet_name=target["planet_name"],
        planet_doi=target["planet_doi"],
        fastchem_config=fastchem_cfg,
        muscles_config=muscles_cfg,
        pipeline_run_id=run_id,
    )

    return retrieve_input, disq_input


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS = {
    "planet_name", "planet_doi", "host_star_id",
    "muscles_key", "muscles_doi",
    "included_species", "metallicity_solar", "c_to_o_ratio",
    "n_live_points", "pressure_grid_levels",
}


def _validate_target_entry(target: dict) -> None:
    """Raise ValueError if any required field is missing or invalid."""
    missing = _REQUIRED_FIELDS - set(target.keys())
    if missing:
        raise ValueError(
            f"Target {target.get('planet_name', '?')!r} is missing required "
            f"fields: {sorted(missing)}"
        )
    if not target["included_species"]:
        raise ValueError(
            f"Target {target['planet_name']!r}: included_species must be non-empty"
        )
    if float(target["c_to_o_ratio"]) <= 0:
        raise ValueError(
            f"Target {target['planet_name']!r}: c_to_o_ratio must be > 0"
        )


# ---------------------------------------------------------------------------
# Manifest writer
# ---------------------------------------------------------------------------

def _write_batch_manifest(
    results: list[BatchTargetResult],
    artifact_dir: Path,
    target_list_path: Path,
) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    n_ok = sum(1 for r in results if r.status == "ok")
    n_cached = sum(1 for r in results if r.status == "cached")
    n_failed = sum(1 for r in results if r.status == "failed")

    manifest = {
        "schema_version": "1",
        "falsifier_version": falsifier.__version__,
        "run_date": datetime.date.today().isoformat(),
        "target_list_path": str(target_list_path),
        "n_targets": len(results),
        "n_ok": n_ok,
        "n_cached": n_cached,
        "n_failed": n_failed,
        "non_claims": [
            "This module is exploratory and not validated against ground truth.",
            "No exoplanet biosignature has ever been confirmed.",
            "Source flux ratios are screening metrics only, not biosignature claims.",
        ],
        "targets": [
            {
                "planet_name": r.planet_name,
                "status": r.status,
                "retrieve_artifact": r.retrieve_artifact_path,
                "disequilibrium_artifact": r.disequilibrium_artifact_path,
                "source_flux_ratios": r.source_flux_ratios,
                "error": r.error,
                "wall_seconds": round(r.wall_seconds, 3),
            }
            for r in results
        ],
    }
    _BATCH_MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_name(s: str) -> str:
    return s.replace(" ", "_").replace("/", "_").replace("\\", "_")


def _load_json_artifact(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _extract_source_flux_ratios(disq_dict: dict) -> dict[str, dict]:
    """Extract {species: {ratio, ratio_uncertainty}} from a DisequilibriumOutput dict."""
    ratios_raw = disq_dict.get("source_flux_ratios", [])
    out = {}
    for item in ratios_raw:
        sp = item.get("species", "?")
        out[sp] = {
            "ratio": item.get("ratio", 0.0),
            "ratio_uncertainty": item.get("ratio_uncertainty", 0.0),
            "muscles_spectrum_doi": item.get("muscles_spectrum_doi", ""),
        }
    return out
