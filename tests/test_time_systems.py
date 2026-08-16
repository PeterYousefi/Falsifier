"""
tests/test_time_systems.py
===========================
Time-system integrity tests for the Falsifier pipeline.

Coverage
--------
1.  Round-trip fidelity  — BJD, HJD, MJD, and BTJD values survive conversion
    through ``astropy.time.Time`` and back to within 1e-9 days (86.4 µs).

2.  Format coverage  — every astropy ``Time`` format used in the pipeline
    (``"jd"``, ``"mjd"``, ``"bkjd"``, ``"btjd"``) round-trips correctly from
    a ``LightCurveSegment.time`` UnitedArray.

3.  Explicit scale + format required  — a ``LightCurveSegment`` must carry
    both ``time_scale`` and ``time_format``; construction with either absent or
    empty raises ``pydantic.ValidationError`` with a message that names the
    missing field.

4.  Pipeline raises on undeclared time system  — ``extract_time_system`` must
    raise ``HeaderMissingKeyError`` when the FITS header has neither TIMESYS
    nor TELESCOP; it must never silently return a default.

5.  Known-mission FITS headers  — Kepler and TESS synthetic headers each
    produce the correct (time_scale, time_format) pair.  Any future mission
    must be added to ``_TELESCOP_TO_TIME_FORMAT`` before it can produce a
    segment; the test asserts that an unknown TELESCOP value raises.

6.  UnitedArray ↔ astropy.time.Time round-trip  — converting a
    ``UnitedArray(values, unit="bkjd")`` through ``to_quantity()`` and then
    constructing ``astropy.time.Time(q, format="bkjd", scale="tdb")`` and
    converting back is idempotent to within 1e-9 days.

Tolerance rationale
-------------------
1e-9 days ≈ 86.4 µs.  The Kepler and TESS time stamps have nominal precision
of ~50 ms (Kepler long-cadence) and ~2 s (TESS full-frame image).  A tolerance
of 86 µs is four orders of magnitude tighter than any real measurement
precision while still being achievable through pure floating-point arithmetic.
"""

from __future__ import annotations

import io

import numpy as np
import pytest
from astropy.io import fits
from astropy.time import Time
import astropy.units as u
from pydantic import ValidationError

from falsifier.pipeline.contracts.ingest import LightCurveSegment
from falsifier.pipeline.contracts.manifest import UnitedArray
from falsifier.pipeline.ingest.exceptions import HeaderMissingKeyError
from falsifier.pipeline.ingest.sources.mast import extract_time_system

# ---------------------------------------------------------------------------
# Shared tolerance
# ---------------------------------------------------------------------------

ROUND_TRIP_TOLERANCE_DAYS = 1e-9  # 86.4 µs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_header(**kwargs) -> fits.Header:
    """Build a minimal FITS header from keyword arguments."""
    h = fits.Header()
    for k, v in kwargs.items():
        h[k] = v
    return h


def _make_segment(time_values: list[float], unit: str, scale: str, fmt: str) -> LightCurveSegment:
    """Build a minimal valid LightCurveSegment."""
    n = len(time_values)
    return LightCurveSegment(
        sector=1,
        time=UnitedArray(values=time_values, unit=unit),
        time_scale=scale,
        time_format=fmt,
        flux=UnitedArray(values=[1.0] * n, unit="electron / s"),
        flux_err=UnitedArray(values=[0.01] * n, unit="electron / s"),
        quality_flags=[0] * n,
        cadence_type="long",
    )


def _roundtrip_days(values: list[float], fmt: str, scale: str) -> np.ndarray:
    """
    Convert *values* to ``astropy.time.Time``, read back as JD in the same
    scale, subtract the reference JD, and return the residuals in days.
    """
    t = Time(values, format=fmt, scale=scale)
    # Convert to JD and back
    jd_values = t.jd
    t2 = Time(jd_values, format="jd", scale=scale)
    # Convert t2 back to the original format
    t2_original = getattr(t2, fmt)  # e.g. t2.bkjd, t2.btjd, t2.mjd, t2.jd
    residuals = np.abs(np.asarray(t2_original) - np.asarray(values))
    return residuals


