"""
tests/pipeline/contracts/test_retrieve.py
==========================================
Tests for RetrievalConfig, RetrievedSpectrum, RetrieveInput, RetrieveOutput.

All tests use stdlib + pydantic only — no astropy, no network.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from falsifier.pipeline.contracts.retrieve import (
    RetrievalConfig,
    RetrievedSpectrum,
    RetrieveInput,
    RetrieveOutput,
)
from falsifier.pipeline.contracts.manifest import (
    ArtifactRef,
    DatasetProvenance,
    StageManifest,
    UnitedArray,
)
import datetime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_id() -> str:
    return str(uuid.uuid4())


def _artifact_ref(stage: str = "classify") -> ArtifactRef:
    return ArtifactRef(
        path=Path("/dev/null"),
        sha256="e" * 64,
        stage=stage,
        pipeline_run_id=_run_id(),
    )


def _stage_manifest(stage: str = "retrieve") -> StageManifest:
    return StageManifest(
        stage=stage,
        code_version="0.1.0-dev",
        input_hash="f" * 64,
        wall_time_seconds=3600.0,
        provenance=[
            DatasetProvenance(
                source_doi="10.1051/0004-6361/201832922",
                access_date=datetime.date(2024, 6, 1),
                row_count=100,
                description="HITRAN opacity database subset",
            )
        ],
        artifact=_artifact_ref(stage),
    )


def _retrieval_config(**kwargs) -> RetrievalConfig:
    defaults = dict(
        retrieval_code="petitRADTRANS",
        n_live_points=500,
        chemistry_scheme="equilibrium",
        pressure_grid_levels=50,
        include_clouds=False,
    )
    defaults.update(kwargs)
    return RetrievalConfig(**defaults)


def _spectrum(n: int = 10, **kwargs) -> RetrievedSpectrum:
    wl = list(range(1, n + 1))
    defaults = dict(
        wavelength=UnitedArray(values=[float(w) for w in wl], unit="micron"),
        transit_depth=UnitedArray(values=[1000.0] * n, unit="ppm"),
        transit_depth_uncertainty=UnitedArray(values=[50.0] * n, unit="ppm"),
    )
    defaults.update(kwargs)
    return RetrievedSpectrum(**defaults)


def _retrieve_input(**kwargs) -> RetrieveInput:
    defaults = dict(
        classify_artifact=_artifact_ref("classify"),
        retrieval_config=_retrieval_config(),
        pipeline_run_id=_run_id(),
    )
    defaults.update(kwargs)
    return RetrieveInput(**defaults)


def _retrieve_output(**kwargs) -> RetrieveOutput:
    inp = _retrieve_input()
    defaults = dict(
        input=inp,
        tce_id="KIC 11904151-00",
        host_star_id="KIC 11904151",
        spectrum=_spectrum(),
        posterior_artifact=_artifact_ref("retrieve"),
        log_evidence=-123.4,
        log_evidence_uncertainty=0.3,
        wall_time_cpu_hours=2.5,
        manifest=_stage_manifest(),
        artifact=_artifact_ref("retrieve"),
    )
    defaults.update(kwargs)
    return RetrieveOutput(**defaults)


# ---------------------------------------------------------------------------
# RetrievalConfig tests
# ---------------------------------------------------------------------------

class TestRetrievalConfig:
    def test_valid_construction(self):
        cfg = _retrieval_config()
        assert cfg.n_live_points == 500
        assert cfg.retrieval_code == "petitRADTRANS"

    def test_rejects_zero_live_points(self):
        with pytest.raises(ValidationError, match="must be > 0"):
            _retrieval_config(n_live_points=0)

    def test_rejects_negative_live_points(self):
        with pytest.raises(ValidationError, match="must be > 0"):
            _retrieval_config(n_live_points=-1)

    def test_rejects_zero_pressure_levels(self):
        with pytest.raises(ValidationError, match="must be > 0"):
            _retrieval_config(pressure_grid_levels=0)

    def test_rejects_invalid_retrieval_code(self):
        with pytest.raises(ValidationError):
            _retrieval_config(retrieval_code="MCMC_code")

    def test_rejects_invalid_chemistry_scheme(self):
        with pytest.raises(ValidationError):
            _retrieval_config(chemistry_scheme="random")

    def test_chimera_and_poseidon_accepted(self):
        cfg_c = _retrieval_config(retrieval_code="CHIMERA")
        assert cfg_c.retrieval_code == "CHIMERA"
        cfg_p = _retrieval_config(retrieval_code="POSEIDON")
        assert cfg_p.retrieval_code == "POSEIDON"


# ---------------------------------------------------------------------------
# RetrievedSpectrum tests
# ---------------------------------------------------------------------------

class TestRetrievedSpectrum:
    def test_valid_spectrum(self):
        s = _spectrum(n=5)
        assert len(s.wavelength.values) == 5

    def test_rejects_wrong_wavelength_unit(self):
        wl = UnitedArray(values=[1.0, 2.0], unit="nm")
        with pytest.raises(ValidationError, match="'micron' or 'um'"):
            _spectrum(n=2, wavelength=wl)

    def test_um_unit_accepted(self):
        wl = UnitedArray(values=[1.0, 2.0], unit="um")
        s = _spectrum(n=2, wavelength=wl)
        assert s.wavelength.unit == "um"

    def test_rejects_wrong_depth_unit(self):
        td = UnitedArray(values=[0.001] * 3, unit="dimensionless")
        with pytest.raises(ValidationError, match="unit 'ppm'"):
            _spectrum(n=3, transit_depth=td)

    def test_rejects_mismatched_depth_length(self):
        with pytest.raises(ValidationError, match="transit_depth has"):
            _spectrum(
                n=5,
                transit_depth=UnitedArray(values=[1000.0, 1001.0], unit="ppm"),
            )

    def test_rejects_mismatched_uncertainty_length(self):
        with pytest.raises(ValidationError, match="transit_depth_uncertainty has"):
            _spectrum(
                n=5,
                transit_depth_uncertainty=UnitedArray(values=[50.0], unit="ppm"),
            )

    def test_json_roundtrip(self):
        s = _spectrum(n=3)
        restored = RetrievedSpectrum.model_validate_json(s.model_dump_json())
        assert restored.wavelength.values == s.wavelength.values
        assert restored.transit_depth.unit == "ppm"


# ---------------------------------------------------------------------------
# RetrieveOutput — policy guards
# ---------------------------------------------------------------------------

class TestRetrieveOutput:
    def test_valid_construction(self):
        out = _retrieve_output()
        assert out.tce_id == "KIC 11904151-00"
        assert out.log_evidence == pytest.approx(-123.4)

    def test_no_status_field(self):
        """
        RetrieveOutput must never have a 'status' field.
        Guard against regression that would introduce async handoff into the
        pipeline contract.
        """
        assert "status" not in RetrieveOutput.model_fields, (
            "RetrieveOutput must not have a 'status' field.  "
            "Job lifecycle management belongs in the API layer, not the pipeline contract."
        )

    def test_spectrum_always_present(self):
        """spectrum field must exist and must not be None."""
        out = _retrieve_output()
        assert out.spectrum is not None
        assert isinstance(out.spectrum, RetrievedSpectrum)

    def test_log_evidence_negative_accepted(self):
        """ln Z can be any real number — there is no sign restriction."""
        out = _retrieve_output(log_evidence=-500.0)
        assert out.log_evidence == pytest.approx(-500.0)

    def test_json_roundtrip(self):
        out = _retrieve_output()
        restored = RetrieveOutput.model_validate_json(out.model_dump_json())
        assert restored.tce_id == out.tce_id
        assert restored.host_star_id == out.host_star_id
        assert restored.log_evidence == pytest.approx(out.log_evidence)
        assert len(restored.spectrum.wavelength.values) == len(
            out.spectrum.wavelength.values
        )
