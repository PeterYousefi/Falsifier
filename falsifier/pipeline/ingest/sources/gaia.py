"""
falsifier.pipeline.ingest.sources.gaia
=========================================
Gaia DR3 stellar parameter fetcher via astroquery.gaia.

Fetches RUWE, effective temperature, stellar radius, and parallax for the
host star.  Results are returned as a ``StellarParams`` contract object.

DOI
---
Gaia DR3 is cited as::

    10.1051/0004-6361/202243940

(Gaia Collaboration, Vallenari et al. 2023, A&A 674, A1)

Tables used
-----------
``gaiadr3.gaia_source`` via the Gaia TAP+ service at::

    https://gea.esac.esa.int/tap-server/tap

Columns fetched: ``source_id``, ``ra``, ``dec``, ``parallax``,
``parallax_error``, ``ruwe``, ``teff_gspphot``, ``teff_gspphot_lower``,
``teff_gspphot_upper``, ``radius_gspphot``, ``radius_gspphot_lower``,
``radius_gspphot_upper``.
"""

from __future__ import annotations

import datetime
import logging
import warnings

import numpy as np

from ...contracts.ingest import StellarParams
from ...contracts.manifest import DatasetProvenance, UnitedArray
from ..exceptions import GaiaFetchError, TargetNotFoundError

log = logging.getLogger(__name__)

GAIA_DOI = "10.1051/0004-6361/202243940"
GAIA_ENDPOINT = "https://gea.esac.esa.int/tap-server/tap"

_GAIA_COLUMNS = (
    "source_id, ra, dec, parallax, parallax_error, ruwe, "
    "teff_gspphot, teff_gspphot_lower, teff_gspphot_upper, "
    "radius_gspphot, radius_gspphot_lower, radius_gspphot_upper"
)


def fetch_stellar_params(
    ra_deg: float,
    dec_deg: float,
    *,
    search_radius_arcsec: float = 5.0,
    access_date: datetime.date | None = None,
) -> StellarParams:
    """
    Query Gaia DR3 for the star nearest to *(ra_deg, dec_deg)* within
    *search_radius_arcsec*.

    Parameters
    ----------
    ra_deg, dec_deg : float
        Sky coordinates in degrees (J2000).
    search_radius_arcsec : float
        Cone search radius.  5 arcsec is sufficient for stars with good
        Gaia coverage; narrow it for crowded fields.
    access_date : datetime.date | None
        Date to record in the provenance sidecar.  Defaults to today.

    Returns
    -------
    StellarParams

    Raises
    ------
    TargetNotFoundError
        If the cone search returns zero rows in Gaia DR3.
    GaiaFetchError
        On astroquery network or parsing failure.
    """
    if access_date is None:
        access_date = datetime.date.today()

    radius_deg = search_radius_arcsec / 3600.0

    adql = (
        f"SELECT {_GAIA_COLUMNS} "
        f"FROM gaiadr3.gaia_source "
        f"WHERE CONTAINS("
        f"  POINT('ICRS', ra, dec), "
        f"  CIRCLE('ICRS', {ra_deg}, {dec_deg}, {radius_deg})"
        f") = 1 "
        f"ORDER BY ruwe ASC"
    )

    log.debug("Gaia query: %s", adql)

    try:
        from astroquery.gaia import Gaia
    except ImportError as exc:
        raise GaiaFetchError(
            f"astroquery not installed: {exc}",
            endpoint=GAIA_ENDPOINT,
            query=adql,
        ) from exc

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            job = Gaia.launch_job(adql)
            result = job.get_results()
    except Exception as exc:
        raise GaiaFetchError(
            f"Gaia TAP query failed: {exc}",
            endpoint=GAIA_ENDPOINT,
            query=adql,
        ) from exc

    if len(result) == 0:
        raise TargetNotFoundError(
            f"Gaia DR3 returned 0 rows within {search_radius_arcsec} arcsec of "
            f"RA={ra_deg}, Dec={dec_deg}",
            endpoint=GAIA_ENDPOINT,
            query=adql,
        )

    # Use first row (lowest RUWE — best astrometric solution)
    row = result[0]

    def _col(name: str) -> float:
        val = row[name]
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return float("nan")
        return float(val)

    source_id = str(row["source_id"])
    ra = _col("ra")
    dec = _col("dec")
    parallax = _col("parallax")
    parallax_error = _col("parallax_error")
    ruwe = _col("ruwe")

    teff = _col("teff_gspphot")
    teff_lo = _col("teff_gspphot_lower")
    teff_hi = _col("teff_gspphot_upper")
    # Symmetric uncertainty: half the credible interval width
    teff_unc = abs(teff_hi - teff_lo) / 2.0

    radius = _col("radius_gspphot")
    radius_lo = _col("radius_gspphot_lower")
    radius_hi = _col("radius_gspphot_upper")
    radius_unc = abs(radius_hi - radius_lo) / 2.0

    parallax_over_error = (
        parallax / parallax_error if parallax_error and parallax_error != 0 else float("nan")
    )

    provenance = DatasetProvenance(
        source_doi=GAIA_DOI,
        source_url=GAIA_ENDPOINT,
        access_date=access_date,
        row_count=1,
        description=(
            f"Gaia DR3 source {source_id}: "
            f"RA={ra:.5f} Dec={dec:.5f} RUWE={ruwe:.3f}"
        ),
    )

    return StellarParams(
        gaia_source_id=source_id,
        ra_deg=ra,
        dec_deg=dec,
        ruwe=ruwe,
        parallax_over_error=parallax_over_error,
        teff=UnitedArray(values=[teff], unit="K"),
        teff_uncertainty=UnitedArray(values=[teff_unc], unit="K"),
        radius=UnitedArray(values=[radius], unit="solRad"),
        radius_uncertainty=UnitedArray(values=[radius_unc], unit="solRad"),
        provenance=provenance,
    )
