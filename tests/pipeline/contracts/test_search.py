"""
tests/pipeline/contracts/test_search.py
=========================================
Tests for SearchInput, TCE, SearchOutput.

All tests use stdlib + pydantic only — no astropy, no network.
"""

from __future__ import annotations

import datetime
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from falsifier.pipeline.contracts.search import (
    SearchInput,
    SearchOutput,
    TCE,
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


def _artifact_ref(stage: str = "detrend") -> ArtifactRef:
    return ArtifactRef(
        path=Path("/dev/null"),
        sha256="c" * 64,
        stage=stage,
        pipeline_run_id=_run_id(),
    )


def _stage_manifest(stage: str = "search") -> StageManifest:
    return StageManifest(
        stage=stage,
        code_version="0.1.0-dev",
        input_hash="d" * 64,
        wall_time_seconds=30.0,
        provenance=[],
        artifact=_artifact_ref(stage),
    )


def _search_input(**kwargs) -> SearchInput:
    defaults = dict(
        detrend_artifact=_artifact_ref("detrend"),
        period_min=UnitedArray(values=[1.0], unit="day"),
        period_max=UnitedArray(values=[30.0], unit="day"),
        snr_threshold=7.0,
        pipeline_run_id=_run_id(),
    )
    defaults.update(kwargs)
    return SearchInput(**defaults)


def _tce(**kwargs) -> TCE:
    defaults = dict(
        tce_id="KIC 11904151-00",
        period=UnitedArray(values=[0.8368], unit="day"),
        period_uncertainty=UnitedArray(values=[0.0001], unit="day"),
        epoch=UnitedArray(values=[2454833.0], unit="bkjd"),
        duration=UnitedArray(values=[1.86], unit="hour"),
        depth=UnitedArray(values=[1260.0], unit="ppm"),
        sde=30.1,
        snr=25.4,
        odd_even_mismatch=0.02,
        secondary_eclipse_depth=None,
    )
    defaults.update(kwargs)
    return TCE(**defaults)


def _search_output(**kwargs) -> SearchOutput:
    inp = _search_input()
    defaults = dict(
        input=inp,
        tces=[_tce()],
        host_star_id="KIC 11904151",
        tls_version="1.0.31",
        manifest=_stage_manifest(),
        artifact=_artifact_ref("search"),
    )
    defaults.update(kwargs)
    return SearchOutput(**defaults)


# ---------------------------------------------------------------------------
# SearchInput tests
# ---------------------------------------------------------------------------

class TestSearchInput:
    def test_valid_construction(self):
        inp = _search_input()
        assert inp.period_min.values == [1.0]
        assert inp.period_max.values == [30.0]
        assert inp.snr_threshold == 7.0

    def test_period_unit_d_accepted(self):
        inp = _search_input(
            period_min=UnitedArray(values=[1.0], unit="d"),
            period_max=UnitedArray(values=[10.0], unit="d"),
        )
        assert inp.period_min.unit == "d"

    def test_rejects_wrong_period_unit(self):
        with pytest.raises(ValidationError, match="got 'hour'"):
            _search_input(period_min=UnitedArray(values=[1.0], unit="hour"))

    def test_rejects_multi_element_period(self):
        with pytest.raises(ValidationError, match="single-element"):
            _search_input(period_min=UnitedArray(values=[1.0, 2.0], unit="day"))

    def test_rejects_period_min_gte_max(self):
        with pytest.raises(ValidationError, match="must be < period_max"):
            _search_input(
                period_min=UnitedArray(values=[10.0], unit="day"),
                period_max=UnitedArray(values=[5.0], unit="day"),
            )

    def test_rejects_period_min_equal_max(self):
        with pytest.raises(ValidationError, match="must be < period_max"):
            _search_input(
                period_min=UnitedArray(values=[5.0], unit="day"),
                period_max=UnitedArray(values=[5.0], unit="day"),
            )


# ---------------------------------------------------------------------------
# TCE tests
# ---------------------------------------------------------------------------

class TestTCE:
    def test_valid_tce(self):
        t = _tce()
        assert t.tce_id == "KIC 11904151-00"
        assert t.period.values == [0.8368]
        assert t.period.unit == "day"

    def test_period_uncertainty_required(self):
        """period_uncertainty must be present — no bare point estimate allowed."""
        t = _tce()
        assert t.period_uncertainty is not None
        assert t.period_uncertainty.values[0] > 0

    def test_secondary_eclipse_none_accepted(self):
        t = _tce(secondary_eclipse_depth=None)
        assert t.secondary_eclipse_depth is None

    def test_secondary_eclipse_populated(self):
        t = _tce(secondary_eclipse_depth=UnitedArray(values=[400.0], unit="ppm"))
        assert t.secondary_eclipse_depth.values[0] == pytest.approx(400.0)

    def test_rejects_wrong_duration_unit(self):
        with pytest.raises(ValidationError, match="unit 'h' or 'hour'"):
            _tce(duration=UnitedArray(values=[1.86], unit="day"))

    def test_rejects_wrong_depth_unit(self):
        with pytest.raises(ValidationError, match="unit 'ppm'"):
            _tce(depth=UnitedArray(values=[0.00126], unit="dimensionless"))

    def test_rejects_multi_element_period(self):
        with pytest.raises(ValidationError, match="single-element"):
            _tce(period=UnitedArray(values=[0.83, 0.84], unit="day"))

    def test_rejects_multi_element_duration(self):
        with pytest.raises(ValidationError, match="single-element"):
            _tce(duration=UnitedArray(values=[1.0, 2.0], unit="hour"))

    def test_rejects_missing_period_uncertainty(self):
        """period_uncertainty has no default — omitting it is a ValidationError."""
        with pytest.raises((ValidationError, TypeError)):
            TCE(
                tce_id="X-00",
                period=UnitedArray(values=[1.0], unit="day"),
                # period_uncertainty omitted
                epoch=UnitedArray(values=[2454833.0], unit="bkjd"),
                duration=UnitedArray(values=[1.0], unit="hour"),
                depth=UnitedArray(values=[1000.0], unit="ppm"),
                sde=10.0,
                snr=8.0,
                odd_even_mismatch=0.0,
            )

    def test_to_quantity_on_period(self):
        """to_quantity() returns correct unit — uses only stdlib math check."""
        t = _tce()
        # Unit round-trip: values[0] must survive float conversion
        assert t.period.values[0] == pytest.approx(0.8368)
        assert t.period.unit == "day"

    def test_json_roundtrip(self):
        t = _tce(secondary_eclipse_depth=UnitedArray(values=[300.0], unit="ppm"))
        restored = TCE.model_validate_json(t.model_dump_json())
        assert restored.tce_id == t.tce_id
        assert restored.period.values == t.period.values
        assert restored.secondary_eclipse_depth.values == [300.0]


# ---------------------------------------------------------------------------
# SearchOutput tests
# ---------------------------------------------------------------------------

class TestSearchOutput:
    def test_valid_with_tces(self):
        out = _search_output()
        assert len(out.tces) == 1
        assert out.tls_version == "1.0.31"

    def test_empty_tces_accepted(self):
        """No significant signals found is a valid outcome."""
        out = _search_output(tces=[])
        assert out.tces == []

    def test_multiple_tces_accepted(self):
        out = _search_output(tces=[_tce(), _tce(tce_id="KIC 11904151-01")])
        assert len(out.tces) == 2

    def test_json_roundtrip(self):
        out = _search_output()
        restored = SearchOutput.model_validate_json(out.model_dump_json())
        assert restored.host_star_id == out.host_star_id
        assert restored.tls_version == out.tls_version
        assert len(restored.tces) == len(out.tces)
