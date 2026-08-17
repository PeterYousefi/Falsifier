"""
tests/test_retrieve_screen.py
==============================
Contract and unit tests for the retrieve and disequilibrium stage contracts.

All tests run without network access and without petitRADTRANS / FastChem /
VULCAN installed.  They exercise:

  R1. BayesFactor.from_evidences() computes ln B and Jeffreys strength correctly
  R2. BayesFactor construction rejects inconsistent ln_bayes_factor_uncertainty
  R3. SpotModelResult rejects filling_factor outside [0, 1]
  R4. PosteriorSummary rejects q16 > median > q84 ordering violations
  R5. PosteriorSummary rejects mismatched units across q16/median/q84
  R6. RetrieveOutput construction validates Bayes factor consistency
  R7. SourceFluxRatio rejects negative ratio and wrong unit
  R8. SourceFluxRatio validator catches inconsistent ratio vs flux fields
  R9. DisequilibriumOutput rejects species_profiles / source_flux_ratios count mismatch
  R10. MUSCLESConfig rejects empty spectral_type_key or muscles_doi
  R11. Batch runner _validate_target_entry catches missing required fields
  R12. Batch runner _validate_target_entry catches c_to_o_ratio <= 0
  R13. DisequilibriumInput now requires muscles_config field
  R14. contracts/__init__.py exports all new types without ImportError
"""

from __future__ import annotations

import math
import pytest

from falsifier.pipeline.contracts.manifest import ArtifactRef, StageManifest, UnitedArray
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dummy_ref(stage: str = "test") -> ArtifactRef:
    return ArtifactRef(
        path=Path("/dev/null"),
        sha256="a" * 64,
        stage=stage,
        pipeline_run_id="test-run-001",
    )


def _dummy_manifest(stage: str = "test") -> StageManifest:
    return StageManifest(
        stage=stage,
        code_version="0.1.0-dev",
        input_hash="b" * 64,
        wall_time_seconds=0.1,
        provenance=[],
        artifact=_dummy_ref(stage),
    )


# ---------------------------------------------------------------------------
# R1 — BayesFactor.from_evidences()
# ---------------------------------------------------------------------------

@pytest.mark.no_network
def test_bayes_factor_from_evidences_decisive():
    """ln B = 5.0 → decisive (|ln B| >= 5)."""
    from falsifier.pipeline.contracts.retrieve import BayesFactor
    bf = BayesFactor.from_evidences(
        model_a_name="atm",
        model_b_name="spot",
        ln_z_a=10.0,
        ln_z_a_unc=0.2,
        ln_z_b=5.0,
        ln_z_b_unc=0.3,
    )
    assert bf.ln_bayes_factor == pytest.approx(5.0)
    assert bf.jeffreys_strength == "decisive"
    assert bf.ln_bayes_factor_uncertainty == pytest.approx(math.sqrt(0.04 + 0.09))


@pytest.mark.no_network
def test_bayes_factor_from_evidences_not_worth_mentioning():
    """ln B = 0.5 → not_worth_mentioning (|ln B| < 1)."""
    from falsifier.pipeline.contracts.retrieve import BayesFactor
    bf = BayesFactor.from_evidences(
        model_a_name="a", model_b_name="b",
        ln_z_a=5.5, ln_z_a_unc=0.1,
        ln_z_b=5.0, ln_z_b_unc=0.1,
    )
    assert bf.jeffreys_strength == "not_worth_mentioning"


@pytest.mark.no_network
def test_bayes_factor_from_evidences_negative_favours_b():
    """Negative ln B means evidence favours model_b."""
    from falsifier.pipeline.contracts.retrieve import BayesFactor
    bf = BayesFactor.from_evidences(
        model_a_name="a", model_b_name="b",
        ln_z_a=0.0, ln_z_a_unc=0.1,
        ln_z_b=7.0, ln_z_b_unc=0.1,
    )
    assert bf.ln_bayes_factor < 0
    assert bf.jeffreys_strength == "decisive"


# ---------------------------------------------------------------------------
# R2 — BayesFactor rejects negative uncertainty
# ---------------------------------------------------------------------------