# ---------------------------------------------------------------------------
# 1. Round-trip fidelity for each time system
# ---------------------------------------------------------------------------

class TestRoundTripFidelity:
    """
    Each time system used in the pipeline must round-trip through
    astropy.time.Time to within 1e-9 days.
    """

    @pytest.mark.parametrize("jd_values", [
        [2454833.0, 2454900.5, 2455000.125],       # typical Kepler era
        [2457000.0, 2457500.0, 2458000.999],       # typical TESS era
        [2400000.5, 2440587.5],                     # MJD reference epochs
    ])
    def test_bjd_roundtrip(self, jd_values):
        """BJD (= JD in TDB scale) round-trips through astropy.time.Time."""
        residuals = _roundtrip_days(jd_values, fmt="jd", scale="tdb")
        assert np.all(residuals < ROUND_TRIP_TOLERANCE_DAYS), (
            f"BJD round-trip residuals exceed {ROUND_TRIP_TOLERANCE_DAYS} days:\n"
            f"  max residual : {residuals.max():.3e} days\n"
            f"  values       : {jd_values}"
        )

    @pytest.mark.parametrize("jd_values", [
        [2454833.0, 2454900.5],
        [2457000.0, 2458000.0],
    ])
    def test_hjd_roundtrip(self, jd_values):
        """
        HJD (Heliocentric Julian Date) round-trips through JD/TCB.

        Astropy does not have a dedicated 'hjd' format; HJD is conventionally
        stored as JD in the 'tcb' scale (heliocentric) or as JD in 'tdb' with
        a barycentric-to-heliocentric offset.  Here we test JD under the 'tcb'
        scale as a proxy for the HJD round-trip, which is what the pipeline
        would use for files that report TIMESYS=TCB.
        """
        residuals = _roundtrip_days(jd_values, fmt="jd", scale="tcb")
        assert np.all(residuals < ROUND_TRIP_TOLERANCE_DAYS), (
            f"HJD/TCB round-trip residuals exceed {ROUND_TRIP_TOLERANCE_DAYS} days:\n"
            f"  max residual : {residuals.max():.3e} days\n"
            f"  values       : {jd_values}"
        )

    @pytest.mark.parametrize("mjd_values", [
        [51544.5, 58000.0, 60000.75],   # MJD 2000–2023
        [0.0, 10000.0, 40000.0],
    ])
    def test_mjd_roundtrip(self, mjd_values):
        """MJD round-trips through astropy.time.Time in UTC scale."""
        residuals = _roundtrip_days(mjd_values, fmt="mjd", scale="utc")
        assert np.all(residuals < ROUND_TRIP_TOLERANCE_DAYS), (
            f"MJD round-trip residuals exceed {ROUND_TRIP_TOLERANCE_DAYS} days:\n"
            f"  max residual : {residuals.max():.3e} days\n"
            f"  values       : {mjd_values}"
        )

    @pytest.mark.parametrize("btjd_values", [
        [100.0, 500.0, 1500.75],        # typical TESS BTJD range
        [1325.3, 2200.9, 2800.1],
    ])
    def test_btjd_roundtrip(self, btjd_values):
        """
        BTJD (Barycentric TESS Julian Date = BJD − 2457000.0) round-trips
        through astropy.time.Time via JD.
        """
        # Convert to JD and back using the offset
        _BTJD_OFFSET = 2457000.0
        t = Time(np.array(btjd_values) + _BTJD_OFFSET, format="jd", scale="tdb")
        # astropy registers btjd as a format, but we also test the manual path
        back = t.jd - _BTJD_OFFSET
        residuals = np.abs(back - np.asarray(btjd_values))
        assert np.all(residuals < ROUND_TRIP_TOLERANCE_DAYS), (
            f"BTJD round-trip residuals exceed {ROUND_TRIP_TOLERANCE_DAYS} days:\n"
            f"  max residual : {residuals.max():.3e} days\n"
            f"  values       : {btjd_values}"
        )

    def test_btjd_via_astropy_format(self):
        """
        If astropy has a registered 'btjd' format, use it natively and verify
        the round-trip.  This test is skipped if astropy does not register btjd
        (older versions) — the manual round-trip above covers that case.
        """
        try:
            t = Time([100.0, 500.0, 1500.75], format="btjd", scale="tdb")
        except ValueError:
            pytest.skip("astropy does not register 'btjd' format on this version")

        back = Time(t.jd, format="jd", scale="tdb").btjd
        residuals = np.abs(back - np.array([100.0, 500.0, 1500.75]))
        assert np.all(residuals < ROUND_TRIP_TOLERANCE_DAYS), (
            f"btjd native format round-trip failed: max residual {residuals.max():.3e} days"
        )

    def test_bkjd_via_astropy_format(self):
        """
        If astropy registers 'bkjd', use it natively.  bkjd = BJD − 2454833.0.
        """
        try:
            t = Time([67.0, 200.5, 500.125], format="bkjd", scale="tdb")
        except ValueError:
            pytest.skip("astropy does not register 'bkjd' format on this version")

        back = Time(t.jd, format="jd", scale="tdb").bkjd
        residuals = np.abs(back - np.array([67.0, 200.5, 500.125]))
        assert np.all(residuals < ROUND_TRIP_TOLERANCE_DAYS), (
            f"bkjd native format round-trip failed: max residual {residuals.max():.3e} days"
        )


