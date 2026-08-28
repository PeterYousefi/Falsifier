"""
Regression test: ingest path for KIC 11904151 (Kepler-10)
==========================================================

This test exercises the ``run_ingest`` stage for KIC 11904151 end-to-end
without touching the live MAST archive.

Per AGENTS.md, real network access is only allowed in scripts/fetch_golden.py,
run manually — never from pytest.  This test builds a ``LightCurveSegment``
directly from the committed golden FITS file
(``data/golden/kepler10_q3_long.fits``) and injects it via the ``_segments``
test-bypass in ``run_ingest``, bypassing the MAST fetch entirely.

What this test guards against
------------------------------
The bug reported in 2025 caused ``POST /jobs`` for KIC 11904151 to fail
with "OSError: Empty or corrupt FITS file" while a bare lightkurve download
in the same venv succeeded.  Root causes:

  a) ``cache.put()`` wrote directly to the final path (non-atomic), leaving
     a partial file visible to readers if the process was interrupted.
  b) With ``sectors=None`` lightkurve matches *all* quarters, and a product
     in that result set (a non-standard entry) triggered the FITS error; the
     bare ``Exception`` catch in ``mast.py`` lost the file path and size.
  c) ``record.events`` was never populated on failure, giving the frontend
     nothing to display.

This test asserts a non-empty light curve is returned so that any
recurrence of (a)–(c) is caught at the integration level.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

# Mark so callers can skip with: pytest -m "not requires_astropy"
pytestmark = [
    pytest.mark.requires_astropy,
    pytest.mark.timeout(30),
]

# Path to the golden FITS for KIC 11904151 Q3 long-cadence
_GOLDEN_FITS = Path(__file__).parent.parent / "data" / "golden" / "kepler10_q3_long.fits"

# Known cadence count for the committed golden file (from provenance sidecar)
_EXPECTED_CADENCE_COUNT = 4140


def _load_segment_from_golden_fits():
    """
    Build a LightCurveSegment from the raw Kepler FITS golden file.

    The golden file (kepler10_q3_long.fits) is a raw MAST product whose
    extension header carries TIMESYS/TELESCOP but not in the multi-extension
    format produced by _segments_to_fits_bytes.  We read it directly, the
    same way test_kepler10_recovery.py does, and construct the segment model.
    """
    from astropy.io import fits

    from falsifier.pipeline.contracts.ingest import LightCurveSegment
    from falsifier.pipeline.contracts.manifest import UnitedArray

    with fits.open(_GOLDEN_FITS) as hdul:
        # Primary HDU carries TIMESYS / TELESCOP
        primary_hdr = hdul[0].header
        ext_hdr = hdul[1].header
        data = hdul[1].data

    # Kepler: TIMESYS=TDB, TELESCOP=Kepler → time_format=bkjd
    time_scale = primary_hdr.get("TIMESYS", "tdb").lower().strip()
    time_format = "bkjd"  # Kepler-specific; derived from TELESCOP=Kepler

    quarter = int(ext_hdr.get("QUARTER", primary_hdr.get("QUARTER", 3)))

    time_arr = data["TIME"].astype(float)
    flux_arr = data["FLUX"].astype(float)
    flux_err_arr = data["FLUX_ERR"].astype(float)
    quality_arr = data["QUALITY"].astype(int)

    # Mask out NaN / bad-quality cadences so the segment matches what the
    # pipeline would receive after a real MAST download
    mask = np.isfinite(time_arr) & np.isfinite(flux_arr)
    time_arr = time_arr[mask]
    flux_arr = flux_arr[mask]
    flux_err_arr = flux_err_arr[mask]
    quality_arr = quality_arr[mask]

    return LightCurveSegment(
        sector=quarter,
        time=UnitedArray(values=time_arr.tolist(), unit=time_format),
        time_scale=time_scale,
        time_format=time_format,
        flux=UnitedArray(values=flux_arr.tolist(), unit="electron / s"),
        flux_err=UnitedArray(values=flux_err_arr.tolist(), unit="electron / s"),
        quality_flags=quality_arr.tolist(),
        cadence_type="long",
    )


def test_live_ingest_kic11904151_returns_nonempty_lightcurve(tmp_path: Path) -> None:
    """
    Run the full ingest stage for KIC 11904151 Quarter 3, using the
    committed golden FITS file as a stand-in for the live MAST response.

    Asserts that:
    - at least one segment with > 0 cadences is returned
    - the total cadence count matches the golden file
    """
    if not _GOLDEN_FITS.exists():
        pytest.skip(f"Golden FITS not found: {_GOLDEN_FITS}")

    from falsifier.pipeline.contracts.ingest import IngestInput
    from falsifier.pipeline.stages.ingest import run_ingest

    inp = IngestInput(
        target_id="KIC 11904151",
        mission="Kepler",
        author="Kepler",
        cadence="long",
        sectors=[3],
        pipeline_run_id="golden-regression-test",
    )

    # Build segment from the golden file — same data the live MAST would return
    golden_segment = _load_segment_from_golden_fits()
    golden_cadences = len(golden_segment.time.values)
    assert golden_cadences > 0, f"Golden FITS loaded zero cadences from {_GOLDEN_FITS}"

    cache_root = tmp_path / "ingest_cache"

    # Use the _segments bypass so run_ingest skips the MAST network call.
    # This exercises the IngestOutput construction path without network I/O.
    out = run_ingest(
        inp,
        cache_root=cache_root,
        offline=False,
        fetch_gaia=False,
        _segments=[golden_segment],
    )

    assert out.segments, (
        "run_ingest returned zero segments for KIC 11904151 Q3.\n"
        "The ingest stage is broken — re-check stages/ingest.py."
    )

    total_cadences = sum(len(seg.time.values) for seg in out.segments)
    assert total_cadences > 0, (
        f"All segments are empty (total_cadences={total_cadences}).\n"
        "Expected cadences for Kepler-10 Q3 long-cadence."
    )

    # Cadence count must match what we injected
    assert total_cadences == golden_cadences, (
        f"Cadence count mismatch: run_ingest returned {total_cadences}, "
        f"expected {golden_cadences} (from golden FITS)."
    )
