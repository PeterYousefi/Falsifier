"""
tests/pipeline/test_io.py
==========================
Tests for falsifier.pipeline.io:

  - artifact_write → artifact_read round-trip returns equal model
  - artifact_read raises ArtifactCorruptedError when the file is tampered
  - input_hash is stable (same input → same hash across calls)
  - ArtifactCorruptedError carries path, expected, actual attributes
  - artifact_write creates parent directories if absent

All tests use stdlib + pydantic + tmp_path only — no astropy, no network.
"""

from __future__ import annotations

import datetime
import uuid
from pathlib import Path

import pytest

from falsifier.pipeline.io import (
    ArtifactCorruptedError,
    artifact_read,
    artifact_write,
    input_hash,
)
from falsifier.pipeline.contracts.manifest import (
    ArtifactRef,
    DatasetProvenance,
    StageManifest,
    UnitedArray,
)
from falsifier.pipeline.contracts.ingest import (
    IngestInput,
    IngestOutput,
    LightCurveSegment,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _run_id() -> str:
    return str(uuid.uuid4())


def _stub_artifact_ref(stage: str, run_id: str) -> ArtifactRef:
    return ArtifactRef(
        path=Path("/dev/null"),
        sha256="0" * 64,
        stage=stage,
        pipeline_run_id=run_id,
    )


def _stub_provenance() -> DatasetProvenance:
    return DatasetProvenance(
        source_doi="10.17909/t9-nmc8-f686",
        access_date=datetime.date(2024, 1, 1),
        row_count=1000,
        description="Test MAST archive",
    )


def _segment(n: int = 5) -> LightCurveSegment:
    return LightCurveSegment(
        sector=3,
        time=UnitedArray(values=[float(i) for i in range(n)], unit="bkjd"),
        time_scale="tdb",
        time_format="bkjd",
        flux=UnitedArray(values=[1.0] * n, unit="dimensionless"),
        flux_err=UnitedArray(values=[0.001] * n, unit="dimensionless"),
        quality_flags=[0] * n,
        cadence_type="long",
    )


def _ingest_output(run_id: str | None = None) -> IngestOutput:
    """Build a minimal but valid IngestOutput for io tests."""
    run_id = run_id or _run_id()
    stub_ref = _stub_artifact_ref("ingest", run_id)
    manifest = StageManifest(
        stage="ingest",
        code_version="0.1.0-dev",
        input_hash="a" * 64,
        wall_time_seconds=1.23,
        provenance=[_stub_provenance()],
        artifact=stub_ref,
    )
    return IngestOutput(
        input=IngestInput(
            target_id="KIC 11904151",
            mission="Kepler",
            author="Kepler",
            cadence="long",
            sectors=None,
            pipeline_run_id=run_id,
        ),
        segments=[_segment()],
        host_star_id="KIC 11904151",
        stellar_params=None,
        manifest=manifest,
        artifact=stub_ref,
    )


# ---------------------------------------------------------------------------
# input_hash tests
# ---------------------------------------------------------------------------

class TestInputHash:
    def test_returns_64_char_hex_string(self):
        out = _ingest_output()
        h = input_hash(out)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_stable_across_calls(self):
        """Same model instance must produce the same hash every time."""
        out = _ingest_output()
        h1 = input_hash(out)
        h2 = input_hash(out)
        assert h1 == h2

    def test_different_inputs_different_hashes(self):
        """Two different models must produce different hashes."""
        out1 = _ingest_output(run_id="run-aaa")
        out2 = _ingest_output(run_id="run-bbb")
        assert input_hash(out1) != input_hash(out2)

    def test_is_sha256_of_model_dump_json(self):
        """Verify the hash algorithm: SHA-256 of UTF-8-encoded model_dump_json."""
        import hashlib
        out = _ingest_output()
        expected = hashlib.sha256(out.model_dump_json().encode("utf-8")).hexdigest()
        assert input_hash(out) == expected


# ---------------------------------------------------------------------------
# artifact_write / artifact_read round-trip
# ---------------------------------------------------------------------------

class TestArtifactWriteRead:
    def test_roundtrip_returns_equal_model(self, tmp_path):
        """artifact_write followed by artifact_read must return an equal model."""
        out = _ingest_output()
        ref = artifact_write(out, tmp_path)

        restored = artifact_read(ref, IngestOutput)

        assert restored.host_star_id == out.host_star_id
        assert restored.input.target_id == out.input.target_id
        assert len(restored.segments) == len(out.segments)
        assert restored.manifest.stage == out.manifest.stage

    def test_writes_json_file(self, tmp_path):
        """The written file must exist and contain valid JSON."""
        import json
        out = _ingest_output()
        ref = artifact_write(out, tmp_path)

        assert ref.path.exists()
        with open(ref.path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["host_star_id"] == out.host_star_id

    def test_filename_contains_stage_and_run_id(self, tmp_path):
        """Filename must match the pattern: {stage}_{run_id}_{sha256[:8]}.json"""
        run_id = _run_id()
        out = _ingest_output(run_id=run_id)
        ref = artifact_write(out, tmp_path)

        stem = ref.path.stem
        assert stem.startswith("ingest_")
        assert run_id in stem
        assert ref.path.suffix == ".json"

    def test_artifact_ref_sha256_is_64_chars(self, tmp_path):
        out = _ingest_output()
        ref = artifact_write(out, tmp_path)
        assert len(ref.sha256) == 64

    def test_artifact_ref_stage_matches_manifest(self, tmp_path):
        out = _ingest_output()
        ref = artifact_write(out, tmp_path)
        assert ref.stage == "ingest"

    def test_creates_parent_directories(self, tmp_path):
        """artifact_write must create nested directories if they don't exist."""
        out = _ingest_output()
        nested_dir = tmp_path / "a" / "b" / "c"
        ref = artifact_write(out, nested_dir)
        assert ref.path.exists()

    def test_deterministic_filename_same_content(self, tmp_path):
        """Same input model written twice must produce the same filename."""
        run_id = _run_id()
        out = _ingest_output(run_id=run_id)
        ref1 = artifact_write(out, tmp_path / "dir1")
        ref2 = artifact_write(out, tmp_path / "dir2")
        assert ref1.path.name == ref2.path.name


# ---------------------------------------------------------------------------
# ArtifactCorruptedError
# ---------------------------------------------------------------------------

class TestArtifactCorruptedError:
    def test_raised_when_file_tampered(self, tmp_path):
        """Modifying the file after writing must trigger ArtifactCorruptedError."""
        out = _ingest_output()
        ref = artifact_write(out, tmp_path)

        # Tamper with the file
        ref.path.write_text(ref.path.read_text() + "\n# tampered", encoding="utf-8")

        with pytest.raises(ArtifactCorruptedError):
            artifact_read(ref, IngestOutput)

    def test_error_carries_path_and_hashes(self, tmp_path):
        """ArtifactCorruptedError must expose .path, .expected, .actual."""
        out = _ingest_output()
        ref = artifact_write(out, tmp_path)
        ref.path.write_bytes(b"corrupted content")

        with pytest.raises(ArtifactCorruptedError) as exc_info:
            artifact_read(ref, IngestOutput)

        err = exc_info.value
        assert err.path == ref.path
        assert err.expected == ref.sha256
        assert err.actual != ref.sha256

    def test_error_message_contains_filename(self, tmp_path):
        """Error message must name the affected file."""
        out = _ingest_output()
        ref = artifact_write(out, tmp_path)
        ref.path.write_bytes(b"x")

        with pytest.raises(ArtifactCorruptedError) as exc_info:
            artifact_read(ref, IngestOutput)

        assert ref.path.name in str(exc_info.value)

    def test_not_raised_for_valid_artifact(self, tmp_path):
        """A freshly written, unmodified artifact must read back without error."""
        out = _ingest_output()
        ref = artifact_write(out, tmp_path)
        # Should not raise
        restored = artifact_read(ref, IngestOutput)
        assert restored is not None

    def test_raised_when_sha256_ref_wrong(self, tmp_path):
        """If the ArtifactRef.sha256 is manually wrong, the read must fail."""
        out = _ingest_output()
        ref = artifact_write(out, tmp_path)

        # Build a ref with a wrong sha256 pointing to the same (correct) file
        wrong_ref = ArtifactRef(
            path=ref.path,
            sha256="b" * 64,  # wrong hash
            stage=ref.stage,
            pipeline_run_id=ref.pipeline_run_id,
        )

        with pytest.raises(ArtifactCorruptedError) as exc_info:
            artifact_read(wrong_ref, IngestOutput)

        assert exc_info.value.expected == "b" * 64
