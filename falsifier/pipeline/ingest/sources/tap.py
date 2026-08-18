"""
falsifier.pipeline.ingest.sources.tap
========================================
NASA Exoplanet Archive TAP client.

Policy
------
Only the ``ps`` (Planetary Systems) and ``pscomppars`` (Planetary Systems
Composite Parameters) tables are used.  The retired tables ``exoplanet``,
``exomultpars``, and ``compositepars`` must not appear anywhere — they are
not queried here and any reference to them in calling code is a bug.

ADQL is executed against::

    https://exoplanetarchive.ipac.caltech.edu/TAP/sync

Results are returned as a ``pandas.DataFrame`` and cached as Parquet.

DOI
---
The NASA Exoplanet Archive is cited as::

    10.26133/NEA12

which is the persistent DOI for the archive itself.  Individual tables do
not have separate DOIs.
"""

from __future__ import annotations

import functools
import logging
import warnings
from typing import Any

import pandas as pd

from ..endpoints import NEA_DOI, NEA_TAP_ASYNC_URL, NEA_TAP_SYNC_URL
from ..exceptions import TapFetchError, TargetNotFoundError

log = logging.getLogger(__name__)

# Re-export for callers that import TAP_ENDPOINT / NEA_DOI from here.
TAP_ENDPOINT = NEA_TAP_SYNC_URL
TAP_ASYNC_ENDPOINT = NEA_TAP_ASYNC_URL

__all__ = ["TAP_ENDPOINT", "TAP_ASYNC_ENDPOINT", "NEA_DOI", "fetch_planet_params"]

# Retired tables that must never be queried — kept here for the guard check  # retired-table-ref-ok
_RETIRED_TABLES = frozenset({"exoplanet", "exomultpars", "compositepars"})  # retired-table-ref-ok

# Approved tables — ps, pscomppars, and cumulative (Kepler cumulative catalog)
_APPROVED_TABLES = frozenset({"ps", "pscomppars", "cumulative"})


def _guard_table(adql: str) -> None:
    """Raise if *adql* references any retired table."""  # retired-table-ref-ok
    lower = adql.lower()
    for t in _RETIRED_TABLES:
        if t in lower:
            raise ValueError(
                f"ADQL query references retired table '{t}'.\n"  # retired-table-ref-ok
                f"Use 'ps' or 'pscomppars' instead.\n"
                f"Query: {adql!r}"
            )


def _tap_with_retry(fn):
    """
    Thin wrapper that retries the TAP call once on transient HTTP errors.

    Uses ``functools.wraps`` so ``fn.__wrapped__`` is accessible.  This
    allows ``tests/pipeline/stages/test_ingest.py::TestTapTableGuard::
    test_invalid_table_arg_raises`` to call the underlying function directly
    (bypassing the retry logic) without hitting the network.
    """
    @functools.wraps(fn)
    def _wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            from ..exceptions import TapFetchError
            # Re-raise immediately for non-network errors (ValueError, etc.)
            if not isinstance(exc, TapFetchError):
                raise
            log.debug("TAP retry after transient error: %s", exc)
            return fn(*args, **kwargs)
    return _wrapper


@_tap_with_retry
def fetch_planet_params(
    target_id: str,
    *,
    table: str = "pscomppars",
    extra_columns: list[str] | None = None,
) -> pd.DataFrame:
    """
    Query the NASA Exoplanet Archive TAP for parameters of *target_id*.

    Parameters
    ----------
    target_id : str
        Canonical target name, e.g. ``"Kepler-10 b"`` or ``"KIC 11904151"``.
        The query uses a LIKE match on ``hostname`` or ``pl_name``.
    table : str
        One of ``"ps"`` or ``"pscomppars"``.  Default: ``"pscomppars"``.
    extra_columns : list[str] | None
        Additional column names to include.  The base set covers period,
        semi-major axis, radius, mass, and stellar parameters.

    Returns
    -------
    pandas.DataFrame

    Raises
    ------
    TapFetchError
        On HTTP or parsing error.
    TargetNotFoundError
        If the query returns zero rows.
    ValueError
        If *table* is not an approved table.
    """
    if table not in _APPROVED_TABLES:
        raise ValueError(
            f"Table '{table}' is not approved.  Use one of: {sorted(_APPROVED_TABLES)}"
        )

    base_columns = [
        "pl_name", "hostname", "sy_snum", "sy_pnum",
        "pl_orbper", "pl_orbpererr1", "pl_orbpererr2",
        "pl_rade", "pl_radeerr1", "pl_radeerr2",
        "pl_masse", "pl_masseerr1", "pl_masseerr2",
        "pl_orbsmax", "pl_orbsmaxerr1", "pl_orbsmaxerr2",
        "st_teff", "st_tefferr1", "st_tefferr2",
        "st_rad", "st_raderr1", "st_raderr2",
        "st_mass", "st_masserr1", "st_masserr2",
        "st_logg", "st_loggerr1", "st_loggerr2",
        "sy_dist", "sy_disterr1", "sy_disterr2",
        "rowupdate", "pl_refname",
    ]
    if extra_columns:
        for col in extra_columns:
            if col not in base_columns:
                base_columns.append(col)

    cols = ", ".join(base_columns)

    # Escape single quotes in target_id
    safe_target = target_id.replace("'", "''")
    adql = (
        f"SELECT {cols} FROM {table} "
        f"WHERE hostname LIKE '%{safe_target}%' "
        f"OR pl_name LIKE '%{safe_target}%'"
    )
    _guard_table(adql)

    log.debug("TAP query: %s", adql)

    try:
        from astroquery.utils.tap.core import Tap
    except ImportError as exc:
        raise TapFetchError(
            f"astroquery not installed: {exc}",
            endpoint=TAP_ENDPOINT,
            query=adql,
        ) from exc

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tap = Tap(url=TAP_ENDPOINT)
            job = tap.launch_job(adql)
            result_table = job.get_results()
    except Exception as exc:
        raise TapFetchError(
            f"TAP query failed: {exc}",
            endpoint=TAP_ENDPOINT,
            query=adql,
        ) from exc

    df = result_table.to_pandas()

    if len(df) == 0:
        raise TargetNotFoundError(
            f"TAP returned 0 rows for target={target_id!r} in table '{table}'",
            endpoint=TAP_ENDPOINT,
            query=adql,
        )

    log.debug("TAP returned %d rows for %r", len(df), target_id)
    return df
