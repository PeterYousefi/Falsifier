"""
tests/test_train_classifier_dr25.py
=====================================
Guards against re-introduction of the train/serve feature skew in
``scripts/train_classifier_dr25.py``.

The script's ``main()`` raises ``NotImplementedError`` when called with
``--train`` until the feature skew between DR25 diagnostic columns and
the vet-stage ``metric_value`` fields is resolved.  This test verifies
that the guard is present and fires.

It does NOT call the network: it imports the module's functions directly
and never calls ``_fetch_dr25``.
"""

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

_SCRIPT = Path(__file__).parent.parent / "scripts" / "train_classifier_dr25.py"


def _load_script() -> types.ModuleType:
    """Load train_classifier_dr25.py as a module without executing __main__."""
    spec = importlib.util.spec_from_file_location("train_classifier_dr25", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestTrainClassifierDr25:

    def test_script_exists(self):
        assert _SCRIPT.exists(), (
            f"scripts/train_classifier_dr25.py not found at {_SCRIPT}.\n"
            "This file must exist to document the feature-skew block."
        )

    def test_train_flag_raises_not_implemented(self):
        """
        Calling main() with --train must raise NotImplementedError.

        This test confirms the train/serve skew guard is in place.  If someone
        removes the guard (intending to unblock training), this test will fail,
        forcing them to also remove or update this assertion explicitly.
        """
        mod = _load_script()

        # Patch _fetch_dr25 so no network call is made, and _report so no
        # output is printed.  We only want to test the --train guard.
        import pandas as pd
        fake_df = pd.DataFrame({
            "kepid": [11904151],
            "kepoi_name": ["K00072.01"],
            "koi_disposition": ["PC"],
            "koi_period": [0.837],
            "koi_depth": [100.0],
            "koi_model_snr": [50.0],
            "koi_ldm_coeff1": [0.3],
            "koi_ldm_coeff4": [0.1],
            "koi_dicco_msky_err": [0.05],
            "koi_steff": [5600.0],
            "koi_robstat": [0.0],
        })

        with (
            patch.object(mod, "_fetch_dr25", return_value=fake_df),
            patch.object(mod, "_report"),
            patch("sys.argv", ["train_classifier_dr25.py", "--train"]),
        ):
            with pytest.raises(NotImplementedError, match="feature skew"):
                mod.main()

    def test_dry_run_does_not_train(self):
        """
        Calling main() without --train must not raise NotImplementedError,
        confirming the dry-run path is safe to call.
        """
        mod = _load_script()

        import pandas as pd
        fake_df = pd.DataFrame({
            "kepid": [11904151],
            "kepoi_name": ["K00072.01"],
            "koi_disposition": ["PC"],
            "koi_period": [0.837],
            "koi_depth": [100.0],
            "koi_model_snr": [50.0],
            "koi_ldm_coeff1": [0.3],
            "koi_ldm_coeff4": [0.1],
            "koi_dicco_msky_err": [0.05],
            "koi_steff": [5600.0],
            "koi_robstat": [0.0],
        })

        with (
            patch.object(mod, "_fetch_dr25", return_value=fake_df),
            patch.object(mod, "_report"),
            patch("sys.argv", ["train_classifier_dr25.py"]),
        ):
            # Should complete without raising
            mod.main()

    def test_proxy_mapping_table_is_documented_in_module_docstring(self):
        """
        The module docstring must contain the skew table.

        If someone refactors the docstring away, this test fails, ensuring the
        skew explanation is always present in the file.
        """
        mod = _load_script()
        doc = mod.__doc__ or ""
        required_phrases = [
            "train/serve skew",
            "odd_even_depth_metric",
            "koi_ldm_coeff4",
            "NotImplementedError",
            "Option A",
            "Option B",
        ]
        for phrase in required_phrases:
            assert phrase in doc, (
                f"Module docstring missing required phrase: {phrase!r}\n"
                "The train/serve skew documentation must remain in the module docstring."
            )
