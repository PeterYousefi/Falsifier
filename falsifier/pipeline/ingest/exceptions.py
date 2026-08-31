"""
falsifier.pipeline.ingest.exceptions
======================================
Typed exceptions for ingest-layer failures.

All exceptions carry the originating query and endpoint so callers can log,
alert, or surface them without parsing message strings.
"""

from __future__ import annotations


class IngestError(RuntimeError):
    """Base class for all ingest-stage failures."""


class FetchError(IngestError):
    """
    Raised when a remote fetch (MAST, TAP, Gaia) fails at the HTTP/network
    level or returns an unexpected response.

    Attributes
    ----------
    endpoint : str
        The URL or service name that was contacted.
    query : str
        The query string or product ID that was requested.
    """

    def __init__(self, message: str, *, endpoint: str, query: str) -> None:
        """
        Parameters
        ----------
        message : str
            Human-readable description of the fetch failure.
        endpoint : str
            The URL or service name that was contacted when the failure
            occurred.
        query : str
            The query string or MAST product ID that triggered the failure.
        """
        super().__init__(message)
        self.endpoint = endpoint
        self.query = query

    def __str__(self) -> str:
        return (
            f"{super().__str__()}\n"
            f"  endpoint : {self.endpoint}\n"
            f"  query    : {self.query}"
        )


class MastFetchError(FetchError):
    """
    Raised on MAST / lightkurve fetch failure.

    Inherits ``endpoint`` and ``query`` attributes from ``FetchError``.
    """


class TapFetchError(FetchError):
    """
    Raised on NASA Exoplanet Archive TAP fetch failure.

    Inherits ``endpoint`` and ``query`` attributes from ``FetchError``.
    """


class GaiaFetchError(FetchError):
    """
    Raised on astroquery.gaia fetch failure.

    Inherits ``endpoint`` and ``query`` attributes from ``FetchError``.
    """


class TargetNotFoundError(FetchError):
    """
    Raised when no data exist for the requested target at the requested
    service.

    Distinct from a network failure: the target name is simply absent from
    the archive.  ``endpoint`` and ``query`` are inherited from ``FetchError``.
    """


class NoProductMatchError(MastFetchError):
    """
    Raised when lightkurve returns results but none match the pinned
    ``mast_product_id``.

    Never fall back silently to a different product (AGENTS.md policy).
    """


class AmbiguousProductError(MastFetchError):
    """
    Raised when more than one product matches the pinned ``mast_product_id``.

    The product ID must be unique; multiple matches indicate a manifest error.
    """


class HeaderMissingKeyError(IngestError):
    """
    Raised when a required FITS header keyword (e.g. TIMESYS, TIMEUNIT) is
    absent.

    Time-system information must come from the header, never from a
    hardcoded assumption.

    Attributes
    ----------
    fits_path : str
        Path to the FITS file with the missing key.
    key : str
        The header keyword that was expected but absent.
    """

    def __init__(self, message: str, *, fits_path: str, key: str) -> None:
        """
        Parameters
        ----------
        message : str
            Human-readable description of which header key is missing.
        fits_path : str
            Path to the FITS file that is missing the required header key.
        key : str
            Name of the FITS header keyword that was expected but absent
            (e.g. ``"TIMESYS"`` or ``"TIME_FMT"``).
        """
        super().__init__(message)
        self.fits_path = fits_path
        self.key = key

    def __str__(self) -> str:
        return (
            f"{super().__str__()}\n"
            f"  fits_path : {self.fits_path}\n"
            f"  key       : {self.key}"
        )


class PartialDataError(IngestError):
    """
    Raised when a fetch returns fewer segments than expected and the failure
    mode is ambiguous.

    Never return partial data silently (AGENTS.md policy).
    """


class StaleArtifactError(IngestError):
    """
    Raised when a cached artifact exceeds ``max_age`` and ``offline=True``
    prevents a refetch.

    The caller must either increase ``max_age`` or disable offline mode to
    trigger a live refetch.
    """


class CacheCorruptedError(IngestError):
    """
    Raised when the SHA-256 of a cached file does not match its sidecar
    manifest.

    The artifact must be deleted and re-fetched to recover.
    """
