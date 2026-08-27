"""
Regression test: live ingest path for KIC 11904151 (Kepler-10)
===============================================================

This test exercises the *real* ``_fetch_lightcurves`` → ``fetch_lightcurve``
→ ``lc.download()`` → ``_segments_to_fits_bytes`` → ``cache.put()`` →
``_fits_to_segments`` round-trip against the live MAST archive.

It is intentionally NOT marked ``@pytest.mark.no_network`` — it requires
a working internet connection and a reachable MAST endpoint.  It must be
skipped in CI environments that block outbound connections; add
``-m "not live_network"`` to the pytest invocation in those cases.

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

import datetime
import tempfile
from pathlib import Path

import pytest

# Mark so callers can skip with: pytest -m "not live_network"
pytestmark = [
    pytest.mark.live_network,
    pytest.mark.requires_astropy,
    pytest.mark.timeout(120),  # generous: MAST can be slow
]


def test_live_ingest_kic11904151_returns_nonempty_lightcurve(tmp_path: Path) -> None:
    """
    Run the full ingest stage against the live MAST archive for KIC 11904151,
    Quarter 3.  Assert that at least one segment with > 0 cadences is returned.

    Uses ``sectors=[3]`` (Quarter 3) so the request is bounded — identical
    parameters to the control call in the bug report.
    """
    from falsifier.pipeline.contracts.ingest import IngestInput
    from falsifier.pipeline.stages.ingest import run_ingest

    inp = IngestInput(
        target_id="KIC 11904151",
        mission="Kepler",
        author="Kepler",
        cadence="long",
        sectors=[3],
        pipeline_run_id="live-regression-test",
    )

    cache_root = tmp_path / "ingest_cache"

    out = run_ingest(inp, cache_root=cache_root, offline=False, fetch_gaia=False)

    assert out.segments, (
        "run_ingest returned zero segments for KIC 11904151 Q3.\n"
        "The live MAST ingest path is broken — re-check mast.py, cache.py, "
        "and stages/ingest.py."
    )

    total_cadences = sum(len(seg.time.values) for seg in out.segments)
    assert total_cadences > 0, (
        f"All segments are empty (total_cadences={total_cadences}).\n"
        "Expected ~4140 cadences for Kepler-10 Q3 long-cadence."
    )

    # Verify the cache was written and can be round-tripped
    from falsifier.pipeline.stages.ingest import _mast_cache_query, _fits_to_segments
    from falsifier.pipeline.ingest.cache import IngestCache

    cache = IngestCache(cache_root)
    hit = cache.get(_mast_cache_query(inp), ".fits")
    assert hit is not None, (
        "Cache was not populated after a successful live fetch.\n"
        "cache.put() may have failed silently."
    )

    cached_path, cached_manifest, _ = hit
    assert cached_path.stat().st_size > 0, (
        f"Cached FITS file is zero bytes: {cached_path}\n"
        "The atomic write (FIX 3) may not have completed correctly."
    )

    round_trip_segments = _fits_to_segments(cached_path, inp)
    assert round_trip_segments, (
        "Cached FITS round-trips to zero segments.\n"
        "_segments_to_fits_bytes / _fits_to_segments is broken."
    )

    rt_cadences = sum(len(s.time.values) for s in round_trip_segments)
    assert rt_cadences == total_cadences, (
        f"Round-trip cadence count mismatch: original={total_cadences} "
        f"cached={rt_cadences}.\n"
        "The FITS serialisation round-trip is lossy."
    )
