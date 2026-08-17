"""
falsifier.pipeline.ingest.endpoints
======================================
Canonical external data-source endpoint URLs, DOIs, and documentation
references for every service the ingest layer contacts.

Rules
-----
- Every URL here is a string constant, not a per-call argument.
- All three services are publicly accessible without authentication.
  No API key is read, stored, or transmitted by any code that imports
  from this module.  See AGENTS.md Rule 1.
- The module is import-safe with stdlib only — no astropy, no requests.

Services
--------
MAST (Mikulski Archive for Space Telescopes)
    Light curve FITS files for Kepler, K2, TESS.
    Accessed via ``lightkurve``; no direct HTTP call is made by this codebase.
    No API key required.

NASA Exoplanet Archive TAP
    Planet and stellar parameters via ADQL over TAP/sync or TAP/async.
    Accessed via ``astroquery.utils.tap.core.Tap``.
    No API key required.
    ADQL NOTE: use ``SELECT TOP N`` — the Archive does NOT support ``LIMIT``.
    Approved tables: ``ps``, ``pscomppars``, ``cumulative`` (Kepler cumulative).
    Retired tables (must NEVER appear in ADQL): ``exoplanet``, ``exomultpars``,
    ``compositepars``.

Gaia DR3
    Stellar RUWE, effective temperature, radius, parallax via TAP+.
    Accessed via ``astroquery.gaia.Gaia``.
    No API key required.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# MAST — Mikulski Archive for Space Telescopes
# ---------------------------------------------------------------------------

MAST_BASE_URL = "https://mast.stsci.edu"
"""Base URL for MAST.  Used in typed exception ``endpoint`` fields."""

MAST_API_URL = "https://mast.stsci.edu/api/v0/invoke"
"""
REST API invocation endpoint.
Reference: https://mast.stsci.edu/api/v0/
Light curves are fetched via lightkurve (which wraps this endpoint), not
by direct HTTP calls from this codebase.
"""

MAST_DOI = "10.17909/t9-st5g-3177"
"""
Persistent DOI for the MAST High Level Science Products archive.
Recorded in ``DatasetProvenance.source_doi`` for every MAST-fetched file.
Reference: https://doi.org/10.17909/t9-st5g-3177
"""

MAST_DOCS_URL = "https://mast.stsci.edu/api/v0/"
"""Human-readable API documentation URL."""

# ---------------------------------------------------------------------------
# NASA Exoplanet Archive — TAP service
# ---------------------------------------------------------------------------

NEA_TAP_BASE_URL = "https://exoplanetarchive.ipac.caltech.edu/TAP"
"""Base URL for the NASA Exoplanet Archive TAP service."""

NEA_TAP_SYNC_URL = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
"""
Synchronous ADQL endpoint.  Use for queries expected to complete in < 30 s.
IMPORTANT: use ``SELECT TOP N`` in ADQL — the Archive does NOT support
the ``LIMIT`` clause.
"""

NEA_TAP_ASYNC_URL = "https://exoplanetarchive.ipac.caltech.edu/TAP/async"
"""
Asynchronous ADQL endpoint.  Use for large queries or when the synchronous
endpoint times out.  Returns a job ID; poll for results.
"""

NEA_DOI = "10.26133/NEA12"
"""
Persistent DOI for the NASA Exoplanet Archive.
Recorded in ``DatasetProvenance.source_doi`` for every NEA query.
Reference: https://doi.org/10.26133/NEA12
"""

NEA_DOCS_URL = "https://exoplanetarchive.ipac.caltech.edu/docs/program_interfaces.html"
"""Human-readable TAP documentation URL."""

# ---------------------------------------------------------------------------
# Gaia DR3 — ESA Gaia TAP+ service
# ---------------------------------------------------------------------------

GAIA_TAP_URL = "https://gea.esac.esa.int/tap-server/tap"
"""
Gaia DR3 TAP+ endpoint.  Used directly by ``astroquery.gaia.Gaia``.
No API key required; publicly accessible.
"""

GAIA_DOI = "10.1051/0004-6361/202243940"
"""
DOI for Gaia DR3 (Gaia Collaboration, Vallenari et al. 2023, A&A 674, A1).
Recorded in ``DatasetProvenance.source_doi`` for every Gaia query.
Reference: https://doi.org/10.1051/0004-6361/202243940
"""

GAIA_DOCS_URL = "https://gea.esac.esa.int/archive/"
"""Human-readable Gaia archive documentation URL."""