@pytest.mark.no_network
def test_bayes_factor_rejects_negative_uncertainty():
    from falsifier.pipeline.contracts.retrieve import BayesFactor
    with pytest.raises(Exception):
        BayesFactor(
            model_a_name="a",
            model_b_name="b",
            ln_bayes_factor=3.0,
            ln_bayes_factor_uncertainty=-0.1,
            jeffreys_strength="strong",
        )


# ---------------------------------------------------------------------------
# R3 — SpotModelResult rejects invalid filling_factor
# ---------------------------------------------------------------------------

@pytest.mark.no_network
def test_spot_model_rejects_filling_factor_out_of_range():
    from falsifier.pipeline.contracts.retrieve import SpotModelResult
    with pytest.raises(Exception):
        SpotModelResult(
            spot_filling_factor=1.5,   # > 1: invalid
            spot_temperature_contrast=UnitedArray(values=[300.0], unit="K"),
            log_evidence=-10.0,
            log_evidence_uncertainty=0.2,
            n_live_points=500,
        )


# ---------------------------------------------------------------------------
# R4 — PosteriorSummary rejects q16 > median
# ---------------------------------------------------------------------------

@pytest.mark.no_network
def test_posterior_summary_rejects_bad_quantile_order():
    from falsifier.pipeline.contracts.retrieve import PosteriorSummary
    with pytest.raises(Exception, match="q16 <= median <= q84"):
        PosteriorSummary(
            parameter_name="T_eq",
            median=UnitedArray(values=[500.0], unit="K"),
            q16=UnitedArray(values=[600.0], unit="K"),   # q16 > median: invalid
            q84=UnitedArray(values=[700.0], unit="K"),
        )


# ---------------------------------------------------------------------------
# R5 — PosteriorSummary rejects unit mismatch
# ---------------------------------------------------------------------------

@pytest.mark.no_network
def test_posterior_summary_rejects_unit_mismatch():
    from falsifier.pipeline.contracts.retrieve import PosteriorSummary
    with pytest.raises(Exception, match="same unit"):
        PosteriorSummary(
            parameter_name="R_p",
            median=UnitedArray(values=[1.0], unit="dimensionless"),
            q16=UnitedArray(values=[0.9], unit="K"),   # wrong unit
            q84=UnitedArray(values=[1.1], unit="dimensionless"),
        )


# ---------------------------------------------------------------------------
# R6 — RetrieveOutput validates Bayes factor consistency
# ---------------------------------------------------------------------------

@pytest.mark.no_network
def test_retrieve_output_rejects_inconsistent_bayes_factor():
    """RetrieveOutput must reject a BayesFactor that does not match the evidence fields."""
    from falsifier.pipeline.contracts.retrieve import (
        BayesFactor,
        PosteriorSummary,
        RetrievalConfig,
        RetrieveInput,
        RetrieveOutput,
        RetrievedSpectrum,
        SpotModelResult,
    )

    retrieval_cfg = RetrievalConfig(
        retrieval_code="petitRADTRANS",
        n_live_points=500,
        chemistry_scheme="equilibrium",
        pressure_grid_levels=60,
        include_clouds=False,
    )
    retrieve_input = RetrieveInput(
        classify_artifact=_dummy_ref("classify"),
        retrieval_config=retrieval_cfg,
        pipeline_run_id="test-run",
    )
    spectrum = RetrievedSpectrum(
        wavelength=UnitedArray(values=[1.0, 2.0], unit="micron"),
        transit_depth=UnitedArray(values=[500.0, 500.0], unit="ppm"),
        transit_depth_uncertainty=UnitedArray(values=[50.0, 50.0], unit="ppm"),
    )
    spot_model = SpotModelResult(
        spot_filling_factor=0.1,
        spot_temperature_contrast=UnitedArray(values=[300.0], unit="K"),
        log_evidence=-5.0,
        log_evidence_uncertainty=0.2,
        n_live_points=500,
    )
    # Inconsistent: ln_bayes_factor should be 2.0 - (-5.0) = 7.0, not 3.0
    bad_bf = BayesFactor(
        model_a_name="atm",
        model_b_name="spot",
        ln_bayes_factor=3.0,       # wrong: should be 7.0
        ln_bayes_factor_uncertainty=0.3,
        jeffreys_strength="strong",
    )
    with pytest.raises(Exception, match="does not match"):
        RetrieveOutput(
            input=retrieve_input,
            tce_id="test-tce",
            host_star_id="test-star",
            spectrum=spectrum,
            posterior_summaries=[],
            posterior_artifact=_dummy_ref("retrieve_posterior"),
            log_evidence=2.0,
            log_evidence_uncertainty=0.2,
            spot_model=spot_model,
            bayes_factor_atm_vs_spot=bad_bf,
            sampler="dynesty",
            wall_time_cpu_hours=0.5,
            manifest=_dummy_manifest("retrieve"),
            artifact=_dummy_ref("retrieve"),
        )


