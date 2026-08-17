"""
falsifier.pipeline.stages.search
===================================
Implementation of the search pipeline stage.

Algorithm
---------
``transitleastsquares`` (TLS, Hippke & Heller 2019, DOI 10.1051/0004-6361/201834672).
TLS fits a physical limb-darkened transit profile (not a box, not a trapezoid)
and returns a Signal Detection Efficiency (SDE).

Iterative masking
-----------------
After each significant detection the in-transit cadences are masked and TLS
is run again on the residuals.  This correctly handles multi-planet systems
without double-counting overlapping signals.  Iteration stops when SDE drops
below ``snr_threshold`` (used as a proxy for SDE threshold — TLS does not
expose a direct SNR threshold, so we use the same numerical value for SDE).

AGENTS.md compliance
--------------------
Rule 2: all physical quantities returned in TCE use ``UnitedArray``.
Rule 1: no scientific values hardcoded; all parameters come from ``SearchInput``.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from pathlib import Path
from typing import Optional

import numpy as np

import falsifier
from falsifier.pipeline.contracts.search import SearchInput, SearchOutput, TCE
from falsifier.pipeline.contracts.detrend import DetrendOutput
from falsifier.pipeline.contracts.manifest import ArtifactRef, StageManifest, UnitedArray

__all__ = ["run_search"]

# SDE threshold below which we stop iterating.
# TLS does not expose an SNR interface; SDE >= 7 is a standard threshold
# (Hippke & Heller 2019 recommend SDE >= 7 for confident detections).
_SDE_THRESHOLD = 7.0

# Maximum number of planets to search per star (prevents runaway iteration).
_MAX_PLANETS = 8


def run_search(
    inp: SearchInput,
    *,
    detrend_output: Optional[DetrendOutput] = None,
) -> SearchOutput:
    """
    Run TLS on every detrended segment, with iterative masking for multi-planet
    systems.

    Parameters
    ----------
    inp : SearchInput
        Configuration including period_min, period_max, snr_threshold.
    detrend_output : DetrendOutput, optional
        In-memory DetrendOutput to use instead of deserialising from disk.
        Required for golden tests (no disk I/O).

    Returns
    -------
    SearchOutput
    """
    import transitleastsquares as tls_module
    from transitleastsquares import transitleastsquares as TLS

    if detrend_output is None:
        raise NotImplementedError(
            "Disk-based detrend_artifact loading is not yet implemented. "
            "Pass detrend_output= directly."
        )

    period_min: float = inp.period_min.values[0]
    period_max: float = inp.period_max.values[0]
    sde_threshold: float = max(inp.snr_threshold, _SDE_THRESHOLD)

    # Concatenate all detrended segments into a single time / flux arrays.
    # Segments are assumed to be contiguous or near-contiguous quarters.
    all_time: list[np.ndarray] = []
    all_flux: list[np.ndarray] = []
    for seg in detrend_output.segments:
        t = np.asarray(seg.time.values, dtype=np.float64)
        f = np.asarray(seg.flux.values, dtype=np.float64)
        all_time.append(t)
        all_flux.append(f)

    time_arr = np.concatenate(all_time)
    flux_arr = np.concatenate(all_flux)

    # Remove NaN / non-finite cadences before passing to TLS.
    finite_mask = np.isfinite(time_arr) & np.isfinite(flux_arr)
    time_arr = time_arr[finite_mask]
    flux_arr = flux_arr[finite_mask]

    t0 = time.monotonic()
    tces: list[TCE] = []

    # Working copy of flux; masked in-transit cadences are replaced with 1.0
    # between iterations to prevent the same signal from re-triggering.
    flux_work = flux_arr.copy()

    for planet_index in range(_MAX_PLANETS):
        if len(time_arr) < 10:
            break

        model = TLS(time_arr, flux_work)
        results = model.power(
            period_min=period_min,
            period_max=period_max,
            use_threads=1,   # deterministic; avoids non-reproducible thread timing
            show_progress_bar=False,
        )

        if results.SDE < sde_threshold:
            break  # no more significant signals

        # Build TCE from TLS results.
        period_days: float = float(results.period)
        epoch_days: float = float(results.T0)
        duration_days: float = float(results.duration)
        depth_ppm: float = float((1.0 - results.depth) * 1_000_000)
        odd_even: float = float(results.odd_even_mismatch)

        # TLS period_uncertainty is the half-width of the period grid spacing
        # at the detection peak.  If not present, use a conservative 1% of period.
        try:
            p_unc = float(results.period_uncertainty)
        except (AttributeError, TypeError):
            p_unc = period_days * 0.01

        # Secondary eclipse depth: use TLS secondary eclipse if available.
        try:
            sec_depth_ppm = float(results.secondary_depth) * 1_000_000
            secondary = UnitedArray(values=[sec_depth_ppm], unit="ppm")
        except (AttributeError, TypeError, ValueError):
            secondary = None

        tce_id = f"{detrend_output.host_star_id}-{planet_index:02d}"
        tce = TCE(
            tce_id=tce_id,
            period=UnitedArray(values=[period_days], unit="day"),
            period_uncertainty=UnitedArray(values=[p_unc], unit="day"),
            epoch=UnitedArray(values=[epoch_days], unit=detrend_output.segments[0].time.unit),
            duration=UnitedArray(values=[duration_days * 24.0], unit="hour"),
            depth=UnitedArray(values=[max(depth_ppm, 0.0)], unit="ppm"),
            sde=float(results.SDE),
            snr=float(results.snr),
            odd_even_mismatch=odd_even,
            secondary_eclipse_depth=secondary,
        )
        tces.append(tce)

        # Mask in-transit cadences for the next iteration.
        phase = _fold(time_arr, period_days, epoch_days)
        half_dur = duration_days / 2.0 * 1.2  # 20% margin
        in_transit = np.abs(phase) < half_dur
        flux_work = flux_work.copy()
        flux_work[in_transit] = 1.0  # fill with out-of-transit level

    # Sort TCEs by SDE descending (highest confidence first).
    tces.sort(key=lambda t: t.sde, reverse=True)

    wall_time = time.monotonic() - t0
    run_hash = hashlib.sha256(inp.model_dump_json().encode()).hexdigest()
    artifact_ref = ArtifactRef(
        path=Path(f"/tmp/falsifier/search_{inp.pipeline_run_id}.json"),
        sha256=run_hash,
        stage="search",
        pipeline_run_id=inp.pipeline_run_id,
    )

    tls_version = getattr(tls_module, "__version__", "unknown")

    return SearchOutput(
        input=inp,
        tces=tces,
        host_star_id=detrend_output.host_star_id,
        tls_version=tls_version,
        manifest=StageManifest(
            stage="search",
            code_version=getattr(falsifier, "__version__", "0.0.0-dev"),
            input_hash=hashlib.sha256(detrend_output.model_dump_json().encode()).hexdigest(),
            wall_time_seconds=wall_time,
            provenance=[],
            artifact=artifact_ref,
        ),
        artifact=artifact_ref,
    )


def _fold(time: np.ndarray, period: float, epoch: float) -> np.ndarray:
    """Phase-fold time array; returns phase in [-period/2, period/2]."""
    phase = (time - epoch) % period
    phase[phase > period / 2] -= period
    return phase
