"""
falsifier.pipeline.exceptions
================================
Typed exceptions for pipeline-stage failures.

These are distinct from ``falsifier.pipeline.ingest.exceptions`` (which covers
ingest-layer network and FITS errors).  The exceptions here cover algorithm-
selection and dependency failures that can arise in any pipeline stage.

Policy
------
No pipeline stage may substitute a different algorithm, data source, or file
without the caller explicitly requesting it.  If a required dependency is
absent, the stage **raises** rather than degrading silently.  The caller is
responsible for deciding whether a fallback is acceptable; if it is, the caller
must pass an explicit flag and the artifact must record which algorithm was
actually used.

See AGENTS.md §Non-Negotiable Rules for All Generated Code.
"""

from __future__ import annotations


class PipelineError(RuntimeError):
    """Base class for all pipeline-stage failures."""


class TLSUnavailableError(PipelineError):
    """
    Raised when TransitLeastSquares (TLS) is requested but cannot be imported.

    TLS requires ``transitleastsquares`` and its dependency ``batman-package``.
    On macOS/Python 3.12, ``batman`` requires the distutils compatibility shim
    (``falsifier._distutils_compat``) to be loaded before import.  If TLS is
    requested but the import fails for any reason, this exception names the
    missing dependency and the reason rather than degrading silently to BLS.

    Attributes
    ----------
    missing_package : str
        The top-level package whose ``ImportError`` triggered this exception.
    reason : str
        Human-readable explanation (the original ``ImportError`` message).
    """

    def __init__(self, missing_package: str, reason: str) -> None:
        super().__init__(
            f"TransitLeastSquares is not available: "
            f"failed to import '{missing_package}'.\n"
            f"  Reason : {reason}\n"
            f"  Fix    : pip install transitleastsquares batman-package\n"
            f"  On macOS/Python 3.12 ensure falsifier._distutils_compat is "
            f"imported before batman (it is imported at the top of "
            f"falsifier.pipeline.stages.search and in conftest.py)."
        )
        self.missing_package = missing_package
        self.reason = reason