@pytest.mark.no_network
def test_retrieve_output_accepts_consistent_bayes_factor():
    """RetrieveOutput accepts a correctly computed BayesFactor."""
    from falsifier.pipeline.contracts.retrieve import (
        BayesFactor,
        RetrievalConfig,
        RetrieveInput,
        RetrieveOutput,
        RetrievedSpectrum,
        SpotModelResult,
    )

    retrieval_cfg = RetrievalConfig(
        retrieval_code="petitRADTRANS",
        n_live_points=500,
        chemistry_scheme="equilibrium",
        pressure_grid_levels=60,
        include_clouds=False,
    )
    retrieve_input = RetrieveInput(
        classify_artifact=_dummy_ref("classify"),
        retrieval_config=retrieval_cfg,
        pipeline_run_id="test-run-ok",
    )
    spectrum = RetrievedSpectrum(
        wavelength=UnitedArray(values=[1.0, 2.0], unit="micron"),
        transit_depth=UnitedArray(values=[500.0, 500.0], unit="ppm"),
        transit_depth_uncertainty=UnitedArray(values=[50.0, 50.0], unit="ppm"),
    )
    ln_z_atm = 2.0
    ln_z_spot = -5.0
    spot_model = SpotModelResult(
        spot_filling_factor=0.1,
        spot_temperature_contrast=UnitedArray(values=[300.0], unit="K"),
        log_evidence=ln_z_spot,
        log_evidence_uncertainty=0.2,
        n_live_points=500,
    )
    good_bf = BayesFactor.from_evidences(
        "atm", "spot",
        ln_z_atm, 0.2,
        ln_z_spot, 0.2,
    )
    out = RetrieveOutput(
        input=retrieve_input,
        tce_id="test-tce",
        host_star_id="test-star",
        spectrum=spectrum,
        posterior_summaries=[],
        posterior_artifact=_dummy_ref("retrieve_posterior"),
        log_evidence=ln_z_atm,
        log_evidence_uncertainty=0.2,
        spot_model=spot_model,
        bayes_factor_atm_vs_spot=good_bf,
        sampler="dynesty",
        wall_time_cpu_hours=0.5,
        manifest=_dummy_manifest("retrieve"),
        artifact=_dummy_ref("retrieve"),
    )
    assert out.bayes_factor_atm_vs_spot.ln_bayes_factor == pytest.approx(7.0)
    assert out.bayes_factor_atm_vs_spot.jeffreys_strength == "decisive"


# ---------------------------------------------------------------------------
# R7 — SourceFluxRatio rejects wrong unit
# ---------------------------------------------------------------------------

@pytest.mark.no_network
def test_source_flux_ratio_rejects_wrong_unit():
    from falsifier.pipeline.contracts.disequilibrium import SourceFluxRatio
    with pytest.raises(Exception, match="W / m2"):
        SourceFluxRatio(
            species="CH4",
            required_source_flux=UnitedArray(values=[1.0], unit="erg / s"),  # wrong
            max_plausible_abiotic_flux=UnitedArray(values=[0.5], unit="W / m2"),
            ratio=2.0,
            ratio_uncertainty=0.1,
            muscles_spectrum_doi="10.3847/0004-637X/820/2/89",
            vulcan_version="2.0",
        )


