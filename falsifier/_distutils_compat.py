"""
falsifier._distutils_compat
==============================
Python 3.12 distutils compatibility shim for batman / transitleastsquares.

Problem
-------
``batman`` (a ``transitleastsquares`` dependency) does::

    from distutils.ccompiler import new_compiler   # batman/openmp.py line 2

at module scope.  ``distutils`` was removed from the Python 3.12 standard
library.  ``setuptools>=68`` ships a replacement under
``setuptools._distutils`` together with a meta-path importer
(``_distutils_hack``) that redirects ``import distutils`` to it.

The importer is activated by two mechanisms:

1. A ``distutils-precedence.pth`` file installed by setuptools that calls
   ``_distutils_hack.add_shim()`` at interpreter startup.  This fires for
   the main process when the venv is created with setuptools>=68 present.

2. Multiprocessing ``spawn`` workers on macOS (Python's default start
   method on macOS ≥ 3.8) run a fresh Python interpreter.  The .pth file
   **does** fire in spawn workers when ``SETUPTOOLS_USE_DISTUTILS=local``
   is set (the setuptools default).  However on uv-managed venvs and some
   CI configurations the .pth exec may be pre-empted or the env var absent.
   This module is a belt-and-suspenders fallback.

Fix strategy (this module)
--------------------------
1. Try ``_distutils_hack.add_shim()`` to activate the setuptools shim for
   the current interpreter.  This is a no-op if the shim is already active.
2. If ``distutils`` is still not in ``sys.modules`` after the shim attempt
   (e.g. setuptools is absent or too old), inject a minimal stub covering
   only the names batman actually uses at module scope:
   - ``distutils.ccompiler.new_compiler``
   - ``distutils.ccompiler.CCompiler``
   The stub is never used for real compilation — batman calls
   ``CCompiler.has_function`` at import time only to decide whether to
   enable OpenMP; the pre-built wheel already has OpenMP compiled in, so
   the stub result (always False) is harmless.

Usage
-----
Import this module at the top of any file that imports batman or TLS::

    import falsifier._distutils_compat  # noqa: F401  (side-effect import)

or simply rely on it being imported transitively from
``falsifier.pipeline.stages.search``.

This module is safe to import multiple times — all operations are guarded
with ``if 'distutils' not in sys.modules``.
"""

from __future__ import annotations

import sys
import types

# Step 1: activate the setuptools meta-path importer if available.
try:
    import _distutils_hack as _dh
    _dh.add_shim()
    del _dh
except ImportError:
    pass  # setuptools not installed or too old — fall through to step 2

# Step 2: inject a minimal stub so batman/openmp.py can import without crashing
# in any interpreter (spawn worker, REPL, API server process) where the
# setuptools shim is absent.
if "distutils" not in sys.modules:
    _stub_pkg = types.ModuleType("distutils")
    _stub_cc = types.ModuleType("distutils.ccompiler")

    class _StubCCompiler:
        """
        Minimal stand-in for distutils.ccompiler.CCompiler.

        batman/openmp.py calls ``new_compiler().has_function('omp_get_wtime')``
        at import time to decide whether to build with OpenMP.  The pre-built
        wheel already includes OpenMP, so we return False to skip the runtime
        detection path without ill effect.
        """

        def has_function(self, *args, **kwargs) -> bool:  # noqa: D102
            return False

        def add_library(self, *args, **kwargs) -> None:  # noqa: D102
            pass

    def _new_compiler(*args, **kwargs) -> _StubCCompiler:
        return _StubCCompiler()

    _stub_cc.new_compiler = _new_compiler  # type: ignore[attr-defined]
    _stub_cc.CCompiler = _StubCCompiler  # type: ignore[attr-defined]
    _stub_pkg.ccompiler = _stub_cc  # type: ignore[attr-defined]

    sys.modules.setdefault("distutils", _stub_pkg)
    sys.modules.setdefault("distutils.ccompiler", _stub_cc)

    del _stub_pkg, _stub_cc, _StubCCompiler, _new_compiler
