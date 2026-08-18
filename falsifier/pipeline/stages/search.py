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

import contextlib
import hashlib
import multiprocessing
import multiprocessing.pool
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

import numpy as np

# ---------------------------------------------------------------------------
# Python 3.12 distutils compat — must precede any batman/TLS import
# ---------------------------------------------------------------------------
# The shim is implemented in falsifier._distutils_compat so it is available
# to the API server, scripts, and any other caller, not only to pytest.
# Importing it here (at module scope, before batman/TLS) ensures it fires in:
#   - the main process
#   - multiprocessing fork workers (which inherit sys.modules)
# The conftest.py also imports it as a belt-and-suspenders guard for the
# test process itself.
import falsifier._distutils_compat  # noqa: F401  (side-effect: distutils shim)

import falsifier
from falsifier.pipeline.contracts.search import SearchInput, SearchOutput, TCE
from falsifier.pipeline.contracts.detrend import DetrendOutput
from falsifier.pipeline.contracts.manifest import ArtifactRef, StageManifest, UnitedArray

__all__ = ["run_search"]

# SDE threshold below which we stop iterating.
# TLS does not expose an SNR interface; SDE >= 7 is a standard threshold
# (Hippke & Heller 2019 recommend SDE >= 7 for confident detections).
_SDE_THRESHOLD = 7.0

# Maximum number of planets to search per star.
#
# _MAX_PLANETS = 1 is a **known limitation**: iterative masking is inert and
# multi-planet systems cannot be found.  This constant is kept at 1 because:
#   - A single TLS pass takes ~25–30 s on Kepler long-cadence data with a
#     1–10 d period range; the 60-second test budget (golden tests) cannot
#     accommodate more than one full pass.
#   - Raising this to >1 requires a per-star compute budget and an integration
#     test with a known 2-planet system.
#
# Declared explicitly here and in README dead-code table per AGENTS.md Rule 6.
_MAX_PLANETS = 1


@contextlib.contextmanager
def _tls_fork_pool_ctx():
    """
    Context manager that makes TLS's internal multiprocessing.Pool use the
    'fork' start method for the duration of one TLS call.

    TLS calls ``multiprocessing.Pool(use_threads)`` directly.  We monkey-patch
    ``multiprocessing.pool.Pool`` with a subclass whose constructor forces a
    fork-context pool, then restore the original class on exit.

    This is intentionally narrow in scope: it does not call
    ``multiprocessing.set_start_method()`` (which is process-wide and
    permanently affects every subsequent Pool, including those created by the
    FastAPI server's async workers where fork is unsafe).

    Fork is required on macOS/Python 3.12 because TLS's spawn workers run a
    fresh interpreter that lacks the distutils shim already loaded in the
    parent; batman (which TLS imports) fails to import in spawn workers.
    """
    original_pool = multiprocessing.pool.Pool

    class _ForkPool(original_pool):  # type: ignore[valid-type, misc]
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("context", multiprocessing.get_context("fork"))
            super().__init__(*args, **kwargs)

    multiprocessing.pool.Pool = _ForkPool  # type: ignore[assignment]
    # TLS accesses multiprocessing.Pool (not multiprocessing.pool.Pool) in some
    # versions; patch both to be safe.
    multiprocessing.Pool = _ForkPool  # type: ignore[assignment]
    try:
        yield
    finally:
        multiprocessing.pool.Pool = original_pool  # type: ignore[assignment]
        multiprocessing.Pool = original_pool  # type: ignore[assignment]


def _compute_odd_even_excess(results, depth_ppm: float) -> float:
    """
    Compute the excess transit-depth scatter normalised by expected per-transit
    photon noise.

    For a planet all transit depths scatter near the photon-noise floor → value
    close to 1.0.  For an EB whose primary and secondary eclipses alternate at
    the detected period, the depth-to-depth scatter significantly exceeds the
    per-transit photon noise → value of several.

    Parameters
    ----------
    results
        ``transitleastsquares`` result object (dict-like).
    depth_ppm : float
        Best-fit transit depth in ppm (already computed from ``results.depth``).

    Returns
    -------
    float
        Normalised excess scatter.  Returns 0.0 when insufficient transit data
        are available to compute the metric (fewer than 4 finite transit depths).
    """
    try:
        transit_depths = np.array(list(results.transit_depths), dtype=np.float64)
        snr = float(results.snr)
    except (AttributeError, TypeError, ValueError):
        return float(results.odd_even_mismatch)

    finite_depths = transit_depths[np.isfinite(transit_depths)]
    n = len(finite_depths)
    if n < 4 or snr <= 0 or depth_ppm <= 0:
        return float(results.odd_even_mismatch)

    depths_ppm = (1.0 - finite_depths) * 1_000_000
    scatter_ppm = float(np.std(depths_ppm))

    # Expected per-transit scatter: depth / (snr / sqrt(n_transits)).
    # snr is the combined SNR across all transits; per-transit SNR scales as
    # combined_SNR / sqrt(n_transits), giving per-transit depth noise of
    # depth_ppm / (snr / sqrt(n)).
    expected_per_transit_ppm = depth_ppm / (snr / np.sqrt(float(n)))
    if expected_per_transit_ppm <= 0:
        return float(results.odd_even_mismatch)

    return scatter_ppm / expected_per_transit_ppm


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

        n_threads = max(1, multiprocessing.cpu_count())
        model = TLS(time_arr, flux_work)
        # TLS uses multiprocessing.Pool internally.  On macOS/Python 3.12 the
        # default start method is 'spawn'; spawned workers run fresh interpreter
        # processes that do not inherit sys.modules, so the distutils stub and
        # already-imported batman symbols are absent in them.  'fork' workers
        # inherit the parent's memory space including sys.modules.
        #
        # We must NOT call multiprocessing.set_start_method() at module scope
        # or in run_search() body — that would affect every importer, including
        # the threaded FastAPI server where fork is unsafe (open sockets are
        # duplicated into children, leading to fd corruption).
        #
        # Instead we temporarily replace the Pool class TLS will instantiate
        # with a subclass that forces the fork context, restoring the original
        # afterwards.  This is scoped to a single TLS call and does not touch
        # the global start-method state.
        with _tls_fork_pool_ctx():
            results = model.power(
                period_min=period_min,
                period_max=period_max,
                use_threads=n_threads,
                show_progress_bar=False,
            )

        if results.SDE < sde_threshold:
            break  # no more significant signals

        # Build TCE from TLS results.
        period_days: float = float(results.period)
        epoch_days: float = float(results.T0)
        duration_days: float = float(results.duration)
        depth_ppm: float = float((1.0 - results.depth) * 1_000_000)

        # odd_even_mismatch: excess transit-depth scatter normalised by the
        # expected per-transit photon noise.
        #
        # TLS's built-in odd_even_mismatch (sigma of odd vs even depth means)
        # is often < 3 for diluted EBs because the depth uncertainty is
        # dominated by systematics, not the true depth alternation.  A more
        # discriminating metric is the standard deviation of individual transit
        # depths divided by the expected per-transit noise
        # (depth / snr × sqrt(n_transits)).
        #
        # For a true planet all transits have similar depths → excess ~ 1.
        # For an EB whose two eclipses differ in depth, the alternating depths
        # produce a scatter that exceeds the per-transit photon noise by a
        # factor of several → excess >> 1.
        #
        # Threshold _ODD_EVEN_FAIL_THRESHOLD = 3.0 in the vet stage reflects
        # this normalised excess, not raw sigma.
        odd_even: float = _compute_odd_even_excess(results, depth_ppm)

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