# ---------------------------------------------------------------------------
# R8 — SourceFluxRatio ratio consistency
# ---------------------------------------------------------------------------

@pytest.mark.no_network
def test_source_flux_ratio_rejects_inconsistent_ratio():
    from falsifier.pipeline.contracts.disequilibrium import SourceFluxRatio
    with pytest.raises(Exception, match="does not match"):
        SourceFluxRatio(
            species="H2O",
            required_source_flux=UnitedArray(values=[3.0], unit="W / m2"),
            max_plausible_abiotic_flux=UnitedArray(values=[1.0], unit="W / m2"),
            ratio=99.0,   # wrong: should be 3.0
            ratio_uncertainty=0.1,
            muscles_spectrum_doi="10.3847/0004-637X/820/2/89",
            vulcan_version="2.0",
        )


@pytest.mark.no_network
def test_source_flux_ratio_accepts_consistent_values():
    from falsifier.pipeline.contracts.disequilibrium import SourceFluxRatio
    sfr = SourceFluxRatio(
        species="CO2",
        required_source_flux=UnitedArray(values=[6.0], unit="W / m2"),
        max_plausible_abiotic_flux=UnitedArray(values=[2.0], unit="W / m2"),
        ratio=3.0,
        ratio_uncertainty=0.2,
        muscles_spectrum_doi="10.3847/0004-637X/820/2/89",
        vulcan_version="2.0",
    )
    assert sfr.ratio == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# R9 — DisequilibriumOutput count mismatch
# ---------------------------------------------------------------------------

@pytest.mark.no_network
def test_disequilibrium_output_rejects_ratio_count_mismatch():
    """source_flux_ratios must have the same length as species_profiles."""
    pytest.importorskip("pydantic")

    from falsifier.pipeline.contracts.disequilibrium import (
        ChemicalSpeciesProfile,
        DisequilibriumInput,
        DisequilibriumOutput,
        FastChemConfig,
        MUSCLESConfig,
        SourceFluxRatio,
    )

    fc_cfg = FastChemConfig(
        temperature_pressure_profile_source="retrieval",
        included_species=["H2O"],
        metallicity_solar=1.0,
        c_to_o_ratio=0.55,
    )
    muscles_cfg = MUSCLESConfig(
        spectral_type_key="GJ1132",
        muscles_doi="10.3847/0004-637X/820/2/89",
        uv_band_lower_nm=115.0,
        uv_band_upper_nm=320.0,
    )
    disq_input = DisequilibriumInput(
        retrieve_artifact=_dummy_ref("retrieve"),
        planet_name="GJ 1132 b",
        planet_doi="10.1038/nature14501",
        fastchem_config=fc_cfg,
        muscles_config=muscles_cfg,
        pipeline_run_id="test-run",
    )
    sp = ChemicalSpeciesProfile(
        species="H2O",
        vmr_profile=UnitedArray(values=[1e-4, 1e-4], unit="dimensionless"),
        pressure=UnitedArray(values=[0.1, 1.0], unit="bar"),
        equilibrium_vmr_profile=UnitedArray(
            values=[1e-4, 1e-4], unit="dimensionless"
        ),
        disequilibrium_metric=0.0,
    )
    from falsifier.pipeline.contracts.disequilibrium import GibbsMinimisationResult
    gibbs = GibbsMinimisationResult(
        temperature=UnitedArray(values=[1000.0], unit="K"),
        pressure=UnitedArray(values=[1.0], unit="bar"),
        species_fractions={"H2O": 1.0},
        gibbs_free_energy=UnitedArray(values=[-5000.0], unit="J / mol"),
    )

    # Provide zero source_flux_ratios for one species_profile — should fail
    with pytest.raises(Exception, match="One SourceFluxRatio is required per species"):
        DisequilibriumOutput(
            input=disq_input,
            planet_name="GJ 1132 b",
            host_star_id="GJ1132",
            species_profiles=[sp],
            gibbs_results=[gibbs],
            source_flux_ratios=[],   # wrong: should have 1 entry
            overall_disequilibrium_score=0.0,
            manifest=_dummy_manifest("disequilibrium"),
            artifact=_dummy_ref("disequilibrium"),
        )


