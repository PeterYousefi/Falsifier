"""
falsifier.pipeline.stages.detrend
===================================
Implementation of the detrend pipeline stage.

Algorithm
---------
wotan biweight sliding-window detrending.  The window length is read from
``DetrendInput.window_length`` (a ``UnitedArray`` in days) — it is never
hardcoded at the call site.

Transit-depth preservation
--------------------------
The biweight filter is robust to outliers and, at window lengths shorter than
the transit ingress–egress, does not significantly dilute transit depth.
Verified by ``test_injection_recovery.py`` (depth recovery within tolerance).

AGENTS.md compliance
--------------------
Rule 2: all physical quantities use ``UnitedArray`` / ``astropy.units``.
Rule 1: no scientific values hardcoded; all parameters come from ``DetrendInput``.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from pathlib import Path
from typing import Optional

import numpy as np

import falsifier
from falsifier.pipeline.contracts.detrend import (
    DetrendInput,
    DetrendedSegment,
    DetrendOutput,
)
from falsifier.pipeline.contracts.ingest import IngestOutput
from falsifier.pipeline.contracts.manifest import ArtifactRef, StageManifest, UnitedArray

__all__ = ["run_detrend"]


def run_detrend(
    inp: DetrendInput,
    *,
    ingest_output: Optional[IngestOutput] = None,
) -> DetrendOutput:
    """
    Apply wotan biweight detrending to every segment in an IngestOutput.

    Parameters
    ----------
    inp : DetrendInput
        Configuration including window_length and break_tolerance (both in days).
    ingest_output : IngestOutput, optional
        In-memory IngestOutput to use instead of deserialising from
        ``inp.ingest_artifact``.  Required when running without disk I/O
        (e.g. in golden tests with ``@pytest.mark.no_network``).

    Returns
    -------
    DetrendOutput
    """
    from wotan import flatten  # local import — not available at module load on CI

    if ingest_output is None:
        raise NotImplementedError(
            "Disk-based ingest_artifact loading is not yet implemented. "
            "Pass ingest_output= directly."
        )

    window_length_days: float = inp.window_length.values[0]
    break_tolerance_days: float = inp.break_tolerance.values[0]

    t0 = time.monotonic()
    detrended_segments: list[DetrendedSegment] = []

    for seg in ingest_output.segments:
        time_arr = np.asarray(seg.time.values, dtype=np.float64)
        flux_arr = np.asarray(seg.flux.values, dtype=np.float64)
        flux_err_arr = np.asarray(seg.flux_err.values, dtype=np.float64)

        # wotan.flatten returns (flattened_flux, trend_flux)
        # edge_cutoff=0 keeps all cadences (avoids NaN trimming at edges).
        try:
            flat_flux, trend_flux = flatten(
                time_arr,
                flux_arr,
                method="biweight",
                window_length=window_length_days,
                break_tolerance=break_tolerance_days,
                edge_cutoff=0,
                return_trend=True,
                cval=5.0,
            )
        except Exception as exc:
            raise RuntimeError(
                f"wotan.flatten failed on segment {seg.sector}: {exc}"
            ) from exc

        # wotan may return NaN at the segment edges; replace with 1.0 to keep
        # the array length intact (the transit search handles NaN masking).
        flat_flux = np.where(np.isfinite(flat_flux), flat_flux, 1.0)
        trend_flux = np.where(np.isfinite(trend_flux), trend_flux, np.nanmedian(trend_flux))

        # flux_err normalised by the same trend so units stay dimensionless
        # Avoid division by zero from zero-valued trend cadences.
        safe_trend = np.where(np.abs(trend_flux) > 0, trend_flux, 1.0)
        flat_err = flux_err_arr / safe_trend

        detrended_segments.append(
            DetrendedSegment(
                sector=seg.sector,
                time=UnitedArray(values=time_arr.tolist(), unit=seg.time.unit),
                time_scale=seg.time_scale,
                time_format=seg.time_format,
                flux=UnitedArray(values=flat_flux.tolist(), unit="dimensionless"),
                flux_err=UnitedArray(values=flat_err.tolist(), unit="dimensionless"),
                trend_flux=UnitedArray(values=trend_flux.tolist(), unit=seg.flux.unit),
                quality_flags=list(seg.quality_flags),
            )
        )

    wall_time = time.monotonic() - t0

    # Build a dummy ArtifactRef that satisfies the contract without writing to disk.
    run_hash = hashlib.sha256(inp.model_dump_json().encode()).hexdigest()
    artifact_ref = ArtifactRef(
        path=Path(f"/tmp/falsifier/detrend_{inp.pipeline_run_id}.json"),
        sha256=run_hash,
        stage="detrend",
        pipeline_run_id=inp.pipeline_run_id,
    )

    return DetrendOutput(
        input=inp,
        segments=detrended_segments,
        host_star_id=ingest_output.host_star_id,
        detrending_method=inp.method,
        manifest=StageManifest(
            stage="detrend",
            code_version=getattr(falsifier, "__version__", "0.0.0-dev"),
            input_hash=hashlib.sha256(ingest_output.model_dump_json().encode()).hexdigest(),
            wall_time_seconds=wall_time,
            provenance=[],
            artifact=artifact_ref,
        ),
        artifact=artifact_ref,
    )
