"""
tests/pipeline/contracts/test_disequilibrium.py
=================================================
Tests for FastChemConfig, ChemicalSpeciesProfile, GibbsMinimisationResult,
DisequilibriumInput, DisequilibriumOutput.

Policy anchor: DisequilibriumOutput must have no ``disposition`` field and
its ``overall_disequilibrium_score`` is a screening metric only — not a
biosignature claim.

All tests use stdlib + pydantic only — no astropy, no network.
"""

from __future__ import annotations

import datetime
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from falsifier.pipeline.contracts.disequilibrium import (
    ChemicalSpeciesProfile,
    DisequilibriumInput,
    DisequilibriumOutput,
    FastChemConfig,
    GibbsMinimisationResult,
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


def _artifact_ref(stage: str = "retrieve") -> ArtifactRef:
    return ArtifactRef(
        path=Path("/dev/null"),
        sha256="9" * 64,
        stage=stage,
        pipeline_run_id=_run_id(),
    )


def _stage_manifest(stage: str = "disequilibrium") -> StageManifest:
    return StageManifest(
        stage=stage,
        code_version="0.1.0-dev",
        input_hash="0" * 64,
        wall_time_seconds=120.0,
        provenance=[
            DatasetProvenance(
                source_doi="10.1051/0004-6361/201834400",
                access_date=datetime.date(2024, 3, 1),
                row_count=500,
                description="FastChem opacity tables",
            )
        ],
        artifact=_artifact_ref(stage),
    )


def _fastchem_config(species: list[str] | None = None, **kwargs) -> FastChemConfig:
    defaults = dict(
        temperature_pressure_profile_source="retrieval",
        included_species=species or ["H2O", "CO2", "CH4"],
        metallicity_solar=1.0,
        c_to_o_ratio=0.55,
    )
    defaults.update(kwargs)
    return FastChemConfig(**defaults)


def _species_profile(species: str = "H2O", n: int = 5, **kwargs) -> ChemicalSpeciesProfile:
    defaults = dict(
        species=species,
        vmr_profile=UnitedArray(values=[1e-3] * n, unit="dimensionless"),
        pressure=UnitedArray(values=[float(i + 1) for i in range(n)], unit="bar"),
        equilibrium_vmr_profile=UnitedArray(values=[1e-3] * n, unit="dimensionless"),
        disequilibrium_metric=0.1,
    )
    defaults.update(kwargs)
    return ChemicalSpeciesProfile(**defaults)


def _gibbs_result(**kwargs) -> GibbsMinimisationResult:
    defaults = dict(
        temperature=UnitedArray(values=[1200.0], unit="K"),
        pressure=UnitedArray(values=[0.1], unit="bar"),
        species_fractions={"H2O": 0.001, "N2": 0.999},
        gibbs_free_energy=UnitedArray(values=[-120000.0], unit="J / mol"),
    )
    defaults.update(kwargs)
    return GibbsMinimisationResult(**defaults)


def _disq_input(species: list[str] | None = None, **kwargs) -> DisequilibriumInput:
    sp = species or ["H2O", "CO2", "CH4"]
    defaults = dict(
        retrieve_artifact=_artifact_ref("retrieve"),
        planet_name="TRAPPIST-1 b",
        planet_doi="10.1038/s41586-021-03394-8",
        fastchem_config=_fastchem_config(species=sp),
        pipeline_run_id=_run_id(),
    )
    defaults.update(kwargs)
    return DisequilibriumInput(**defaults)


def _disq_output(species: list[str] | None = None, **kwargs) -> DisequilibriumOutput:
    sp = species or ["H2O", "CO2", "CH4"]
    inp = _disq_input(species=sp)
    profiles = [_species_profile(s) for s in sp]
    defaults = dict(
        input=inp,
        planet_name="TRAPPIST-1 b",
        host_star_id="TRAPPIST-1",
        species_profiles=profiles,
        gibbs_results=[_gibbs_result()],
        overall_disequilibrium_score=0.1,
        manifest=_stage_manifest(),
        artifact=_artifact_ref("disequilibrium"),
    )
    defaults.update(kwargs)
    return DisequilibriumOutput(**defaults)


# ---------------------------------------------------------------------------
# FastChemConfig tests
# ---------------------------------------------------------------------------

class TestFastChemConfig:
    def test_valid_construction(self):
        cfg = _fastchem_config()
        assert cfg.included_species == ["H2O", "CO2", "CH4"]
        assert cfg.c_to_o_ratio == pytest.approx(0.55)

    def test_rejects_empty_species_list(self):
        with pytest.raises(ValidationError, match="at least one species"):
            _fastchem_config(species=[])

    def test_rejects_zero_c_to_o(self):
        with pytest.raises(ValidationError, match="c_to_o_ratio must be > 0"):
            _fastchem_config(c_to_o_ratio=0.0)

    def test_rejects_negative_c_to_o(self):
        with pytest.raises(ValidationError, match="c_to_o_ratio must be > 0"):
            _fastchem_config(c_to_o_ratio=-0.1)

    def test_rejects_invalid_tp_source(self):
        with pytest.raises(ValidationError, match="must be one of"):
            _fastchem_config(temperature_pressure_profile_source="empirical")

    def test_gcm_and_parametric_accepted(self):
        cfg_g = _fastchem_config(temperature_pressure_profile_source="gcm")
        assert cfg_g.temperature_pressure_profile_source == "gcm"
        cfg_p = _fastchem_config(temperature_pressure_profile_source="parametric")
        assert cfg_p.temperature_pressure_profile_source == "parametric"


# ---------------------------------------------------------------------------
# ChemicalSpeciesProfile tests
# ---------------------------------------------------------------------------

class TestChemicalSpeciesProfile:
    def test_valid_construction(self):
        p = _species_profile("H2O", n=10)
        assert p.species == "H2O"
        assert p.disequilibrium_metric == pytest.approx(0.1)

    def test_rejects_negative_metric(self):
        with pytest.raises(ValidationError, match="must be >= 0.0"):
            _species_profile(disequilibrium_metric=-0.01)

    def test_zero_metric_accepted(self):
        p = _species_profile(disequilibrium_metric=0.0)
        assert p.disequilibrium_metric == 0.0

    def test_rejects_wrong_pressure_unit(self):
        with pytest.raises(ValidationError, match="unit must be 'bar'"):
            _species_profile(n=3, pressure=UnitedArray(values=[1.0, 2.0, 3.0], unit="Pa"))

    def test_rejects_wrong_vmr_unit(self):
        with pytest.raises(ValidationError, match="unit 'dimensionless'"):
            _species_profile(n=3, vmr_profile=UnitedArray(values=[1.0, 1.0, 1.0], unit="ppm"))

    def test_rejects_vmr_length_mismatch(self):
        with pytest.raises(ValidationError, match="vmr_profile has"):
            _species_profile(
                n=5,
                vmr_profile=UnitedArray(values=[1e-3, 2e-3], unit="dimensionless"),
            )

    def test_rejects_equilibrium_vmr_length_mismatch(self):
        with pytest.raises(ValidationError, match="equilibrium_vmr_profile has"):
            _species_profile(
                n=5,
                equilibrium_vmr_profile=UnitedArray(values=[1e-3], unit="dimensionless"),
            )

    def test_json_roundtrip(self):
        p = _species_profile("CH4", n=4)
        restored = ChemicalSpeciesProfile.model_validate_json(p.model_dump_json())
        assert restored.species == "CH4"
        assert restored.disequilibrium_metric == pytest.approx(p.disequilibrium_metric)


# ---------------------------------------------------------------------------
# GibbsMinimisationResult tests
# ---------------------------------------------------------------------------

class TestGibbsMinimisationResult:
    def test_valid_construction(self):
        g = _gibbs_result()
        assert g.temperature.values == [1200.0]
        assert g.pressure.unit == "bar"
        assert g.gibbs_free_energy.unit == "J / mol"

    def test_rejects_wrong_temperature_unit(self):
        with pytest.raises(ValidationError, match="unit must be 'K'"):
            _gibbs_result(temperature=UnitedArray(values=[1200.0], unit="Celsius"))

    def test_rejects_multi_element_temperature(self):
        with pytest.raises(ValidationError, match="single-element"):
            _gibbs_result(temperature=UnitedArray(values=[1200.0, 1300.0], unit="K"))

    def test_rejects_wrong_pressure_unit(self):
        with pytest.raises(ValidationError, match="unit must be 'bar'"):
            _gibbs_result(pressure=UnitedArray(values=[0.1], unit="Pa"))

    def test_rejects_wrong_gibbs_unit(self):
        with pytest.raises(ValidationError, match="unit must be 'J / mol'"):
            _gibbs_result(gibbs_free_energy=UnitedArray(values=[-120000.0], unit="kJ / mol"))

    def test_json_roundtrip(self):
        g = _gibbs_result()
        restored = GibbsMinimisationResult.model_validate_json(g.model_dump_json())
        assert restored.temperature.values == [1200.0]


# ---------------------------------------------------------------------------
# DisequilibriumOutput — policy guards
# ---------------------------------------------------------------------------

class TestDisequilibriumOutput:
    def test_valid_construction(self):
        out = _disq_output()
        assert out.planet_name == "TRAPPIST-1 b"
        assert len(out.species_profiles) == 3

    def test_no_disposition_field(self):
        """
        DisequilibriumOutput must never have a 'disposition' field.
        This stage is a screening tool, not a candidate classifier.
        AGENTS.md Locked Claim: not a biosignature detector.
        """
        assert "disposition" not in DisequilibriumOutput.model_fields, (
            "DisequilibriumOutput must not have a 'disposition' field.  "
            "This stage is a thermochemical screening tool only."
        )

    def test_rejects_species_count_mismatch(self):
        """species_profiles must have same length as included_species."""
        inp = _disq_input(species=["H2O", "CO2", "CH4"])
        with pytest.raises(ValidationError, match="species_profiles has"):
            DisequilibriumOutput(
                input=inp,
                planet_name="TRAPPIST-1 b",
                host_star_id="TRAPPIST-1",
                species_profiles=[_species_profile("H2O")],  # only 1, need 3
                gibbs_results=[_gibbs_result()],
                overall_disequilibrium_score=0.1,
                manifest=_stage_manifest(),
                artifact=_artifact_ref("disequilibrium"),
            )

    def test_rejects_negative_overall_score(self):
        with pytest.raises(ValidationError, match="overall_disequilibrium_score must be >= 0"):
            _disq_output(overall_disequilibrium_score=-0.1)

    def test_rejects_negative_metric_in_profile(self):
        """
        ChemicalSpeciesProfile rejects a negative disequilibrium_metric at construction.
        The contract-level guard is in the inner model, not in DisequilibriumOutput.
        """
        with pytest.raises(ValidationError, match="must be >= 0.0"):
            _species_profile("H2O", disequilibrium_metric=-1.0)

    def test_json_roundtrip(self):
        out = _disq_output()
        restored = DisequilibriumOutput.model_validate_json(out.model_dump_json())
        assert restored.planet_name == out.planet_name
        assert restored.overall_disequilibrium_score == pytest.approx(
            out.overall_disequilibrium_score
        )
        assert len(restored.species_profiles) == len(out.species_profiles)

    def test_overall_score_is_screening_metric_not_biosignature(self):
        """
        Docstring-level assertion: the field description must explicitly state
        that overall_disequilibrium_score is a screening metric only.
        """
        field_info = DisequilibriumOutput.model_fields["overall_disequilibrium_score"]
        description = field_info.description or ""
        assert "Screening metric" in description or "screening metric" in description, (
            "overall_disequilibrium_score field description must state it is a "
            "screening metric only, not a biosignature claim."
        )