# ---------------------------------------------------------------------------
# R10 — MUSCLESConfig validation
# ---------------------------------------------------------------------------

@pytest.mark.no_network
def test_muscles_config_rejects_empty_doi():
    from falsifier.pipeline.contracts.disequilibrium import MUSCLESConfig
    with pytest.raises(Exception):
        MUSCLESConfig(
            spectral_type_key="GJ1132",
            muscles_doi="",   # empty: invalid
            uv_band_lower_nm=115.0,
            uv_band_upper_nm=320.0,
        )


@pytest.mark.no_network
def test_muscles_config_rejects_empty_key():
    from falsifier.pipeline.contracts.disequilibrium import MUSCLESConfig
    with pytest.raises(Exception):
        MUSCLESConfig(
            spectral_type_key="",   # empty: invalid
            muscles_doi="10.3847/0004-637X/820/2/89",
            uv_band_lower_nm=115.0,
            uv_band_upper_nm=320.0,
        )


# ---------------------------------------------------------------------------
# R11 — Batch runner: missing required fields
# ---------------------------------------------------------------------------

@pytest.mark.no_network
def test_batch_validate_rejects_missing_field():
    from falsifier.pipeline.batch.runner import _validate_target_entry
    bad = {
        "planet_name": "Test b",
        # planet_doi missing — must be caught
        "host_star_id": "TestStar",
        "muscles_key": "GJ1132",
        "muscles_doi": "10.0/test",
        "included_species": ["H2O"],
        "metallicity_solar": 1.0,
        "c_to_o_ratio": 0.55,
        "n_live_points": 500,
        "pressure_grid_levels": 60,
    }
    with pytest.raises(ValueError, match="missing required fields"):
        _validate_target_entry(bad)


# ---------------------------------------------------------------------------
# R12 — Batch runner: c_to_o_ratio <= 0
# ---------------------------------------------------------------------------

@pytest.mark.no_network
def test_batch_validate_rejects_nonpositive_c_to_o():
    from falsifier.pipeline.batch.runner import _validate_target_entry
    bad = {
        "planet_name": "Test b",
        "planet_doi": "10.0/test",
        "host_star_id": "TestStar",
        "muscles_key": "GJ1132",
        "muscles_doi": "10.0/test",
        "included_species": ["H2O"],
        "metallicity_solar": 1.0,
        "c_to_o_ratio": 0.0,   # invalid
        "n_live_points": 500,
        "pressure_grid_levels": 60,
    }
    with pytest.raises(ValueError, match="c_to_o_ratio must be > 0"):
        _validate_target_entry(bad)


# ---------------------------------------------------------------------------
# R13 — DisequilibriumInput requires muscles_config
# ---------------------------------------------------------------------------

@pytest.mark.no_network
def test_disequilibrium_input_requires_muscles_config():
    """DisequilibriumInput must reject construction without muscles_config."""
    from falsifier.pipeline.contracts.disequilibrium import (
        DisequilibriumInput,
        FastChemConfig,
    )
    with pytest.raises(Exception):
        DisequilibriumInput(
            retrieve_artifact=_dummy_ref("retrieve"),
            planet_name="GJ 1132 b",
            planet_doi="10.1038/nature14501",
            fastchem_config=FastChemConfig(
                temperature_pressure_profile_source="retrieval",
                included_species=["H2O"],
                metallicity_solar=1.0,
                c_to_o_ratio=0.55,
            ),
            # muscles_config omitted — should raise
            pipeline_run_id="test",
        )


# ---------------------------------------------------------------------------
# R14 — contracts/__init__.py exports all new types
# ---------------------------------------------------------------------------

@pytest.mark.no_network
def test_contracts_exports_all_new_types():
    """All new types introduced in this task must be importable from the package."""
    from falsifier.pipeline.contracts import (
        BayesFactor,
        PosteriorSummary,
        SpotModelResult,
        MUSCLESConfig,
        SourceFluxRatio,
    )
    assert BayesFactor is not None
    assert PosteriorSummary is not None
    assert SpotModelResult is not None
    assert MUSCLESConfig is not None
    assert SourceFluxRatio is not None