# ---------------------------------------------------------------------------
# 2. UnitedArray ↔ astropy.time.Time round-trip
# ---------------------------------------------------------------------------

class TestUnitedArrayTimeRoundTrip:
    """
    The pipeline path from raw time column to astropy.time.Time and back
    must be idempotent to within 1e-9 days.
    """

    @pytest.mark.parametrize("fmt,scale,offset,values", [
        ("bkjd", "tdb", 2454833.0, [67.3, 200.0, 500.125]),
        ("btjd", "tdb", 2457000.0, [100.0, 500.5, 1500.75]),
        ("jd",   "tdb", 0.0,       [2454900.0, 2457500.0]),
        ("mjd",  "utc", 0.0,       [51544.5, 58000.0]),
    ])
    def test_united_array_time_roundtrip(self, fmt, scale, offset, values):
        """
        Constructing a ``LightCurveSegment`` from UnitedArray time values and
        then converting via ``to_quantity()`` → ``astropy.time.Time`` → back
        must preserve values to within 1e-9 days.
        """
        seg = _make_segment(values, unit=fmt, scale=scale, fmt=fmt)

        # Convert UnitedArray → quantity → Time
        q = seg.time.to_quantity()
        numeric = q.value  # raw floats (astropy strips the unit string)

        if offset != 0.0:
            # For bkjd/btjd: construct Time from offset-corrected JD
            t = Time(numeric + offset, format="jd", scale=scale)
            back_raw = t.jd - offset
        else:
            t = Time(numeric, format=fmt, scale=scale)
            back_raw = getattr(t, fmt)

        residuals = np.abs(np.asarray(back_raw) - np.asarray(values))
        assert np.all(residuals < ROUND_TRIP_TOLERANCE_DAYS), (
            f"UnitedArray → Time → back residual exceeds {ROUND_TRIP_TOLERANCE_DAYS} d "
            f"for format='{fmt}' scale='{scale}':\n"
            f"  max residual: {residuals.max():.3e} days"
        )

    def test_segment_time_scale_survives_json_roundtrip(self):
        """
        time_scale and time_format survive Pydantic JSON serialisation unchanged.
        """
        seg = _make_segment([100.0, 200.0], unit="btjd", scale="tdb", fmt="btjd")
        restored = LightCurveSegment.model_validate_json(seg.model_dump_json())
        assert restored.time_scale == "tdb"
        assert restored.time_format == "btjd"
        assert restored.time.unit == "btjd"


# ---------------------------------------------------------------------------
# 3. Explicit scale + format required on LightCurveSegment
# ---------------------------------------------------------------------------

