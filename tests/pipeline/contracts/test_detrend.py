"""
tests/pipeline/contracts/test_detrend.py
==========================================
Tests for DetrendInput, DetrendedSegment, DetrendOutput.

All tests use stdlib + pydantic only — no astropy, no network.
"""

from __future__ import annotations

import datetime
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from falsifier.pipeline.contracts.detrend import (
    DetrendInput,
    DetrendOutput,
    DetrendedSegment,
)
from falsifier.pipeline.contracts.manifest import (
    ArtifactRef,
    DatasetProvenance,
    StageManifest,
    UnitedArray,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_id() -> str:
    return str(uuid.uuid4())


def _artifact_ref(stage: str = "ingest") -> ArtifactRef:
    return ArtifactRef(
        path=Path("/dev/null"),
        sha256="a" * 64,
        stage=stage,
        pipeline_run_id=_run_id(),
    )


def _stage_manifest(stage: str = "detrend") -> StageManifest:
    return StageManifest(
        stage=stage,
        code_version="0.1.0-dev",
        input_hash="b" * 64,
        wall_time_seconds=1.0,
        provenance=[
            DatasetProvenance(
                source_doi="10.17909/t9-nmc8-f686",
                access_date=datetime.date(2024, 1, 1),
                row_count=1000,
                description="MAST light curves",
            )
        ],
        artifact=_artifact_ref(stage),
    )


def _detrend_input(**kwargs) -> DetrendInput:
    defaults = dict(
        ingest_artifact=_artifact_ref("ingest"),
        method="biweight",
        window_length=UnitedArray(values=[0.75], unit="day"),
        break_tolerance=UnitedArray(values=[0.5], unit="day"),
        pipeline_run_id=_run_id(),
    )
    defaults.update(kwargs)
    return DetrendInput(**defaults)


def _segment(n: int = 5, **kwargs) -> DetrendedSegment:
    defaults = dict(
        sector=3,
        time=UnitedArray(values=list(range(n)), unit="bkjd"),
        time_scale="tdb",
        time_format="bkjd",
        flux=UnitedArray(values=[1.0] * n, unit="dimensionless"),
        flux_err=UnitedArray(values=[0.001] * n, unit="dimensionless"),
        trend_flux=UnitedArray(values=[150000.0] * n, unit="electron / s"),
        quality_flags=[0] * n,
    )
    defaults.update(kwargs)
    return DetrendedSegment(**defaults)


def _detrend_output(**kwargs) -> DetrendOutput:
    inp = _detrend_input()
    defaults = dict(
        input=inp,
        segments=[_segment()],
        host_star_id="KIC 11904151",
        detrending_method="biweight",
        manifest=_stage_manifest(),
        artifact=_artifact_ref("detrend"),
    )
    defaults.update(kwargs)
    return DetrendOutput(**defaults)


# ---------------------------------------------------------------------------
# DetrendInput tests
# ---------------------------------------------------------------------------

class TestDetrendInput:
    def test_valid_construction(self):
        inp = _detrend_input()
        assert inp.method == "biweight"
        assert inp.window_length.values == [0.75]
        assert inp.window_length.unit == "day"

    def test_window_length_unit_d_accepted(self):
        inp = _detrend_input(window_length=UnitedArray(values=[1.0], unit="d"))
        assert inp.window_length.unit == "d"

    def test_rejects_window_length_wrong_unit(self):
        with pytest.raises(ValidationError, match="got 'hour'"):
            _detrend_input(window_length=UnitedArray(values=[1.0], unit="hour"))

    def test_rejects_multi_element_window_length(self):
        with pytest.raises(ValidationError, match="single-element"):
            _detrend_input(window_length=UnitedArray(values=[0.5, 1.0], unit="day"))

    def test_rejects_break_tolerance_wrong_unit(self):
        with pytest.raises(ValidationError, match="got 'h'"):
            _detrend_input(break_tolerance=UnitedArray(values=[0.1], unit="h"))

    def test_invalid_method_rejected(self):
        with pytest.raises(ValidationError):
            _detrend_input(method="savgol")  # not in Literal


# ---------------------------------------------------------------------------
# DetrendedSegment tests
# ---------------------------------------------------------------------------

class TestDetrendedSegment:
    def test_valid_segment(self):
        seg = _segment(n=10)
        assert seg.sector == 3
        assert seg.time_scale == "tdb"
        assert seg.time_format == "bkjd"
        assert len(seg.flux.values) == 10

    def test_time_scale_lowercased(self):
        seg = _segment(time_scale="TDB")
        assert seg.time_scale == "tdb"

    def test_time_format_lowercased(self):
        seg = _segment(time_format="BKJD")
        assert seg.time_format == "bkjd"

    def test_rejects_empty_time_scale(self):
        with pytest.raises(ValidationError, match="time_scale must be non-empty"):
            _segment(time_scale="")

    def test_rejects_whitespace_time_scale(self):
        with pytest.raises(ValidationError, match="time_scale must be non-empty"):
            _segment(time_scale="   ")

    def test_rejects_empty_time_format(self):
        with pytest.raises(ValidationError, match="time_format must be non-empty"):
            _segment(time_format="")

    def test_rejects_flux_length_mismatch(self):
        with pytest.raises(ValidationError, match="flux has"):
            _segment(n=5, flux=UnitedArray(values=[1.0, 1.0], unit="dimensionless"))

    def test_rejects_flux_err_length_mismatch(self):
        with pytest.raises(ValidationError, match="flux_err has"):
            _segment(n=5, flux_err=UnitedArray(values=[0.001] * 3, unit="dimensionless"))

    def test_rejects_trend_flux_length_mismatch(self):
        with pytest.raises(ValidationError, match="trend_flux has"):
            _segment(n=5, trend_flux=UnitedArray(values=[1.0], unit="electron / s"))

    def test_rejects_quality_flags_length_mismatch(self):
        with pytest.raises(ValidationError, match="quality_flags has"):
            _segment(n=5, quality_flags=[0, 0])

    def test_json_roundtrip(self):
        seg = _segment(n=3)
        restored = DetrendedSegment.model_validate_json(seg.model_dump_json())
        assert restored.sector == seg.sector
        assert restored.flux.values == seg.flux.values
        assert restored.time_scale == seg.time_scale


# ---------------------------------------------------------------------------
# DetrendOutput tests
# ---------------------------------------------------------------------------

class TestDetrendOutput:
    def test_valid_construction(self):
        out = _detrend_output()
        assert out.host_star_id == "KIC 11904151"
        assert out.detrending_method == "biweight"

    def test_rejects_empty_segments(self):
        with pytest.raises(ValidationError, match="at least one segment"):
            _detrend_output(segments=[])

    def test_multiple_segments_accepted(self):
        out = _detrend_output(segments=[_segment(3), _segment(4)])
        assert len(out.segments) == 2

    def test_json_roundtrip(self):
        out = _detrend_output()
        restored = DetrendOutput.model_validate_json(out.model_dump_json())
        assert restored.host_star_id == out.host_star_id
        assert restored.detrending_method == out.detrending_method
        assert len(restored.segments) == len(out.segments)
