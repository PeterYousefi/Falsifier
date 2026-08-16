"""
tests/pipeline/contracts/test_ingest_contracts.py
==================================================
Unit tests for IngestInput, LightCurveSegment, and IngestOutput contracts.
"""

import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from falsifier.pipeline.contracts.ingest import (
    IngestInput,
    IngestOutput,
    LightCurveSegment,
    StellarParams,
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

def _dummy_ref(tmp_path: Path) -> ArtifactRef:
    return ArtifactRef(
        path=tmp_path / "artifact.json",
        sha256="0" * 64,
        stage="ingest",
        pipeline_run_id="test-run",
    )


def _dummy_manifest(tmp_path: Path) -> StageManifest:
    return StageManifest(
        stage="ingest",
        code_version="0.0.0-test",
        input_hash="a" * 64,
        wall_time_seconds=0.0,
        provenance=[
            DatasetProvenance(
                source_doi="10.17909/t9-st5g-3177",
                access_date=datetime.date(2024, 1, 1),
                row_count=100,
                description="test",
            )
        ],
        artifact=_dummy_ref(tmp_path),
    )


def _minimal_segment() -> LightCurveSegment:
    """A minimal valid LightCurveSegment with all required fields."""
    n = 5
    return LightCurveSegment(
        sector=3,
        time=UnitedArray(values=list(range(n)), unit="bkjd"),
        time_scale="tdb",
        time_format="bkjd",
        flux=UnitedArray(values=[1.0] * n, unit="electron / s"),
        flux_err=UnitedArray(values=[0.01] * n, unit="electron / s"),
        quality_flags=[0] * n,
        cadence_type="long",
    )


# ---------------------------------------------------------------------------
# IngestInput
# ---------------------------------------------------------------------------

class TestIngestInput:
    def test_valid_kepler(self):
        inp = IngestInput(
            target_id="KIC 11904151",
            mission="Kepler",
            author="Kepler",
            cadence="long",
            sectors=[3],
            pipeline_run_id="run-abc",
        )
        assert inp.target_id == "KIC 11904151"

    def test_valid_tess(self):
        inp = IngestInput(
            target_id="TIC 261136679",
            mission="TESS",
            author="SPOC",
            cadence="short",
            sectors=None,
            pipeline_run_id="run-def",
        )
        assert inp.sectors is None

    def test_rejects_empty_target_id(self):
        with pytest.raises(ValidationError):
            IngestInput(
                target_id="",
                mission="Kepler",
                author="Kepler",
                cadence="long",
                pipeline_run_id="x",
            )

    def test_rejects_invalid_mission(self):
        with pytest.raises(ValidationError):
            IngestInput(
                target_id="KIC 1",
                mission="CoRoT",  # not in Literal
                author="CoRoT",
                cadence="long",
                pipeline_run_id="x",
            )

    def test_rejects_invalid_cadence(self):
        with pytest.raises(ValidationError):
            IngestInput(
                target_id="KIC 1",
                mission="Kepler",
                author="Kepler",
                cadence="ultrafast",  # not in Literal
                pipeline_run_id="x",
            )


# ---------------------------------------------------------------------------
# LightCurveSegment
# ---------------------------------------------------------------------------

class TestLightCurveSegment:
    def test_valid_segment(self):
        seg = _minimal_segment()
        assert seg.sector == 3
        assert seg.time_scale == "tdb"
        assert seg.time_format == "bkjd"

    def test_time_scale_lowercased(self):
        n = 3
        seg = LightCurveSegment(
            sector=1,
            time=UnitedArray(values=[1.0, 2.0, 3.0], unit="bkjd"),
            time_scale="TDB",   # provided upper-case
            time_format="BKJD",
            flux=UnitedArray(values=[1.0, 1.0, 1.0], unit="electron / s"),
            flux_err=UnitedArray(values=[0.01, 0.01, 0.01], unit="electron / s"),
            quality_flags=[0, 0, 0],
            cadence_type="long",
        )
        assert seg.time_scale == "tdb"   # normalised to lower
        assert seg.time_format == "bkjd"

    def test_rejects_missing_time_scale(self):
        n = 3
        with pytest.raises(ValidationError, match="time_scale"):
            LightCurveSegment(
                sector=1,
                time=UnitedArray(values=[1.0, 2.0, 3.0], unit="bkjd"),
                # time_scale omitted → ValidationError (required, no default)
                time_format="bkjd",
                flux=UnitedArray(values=[1.0, 1.0, 1.0], unit="electron / s"),
                flux_err=UnitedArray(values=[0.01, 0.01, 0.01], unit="electron / s"),
                quality_flags=[0, 0, 0],
                cadence_type="long",
            )

    def test_rejects_missing_time_format(self):
        n = 3
        with pytest.raises(ValidationError, match="time_format"):
            LightCurveSegment(
                sector=1,
                time=UnitedArray(values=[1.0, 2.0, 3.0], unit="bkjd"),
                time_scale="tdb",
                # time_format omitted → ValidationError (required, no default)
                flux=UnitedArray(values=[1.0, 1.0, 1.0], unit="electron / s"),
                flux_err=UnitedArray(values=[0.01, 0.01, 0.01], unit="electron / s"),
                quality_flags=[0, 0, 0],
                cadence_type="long",
            )

    def test_rejects_empty_time_scale(self):
        n = 3
        with pytest.raises(ValidationError, match="time_scale must be non-empty"):
            LightCurveSegment(
                sector=1,
                time=UnitedArray(values=[1.0, 2.0, 3.0], unit="bkjd"),
                time_scale="",
                time_format="bkjd",
                flux=UnitedArray(values=[1.0, 1.0, 1.0], unit="electron / s"),
                flux_err=UnitedArray(values=[0.01, 0.01, 0.01], unit="electron / s"),
                quality_flags=[0, 0, 0],
                cadence_type="long",
            )

    def test_rejects_empty_time_format(self):
        n = 3
        with pytest.raises(ValidationError, match="time_format must be non-empty"):
            LightCurveSegment(
                sector=1,
                time=UnitedArray(values=[1.0, 2.0, 3.0], unit="bkjd"),
                time_scale="tdb",
                time_format="",
                flux=UnitedArray(values=[1.0, 1.0, 1.0], unit="electron / s"),
                flux_err=UnitedArray(values=[0.01, 0.01, 0.01], unit="electron / s"),
                quality_flags=[0, 0, 0],
                cadence_type="long",
            )

    def test_rejects_length_mismatch_flux(self):
        with pytest.raises(ValidationError, match="length mismatch"):
            LightCurveSegment(
                sector=1,
                time=UnitedArray(values=[1.0, 2.0, 3.0], unit="bkjd"),
                time_scale="tdb",
                time_format="bkjd",
                flux=UnitedArray(values=[1.0, 1.0], unit="electron / s"),  # 2 ≠ 3
                flux_err=UnitedArray(values=[0.01, 0.01, 0.01], unit="electron / s"),
                quality_flags=[0, 0, 0],
                cadence_type="long",
            )

    def test_rejects_length_mismatch_quality(self):
        with pytest.raises(ValidationError, match="length mismatch"):
            LightCurveSegment(
                sector=1,
                time=UnitedArray(values=[1.0, 2.0, 3.0], unit="bkjd"),
                time_scale="tdb",
                time_format="bkjd",
                flux=UnitedArray(values=[1.0, 1.0, 1.0], unit="electron / s"),
                flux_err=UnitedArray(values=[0.01, 0.01, 0.01], unit="electron / s"),
                quality_flags=[0, 0],  # 2 ≠ 3
                cadence_type="long",
            )

    def test_to_quantity_on_time_field(self):
        import astropy.units as u
        seg = _minimal_segment()
        q = seg.time.to_quantity()
        # bkjd is not a standard astropy unit — UnitedArray stores it as a string;
        # to_quantity will work if astropy knows the unit, or we can just verify
        # the values are preserved
        assert list(q.value) == pytest.approx(list(range(5)))

    def test_tess_header_time_format(self):
        """TESS uses btjd; Kepler uses bkjd — both must be accepted."""
        n = 3
        seg = LightCurveSegment(
            sector=5,
            time=UnitedArray(values=[100.0, 101.0, 102.0], unit="btjd"),
            time_scale="tdb",
            time_format="btjd",
            flux=UnitedArray(values=[1.0, 1.0, 1.0], unit="dimensionless"),
            flux_err=UnitedArray(values=[0.001, 0.001, 0.001], unit="dimensionless"),
            quality_flags=[0, 0, 0],
            cadence_type="short",
        )
        assert seg.time_format == "btjd"
        assert seg.time.unit == "btjd"

    def test_json_roundtrip(self):
        seg = _minimal_segment()
        restored = LightCurveSegment.model_validate_json(seg.model_dump_json())
        assert restored.sector == seg.sector
        assert restored.time_scale == seg.time_scale
        assert restored.time_format == seg.time_format
        assert restored.flux.unit == seg.flux.unit


# ---------------------------------------------------------------------------
# IngestOutput
# ---------------------------------------------------------------------------

class TestIngestOutput:
    def _make_output(self, tmp_path: Path, n_segments: int = 1) -> IngestOutput:
        inp = IngestInput(
            target_id="KIC 11904151",
            mission="Kepler",
            author="Kepler",
            cadence="long",
            sectors=[3],
            pipeline_run_id="test-run",
        )
        return IngestOutput(
            input=inp,
            segments=[_minimal_segment()] * n_segments,
            host_star_id="KIC 11904151",
            manifest=_dummy_manifest(tmp_path),
            artifact=_dummy_ref(tmp_path),
        )

    def test_valid_construction(self, tmp_path):
        out = self._make_output(tmp_path)
        assert out.host_star_id == "KIC 11904151"
        assert len(out.segments) == 1

    def test_rejects_empty_segments(self, tmp_path):
        inp = IngestInput(
            target_id="KIC 11904151",
            mission="Kepler",
            author="Kepler",
            cadence="long",
            sectors=[3],
            pipeline_run_id="test-run",
        )
        with pytest.raises(ValidationError, match="at least one segment"):
            IngestOutput(
                input=inp,
                segments=[],
                host_star_id="KIC 11904151",
                manifest=_dummy_manifest(tmp_path),
                artifact=_dummy_ref(tmp_path),
            )

    def test_multiple_segments_accepted(self, tmp_path):
        out = self._make_output(tmp_path, n_segments=3)
        assert len(out.segments) == 3

    def test_json_roundtrip(self, tmp_path):
        out = self._make_output(tmp_path)
        restored = IngestOutput.model_validate_json(out.model_dump_json())
        assert restored.host_star_id == out.host_star_id
        assert len(restored.segments) == len(out.segments)
        assert restored.input.target_id == out.input.target_id