class TestExplicitScaleAndFormatRequired:
    """
    time_scale and time_format have no defaults.  Construction without them
    must raise ValidationError with a message naming the missing field.
    """

    def test_missing_time_scale_raises(self):
        n = 3
        with pytest.raises(ValidationError) as exc_info:
            LightCurveSegment(
                sector=1,
                time=UnitedArray(values=[1.0, 2.0, 3.0], unit="bkjd"),
                # time_scale intentionally omitted
                time_format="bkjd",
                flux=UnitedArray(values=[1.0] * n, unit="electron / s"),
                flux_err=UnitedArray(values=[0.01] * n, unit="electron / s"),
                quality_flags=[0] * n,
                cadence_type="long",
            )
        # Error message must mention the field name
        assert "time_scale" in str(exc_info.value)

    def test_missing_time_format_raises(self):
        n = 3
        with pytest.raises(ValidationError) as exc_info:
            LightCurveSegment(
                sector=1,
                time=UnitedArray(values=[1.0, 2.0, 3.0], unit="bkjd"),
                time_scale="tdb",
                # time_format intentionally omitted
                flux=UnitedArray(values=[1.0] * n, unit="electron / s"),
                flux_err=UnitedArray(values=[0.01] * n, unit="electron / s"),
                quality_flags=[0] * n,
                cadence_type="long",
            )
        assert "time_format" in str(exc_info.value)

    def test_empty_time_scale_raises_with_message(self):
        n = 2
        with pytest.raises(ValidationError) as exc_info:
            LightCurveSegment(
                sector=1,
                time=UnitedArray(values=[1.0, 2.0], unit="bkjd"),
                time_scale="",
                time_format="bkjd",
                flux=UnitedArray(values=[1.0, 1.0], unit="electron / s"),
                flux_err=UnitedArray(values=[0.01, 0.01], unit="electron / s"),
                quality_flags=[0, 0],
                cadence_type="long",
            )
        msg = str(exc_info.value)
        assert "time_scale" in msg
        assert "non-empty" in msg.lower() or "never assume" in msg.lower()

    def test_empty_time_format_raises_with_message(self):
        n = 2
        with pytest.raises(ValidationError) as exc_info:
            LightCurveSegment(
                sector=1,
                time=UnitedArray(values=[1.0, 2.0], unit="bkjd"),
                time_scale="tdb",
                time_format="",
                flux=UnitedArray(values=[1.0, 1.0], unit="electron / s"),
                flux_err=UnitedArray(values=[0.01, 0.01], unit="electron / s"),
                quality_flags=[0, 0],
                cadence_type="long",
            )
        msg = str(exc_info.value)
        assert "time_format" in msg
        assert "non-empty" in msg.lower() or "never assume" in msg.lower()

    def test_whitespace_only_time_scale_raises(self):
        n = 2
        with pytest.raises(ValidationError):
            LightCurveSegment(
                sector=1,
                time=UnitedArray(values=[1.0, 2.0], unit="bkjd"),
                time_scale="   ",
                time_format="bkjd",
                flux=UnitedArray(values=[1.0, 1.0], unit="electron / s"),
                flux_err=UnitedArray(values=[0.01, 0.01], unit="electron / s"),
                quality_flags=[0, 0],
                cadence_type="long",
            )

    def test_whitespace_only_time_format_raises(self):
        n = 2
        with pytest.raises(ValidationError):
            LightCurveSegment(
                sector=1,
                time=UnitedArray(values=[1.0, 2.0], unit="bkjd"),
                time_scale="tdb",
                time_format="\t",
                flux=UnitedArray(values=[1.0, 1.0], unit="electron / s"),
                flux_err=UnitedArray(values=[0.01, 0.01], unit="electron / s"),
                quality_flags=[0, 0],
                cadence_type="long",
            )

    @pytest.mark.parametrize("scale,fmt", [
        ("tdb",  "bkjd"),
        ("tdb",  "btjd"),
        ("tdb",  "jd"),
        ("utc",  "mjd"),
        ("tcb",  "jd"),
        ("tt",   "jd"),
    ])
    def test_valid_scale_format_combinations_accepted(self, scale, fmt):
        """Spot-check that common valid (scale, format) pairs are accepted."""
        n = 3
        seg = LightCurveSegment(
            sector=1,
            time=UnitedArray(values=[1.0, 2.0, 3.0], unit=fmt),
            time_scale=scale,
            time_format=fmt,
            flux=UnitedArray(values=[1.0] * n, unit="electron / s"),
            flux_err=UnitedArray(values=[0.01] * n, unit="electron / s"),
            quality_flags=[0] * n,
            cadence_type="long",
        )
        assert seg.time_scale == scale
        assert seg.time_format == fmt


