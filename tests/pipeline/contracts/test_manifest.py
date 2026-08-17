"""
tests/pipeline/contracts/test_manifest.py
==========================================
Unit tests for the shared manifest contracts:
  UnitedArray, DatasetProvenance, ArtifactRef, StageManifest.
"""

import datetime
from pathlib import Path

import pytest

from falsifier.pipeline.contracts.manifest import (
    ArtifactRef,
    DatasetProvenance,
    StageManifest,
    UnitedArray,
)


# ---------------------------------------------------------------------------
# UnitedArray
# ---------------------------------------------------------------------------

class TestUnitedArray:
    def test_to_quantity_returns_correct_unit(self):
        u = pytest.importorskip("astropy.units")
        ua = UnitedArray(values=[1.0, 2.0, 3.0], unit="day")
        q = ua.to_quantity()
        assert q.unit == u.day
        assert list(q.value) == pytest.approx([1.0, 2.0, 3.0])

    def test_from_quantity_roundtrip(self):
        u = pytest.importorskip("astropy.units")
        import numpy as np
        q = np.array([10.0, 20.0]) * u.ppm
        ua = UnitedArray.from_quantity(q)
        assert ua.unit == "ppm"
        assert ua.values == pytest.approx([10.0, 20.0])

    def test_to_quantity_from_quantity_roundtrip(self):
        pytest.importorskip("astropy.units")
        ua = UnitedArray(values=[3.14, 2.72], unit="electron / s")
        q = ua.to_quantity()
        ua2 = UnitedArray.from_quantity(q)
        assert ua2.values == pytest.approx(ua.values)

    def test_rejects_empty_values(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="at least one element"):
            UnitedArray(values=[], unit="day")

    def test_rejects_empty_unit(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="non-empty string"):
            UnitedArray(values=[1.0], unit="")

    def test_rejects_whitespace_only_unit(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="non-empty string"):
            UnitedArray(values=[1.0], unit="   ")

    def test_json_roundtrip(self):
        ua = UnitedArray(values=[0.5, 1.5], unit="ppm")
        restored = UnitedArray.model_validate_json(ua.model_dump_json())
        assert restored.values == pytest.approx(ua.values)
        assert restored.unit == ua.unit

    def test_dimensionless_unit_accepted(self):
        u = pytest.importorskip("astropy.units")
        ua = UnitedArray(values=[1.0], unit="dimensionless")
        q = ua.to_quantity()
        assert q.unit == u.dimensionless_unscaled


# ---------------------------------------------------------------------------
# DatasetProvenance
# ---------------------------------------------------------------------------

class TestDatasetProvenance:
    def _valid(self, **overrides):
        defaults = dict(
            source_doi="10.1234/test",
            access_date=datetime.date(2024, 6, 1),
            row_count=100,
            description="test dataset",
        )
        defaults.update(overrides)
        return DatasetProvenance(**defaults)

    def test_valid_construction(self):
        prov = self._valid()
        assert prov.source_doi == "10.1234/test"
        assert prov.row_count == 100

    def test_rejects_empty_doi(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="source_doi must be non-empty"):
            self._valid(source_doi="")

    def test_rejects_whitespace_doi(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="source_doi must be non-empty"):
            self._valid(source_doi="   ")

    def test_rejects_zero_row_count(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="row_count must be >= 1"):
            self._valid(row_count=0)

    def test_rejects_negative_row_count(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="row_count must be >= 1"):
            self._valid(row_count=-5)

    def test_json_roundtrip(self):
        prov = self._valid()
        restored = DatasetProvenance.model_validate_json(prov.model_dump_json())
        assert restored.source_doi == prov.source_doi
        assert restored.access_date == prov.access_date
        assert restored.row_count == prov.row_count


# ---------------------------------------------------------------------------
# ArtifactRef
# ---------------------------------------------------------------------------

class TestArtifactRef:
    def test_construction(self, tmp_path):
        ref = ArtifactRef(
            path=tmp_path / "out.json",
            sha256="a" * 64,
            stage="ingest",
            pipeline_run_id="run-001",
        )
        assert ref.stage == "ingest"

    def test_json_roundtrip(self, tmp_path):
        ref = ArtifactRef(
            path=tmp_path / "out.json",
            sha256="b" * 64,
            stage="detrend",
            pipeline_run_id="run-002",
        )
        restored = ArtifactRef.model_validate_json(ref.model_dump_json())
        assert restored.stage == ref.stage
        assert restored.sha256 == ref.sha256


# ---------------------------------------------------------------------------
# StageManifest
# ---------------------------------------------------------------------------

class TestStageManifest:
    def _make(self, tmp_path) -> StageManifest:
        ref = ArtifactRef(
            path=tmp_path / "artifact.json",
            sha256="c" * 64,
            stage="ingest",
            pipeline_run_id="run-003",
        )
        prov = DatasetProvenance(
            source_doi="10.5555/test",
            access_date=datetime.date(2024, 1, 15),
            row_count=42,
            description="test",
        )
        return StageManifest(
            stage="ingest",
            code_version="0.1.0-dev",
            input_hash="d" * 64,
            wall_time_seconds=1.23,
            provenance=[prov],
            artifact=ref,
        )

    def test_valid_construction(self, tmp_path):
        m = self._make(tmp_path)
        assert m.stage == "ingest"
        assert len(m.provenance) == 1

    def test_json_roundtrip(self, tmp_path):
        m = self._make(tmp_path)
        restored = StageManifest.model_validate_json(m.model_dump_json())
        assert restored.stage == m.stage
        assert restored.code_version == m.code_version
        assert restored.input_hash == m.input_hash
        assert restored.wall_time_seconds == pytest.approx(m.wall_time_seconds)
        assert len(restored.provenance) == 1
        assert restored.provenance[0].source_doi == m.provenance[0].source_doi

    def test_empty_provenance_accepted(self, tmp_path):
        """Pure-compute stages may have no provenance entries."""
        ref = ArtifactRef(
            path=tmp_path / "x.json",
            sha256="e" * 64,
            stage="classify",
            pipeline_run_id="run-004",
        )
        m = StageManifest(
            stage="classify",
            code_version="0.1.0-dev",
            input_hash="f" * 64,
            wall_time_seconds=0.5,
            provenance=[],
            artifact=ref,
        )
        assert m.provenance == []