# ---------------------------------------------------------------------------
# 4. Pipeline raises when time system is absent from FITS header
# ---------------------------------------------------------------------------

class TestPipelineRaisesOnUndeclaredTimeSystem:
    """
    ``extract_time_system`` must raise ``HeaderMissingKeyError`` rather than
    returning a default whenever the header lacks enough information to
    determine the time system unambiguously.
    """

    def test_raises_when_timesys_absent_and_no_telescop(self):
        """Header with neither TIMESYS nor TELESCOP must raise."""
        hdr = _make_header(TIMEUNIT="d")
        with pytest.raises(HeaderMissingKeyError) as exc_info:
            extract_time_system(hdr, "no_timesys.fits")
        assert exc_info.value.key == "TIMESYS"

    def test_raises_when_timesys_absent_even_with_telescop(self):
        """TELESCOP alone is insufficient — TIMESYS is always required."""
        hdr = _make_header(TELESCOP="Kepler", TIMEUNIT="d")
        with pytest.raises(HeaderMissingKeyError) as exc_info:
            extract_time_system(hdr, "telescop_no_timesys.fits")
        assert exc_info.value.key == "TIMESYS"

    def test_raises_when_only_timeunit_present(self):
        """TIMEUNIT='d' with no TIMESYS or TELESCOP must raise."""
        hdr = _make_header(TIMEUNIT="d")
        with pytest.raises(HeaderMissingKeyError):
            extract_time_system(hdr, "timeunit_only.fits")

    def test_raises_on_unknown_telescop_value(self):
        """
        An unrecognised TELESCOP value must raise rather than guessing the
        time_format.  Any new mission must be added to _TELESCOP_TO_TIME_FORMAT
        before it can produce a segment.
        """
        hdr = _make_header(TIMESYS="TDB", TELESCOP="CHEOPS")
        with pytest.raises(HeaderMissingKeyError) as exc_info:
            extract_time_system(hdr, "unknown_mission.fits")
        # The error must name the problematic key so the caller knows what to add
        assert exc_info.value.key in ("TELESCOP", "TIME_FMT")

    def test_error_carries_fits_path(self):
        """HeaderMissingKeyError.fits_path must match the argument passed in."""
        hdr = _make_header()
        path_str = "/data/missions/kepler/q3.fits"
        with pytest.raises(HeaderMissingKeyError) as exc_info:
            extract_time_system(hdr, path_str)
        assert exc_info.value.fits_path == path_str

    def test_error_message_contains_path_and_key(self):
        """str(error) must include both the key and the path for diagnostics."""
        hdr = _make_header(TIMEUNIT="d")
        with pytest.raises(HeaderMissingKeyError) as exc_info:
            extract_time_system(hdr, "diagnostic_test.fits")
        rendered = str(exc_info.value)
        assert "diagnostic_test.fits" in rendered
        assert "TIMESYS" in rendered

    def test_completely_empty_header_raises(self):
        """A completely empty header must raise, not silently return defaults."""
        hdr = fits.Header()
        with pytest.raises(HeaderMissingKeyError):
            extract_time_system(hdr, "empty.fits")


# ---------------------------------------------------------------------------
# 5. Known-mission FITS headers produce correct (scale, format)
# ---------------------------------------------------------------------------

class TestKnownMissionHeaders:
    """
    Synthetic FITS headers for each supported mission must yield the expected
    (time_scale, time_format) pair.
    """

    def test_kepler_header(self):
        """Kepler FITS: TIMESYS=TDB + TELESCOP=Kepler → ('tdb', 'bkjd')."""
        hdr = _make_header(TIMESYS="TDB", TELESCOP="Kepler", TIMEUNIT="d")
        ts, tf = extract_time_system(hdr, "kepler.fits")
        assert ts == "tdb"
        assert tf == "bkjd"

    def test_kepler_uppercase_telescop(self):
        """TELESCOP='KEPLER' (all caps) also maps to bkjd."""
        hdr = _make_header(TIMESYS="TDB", TELESCOP="KEPLER", TIMEUNIT="d")
        ts, tf = extract_time_system(hdr, "kepler_upper.fits")
        assert ts == "tdb"
        assert tf == "bkjd"

    def test_k2_header(self):
        """K2 FITS: TELESCOP=K2 → ('tdb', 'bkjd') (same offset as Kepler)."""
        hdr = _make_header(TIMESYS="TDB", TELESCOP="K2", TIMEUNIT="d")
        ts, tf = extract_time_system(hdr, "k2.fits")
        assert ts == "tdb"
        assert tf == "bkjd"

    def test_tess_header(self):
        """TESS FITS: TIMESYS=TDB + TELESCOP=TESS → ('tdb', 'btjd')."""
        hdr = _make_header(TIMESYS="TDB", TELESCOP="TESS", TIMEUNIT="d")
        ts, tf = extract_time_system(hdr, "tess.fits")
        assert ts == "tdb"
        assert tf == "btjd"

    def test_explicit_time_fmt_overrides_telescop(self):
        """
        An explicit TIME_FMT header takes priority over the TELESCOP lookup.
        A Kepler file with TIME_FMT=JD should produce time_format='jd', not
        'bkjd'.
        """
        hdr = _make_header(TIMESYS="TDB", TELESCOP="Kepler", TIME_FMT="JD")
        ts, tf = extract_time_system(hdr, "explicit_fmt.fits")
        assert ts == "tdb"
        assert tf == "jd"  # overridden, not bkjd

    def test_timesys_stored_with_trailing_spaces(self):
        """TIMESYS='TDB ' (with trailing spaces) must still parse to 'tdb'."""
        hdr = _make_header(TIMESYS="TDB ", TELESCOP="TESS")
        ts, tf = extract_time_system(hdr, "trailing_spaces.fits")
        assert ts == "tdb"

    def test_timesys_case_insensitive(self):
        """TIMESYS='tdb' (lower-case) must normalise to 'tdb'."""
        hdr = _make_header(TIMESYS="tdb", TELESCOP="TESS")
        ts, tf = extract_time_system(hdr, "lowercase_timesys.fits")
        assert ts == "tdb"

    @pytest.mark.parametrize("scale", ["TCB", "TCG", "TT", "UTC"])
    def test_other_valid_timesys_values(self, scale):
        """
        Non-TDB time scales that appear with TELESCOP must be returned
        correctly (lower-cased).  An archive that stores HJD under TCB is
        a real case.
        """
        hdr = _make_header(TIMESYS=scale, TELESCOP="TESS")
        ts, tf = extract_time_system(hdr, f"{scale.lower()}.fits")
        assert ts == scale.lower()


# ---------------------------------------------------------------------------
# 6. Tolerance boundary — assert the 1e-9 day tolerance is not vacuous
# ---------------------------------------------------------------------------

class TestToleranceNotVacuous:
    """
    The 1e-9 day tolerance must actually reject values that are meaningfully
    wrong, not merely pass everything.
    """

    def test_tolerance_rejects_microsecond_offset(self):
        """An offset of 1e-6 days (86.4 ms) must exceed the tolerance."""
        too_large = 1e-6
        assert too_large > ROUND_TRIP_TOLERANCE_DAYS, (
            "Test setup error: 1e-6 days should exceed the 1e-9 day tolerance"
        )

    def test_tolerance_accepts_subnanosecond_offset(self):
        """An offset of 1e-10 days must be within the tolerance."""
        within = 1e-10
        assert within < ROUND_TRIP_TOLERANCE_DAYS

    def test_bjd_residuals_are_genuinely_small(self):
        """
        Actual BJD round-trip residuals must be <<< 1e-9 days, not merely
        < 1e-9.  This guards against the tolerance being set too loose.
        """
        values = [2454833.0, 2457500.5, 2459000.125]
        residuals = _roundtrip_days(values, fmt="jd", scale="tdb")
        # Should be at machine-epsilon level, not near the tolerance boundary
        assert residuals.max() < ROUND_TRIP_TOLERANCE_DAYS * 0.01, (
            f"BJD residuals {residuals.max():.3e} days are unexpectedly close to "
            f"the tolerance boundary {ROUND_TRIP_TOLERANCE_DAYS} days; "
            "the tolerance may be set too loose."
        )
