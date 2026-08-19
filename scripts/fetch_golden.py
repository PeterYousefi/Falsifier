#!/usr/bin/env python3
"""
scripts/fetch_golden.py — manifest-driven golden fixture fetcher
=================================================================

Fetches every light curve listed in data/golden/MANIFEST.json, saves each
as a FITS file in data/golden/, computes its SHA-256, and writes it back
into the corresponding provenance sidecar.

Run this script ONCE per system (or when adding a new target).  Never run
it in CI — all golden FITS files must be committed.

Usage
-----
    python scripts/fetch_golden.py                  # fetch all missing
    python scripts/fetch_golden.py --target KIC11904151  # fetch one target
    python scripts/fetch_golden.py --force          # re-fetch even if present

Requirements
------------
    lightkurve >= 2.4
    astropy >= 5.0

Single-quarter entries
----------------------
Each entry with a scalar ``quarter`` field is fetched from the pinned MAST
product ID exactly as before.

Multi-quarter entries (stitched baselines)
------------------------------------------
Entries with a ``quarters`` list (e.g. ``"quarters": [1, 2, 3, 4, 5, 6, 7, 8]``)
download each quarter individually and stitch them into a single FITS file
with a monotonically increasing TIME column.  The stitching is gap-preserving:
inter-quarter gaps remain in the time axis so the baseline covers the full
calendar span.  Each quarter's flux is independently median-normalised before
concatenation; the merged flux is then re-normalised to a grand median of 1.0.

For multi-quarter entries, ``mast_product_id`` is interpreted as a list of
per-quarter product IDs in the same order as ``quarters``.  Leave as an empty
list ``[]`` to let lightkurve pick the default product for each quarter
(acceptable when the quarter is unique for that KIC ID and cadence).

Golden set growth
-----------------
To add a new system, append an entry to data/golden/MANIFEST.json.  The
fetch script will handle the rest.  Each entry must have:

    kic_id, common_name, quarter OR quarters, cadence, mast_product_id,
    fits_filename, provenance_filename, reference_doi, reference_citation,
    notes, (optional) eb_catalog dict for eclipsing binaries

After fetching, commit:
    data/golden/<fits_filename>
    data/golden/<provenance_filename>   (sha256 is now filled in)
"""

import argparse
import hashlib
import json
import pathlib
import sys
from datetime import date

GOLDEN_DIR = pathlib.Path(__file__).parent.parent / "data" / "golden"
MANIFEST_PATH = GOLDEN_DIR / "MANIFEST.json"


# ---------------------------------------------------------------------------
# SHA-256 helper
# ---------------------------------------------------------------------------

def _sha256_of_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Fetch one entry
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Single-quarter fetch helpers
# ---------------------------------------------------------------------------

def _find_pinned_index(results, pinned_id: str) -> int | None:
    """
    Return the index of the result row whose product filename contains
    *pinned_id*, or None if not found.  Tries the column names that lightkurve
    has used across versions.
    """
    tbl = results.table
    for col in ("#product_filename", "productFilename", "description"):
        if col in tbl.colnames:
            for i, val in enumerate(tbl[col]):
                if pinned_id in str(val):
                    return i
    return None


def _download_one_quarter(
    lk,
    kic_id: str,
    quarter: int,
    cadence: str,
    pinned_id: str | None,
) -> object | None:
    """
    Search MAST for one quarter of *kic_id*, optionally pinning to a specific
    product ID.  Returns a lightkurve LightCurve or None on failure.
    """
    results = lk.search_lightcurve(
        kic_id,
        mission="Kepler",
        quarter=quarter,
        cadence=cadence,
        author="Kepler",
    )
    if len(results) == 0:
        print(f"    WARNING: No MAST results for {kic_id} Q{quarter}.", file=sys.stderr)
        return None

    if pinned_id:
        idx = _find_pinned_index(results, pinned_id)
        if idx is None:
            available = []
            tbl = results.table
            for col in ("#product_filename", "productFilename", "description"):
                if col in tbl.colnames:
                    available = list(tbl[col])
                    break
            print(
                f"    WARNING: Pinned product ID '{pinned_id}' not found for "
                f"{kic_id} Q{quarter}.\n"
                f"    Available ({len(results)} rows): {available}\n"
                f"    Skipping this quarter.",
                file=sys.stderr,
            )
            return None
        lc = results[idx].download()
    else:
        lc = results[0].download()

    if lc is None:
        print(f"    WARNING: Download returned None for {kic_id} Q{quarter}.", file=sys.stderr)
    return lc


def _write_fits(fits_path: pathlib.Path, t_arr, f_arr, e_arr, q_arr) -> None:
    """Write arrays to the canonical FITS format expected by load_quiet_star."""
    import numpy as np
    from astropy.io import fits as _fits
    from astropy.table import Table as _Table

    tbl = _Table(
        [t_arr, f_arr, e_arr, q_arr],
        names=["TIME", "FLUX", "FLUX_ERR", "QUALITY"],
    )
    primary_hdu = _fits.PrimaryHDU()
    table_hdu = _fits.BinTableHDU(tbl, name="LIGHTCURVE")
    _fits.HDUList([primary_hdu, table_hdu]).writeto(str(fits_path), overwrite=True)


def _write_provenance(
    prov_path: pathlib.Path,
    entry: dict,
    sha256: str,
    row_count: int,
    extra: dict | None = None,
) -> None:
    """Write (or overwrite) the provenance sidecar for an entry."""
    provenance = {
        "target": entry["kic_id"],
        "common_name": entry["common_name"],
        "mission": "Kepler",
        "cadence": entry["cadence"],
        "pipeline_version": entry.get("pipeline_version", "SOC 9.3"),
        "time_system": "BKJD",
        "time_scale": "TDB",
        "time_reference": "BJD - 2454833.0",
        "flux_column": entry.get("flux_column", "SAP_FLUX"),
        "flux_unit": "e-/s",
        "access_date": date.today().isoformat(),
        "sha256": sha256,
        "row_count": row_count,
        "source_doi": entry["reference_doi"],
        "reference_doi": entry["reference_doi"],
        "reference_citation": entry["reference_citation"],
        "notes": entry.get("notes", ""),
    }
    # Single-quarter fields
    if "quarter" in entry:
        provenance["quarter"] = entry["quarter"]
        provenance["mast_product_id"] = entry.get("mast_product_id", "")
        provenance["mast_uri"] = entry.get("mast_uri", "")
    # Multi-quarter fields
    if "quarters" in entry:
        provenance["quarters"] = entry["quarters"]
        provenance["mast_product_ids"] = entry.get("mast_product_id", [])
    if extra:
        provenance.update(extra)
    if "eb_catalog" in entry:
        provenance["eb_catalog"] = entry["eb_catalog"]

    with open(prov_path, "w") as f:
        json.dump(provenance, f, indent=2)
        f.write("\n")


# ---------------------------------------------------------------------------
# Per-entry fetch dispatcher
# ---------------------------------------------------------------------------

def _fetch_entry(entry: dict, force: bool) -> bool:
    """
    Fetch a single manifest entry.  Returns True if the file was (re)fetched,
    False if it was already present and --force was not given.

    Dispatches to single-quarter or multi-quarter logic based on whether the
    entry has ``quarter`` (int) or ``quarters`` (list[int]).
    """
    fits_path = GOLDEN_DIR / entry["fits_filename"]
    prov_path = GOLDEN_DIR / entry["provenance_filename"]

    if fits_path.exists() and not force:
        print(f"  [skip] {fits_path.name} already exists (use --force to re-fetch)")
        return False

    try:
        import lightkurve as lk
    except ImportError:
        print("ERROR: lightkurve not installed.  Run: pip install 'lightkurve>=2.4'", file=sys.stderr)
        sys.exit(1)

    if "quarters" in entry:
        return _fetch_multi_quarter(entry, lk, fits_path, prov_path)
    else:
        return _fetch_single_quarter(entry, lk, fits_path, prov_path)


def _fetch_single_quarter(entry: dict, lk, fits_path: pathlib.Path, prov_path: pathlib.Path) -> bool:
    """Fetch one quarter pinned by mast_product_id."""
    import numpy as np

    print(f"  Searching MAST for {entry['kic_id']}, Q{entry['quarter']}, {entry['cadence']} ...")

    results = lk.search_lightcurve(
        entry["kic_id"],
        mission="Kepler",
        quarter=entry["quarter"],
        cadence=entry["cadence"],
        author="Kepler",
    )

    if len(results) == 0:
        print(f"  ERROR: No MAST results for {entry['kic_id']} Q{entry['quarter']}.", file=sys.stderr)
        return False

    pinned_id = entry["mast_product_id"]
    idx = _find_pinned_index(results, pinned_id)

    if idx is None:
        available = []
        tbl = results.table
        for col in ("#product_filename", "productFilename", "description", "target_name"):
            if col in tbl.colnames:
                available = list(tbl[col])
                break
        print(
            f"  ERROR: Pinned product ID '{pinned_id}' not found in MAST results.\n"
            f"  Available identifiers ({len(results)} rows): {available}\n"
            f"  Update mast_product_id in data/golden/MANIFEST.json to match one of\n"
            f"  the above, then re-run.",
            file=sys.stderr,
        )
        return False

    print(f"  Pinned match: index {idx} of {len(results)} results")
    lc = results[idx].download()

    if lc is None:
        print(f"  ERROR: Download returned None for {entry['kic_id']}.", file=sys.stderr)
        return False

    fits_path.parent.mkdir(parents=True, exist_ok=True)

    t_arr = np.asarray(lc.time.bkjd, dtype=np.float64)
    f_arr = np.asarray(lc.flux.value, dtype=np.float64)
    e_arr = np.asarray(lc.flux_err.value, dtype=np.float64)
    q_arr = np.asarray(lc.quality, dtype=np.int32)

    _write_fits(fits_path, t_arr, f_arr, e_arr, q_arr)
    print(f"  Saved: {fits_path.name}  ({len(lc)} cadences)")

    sha256 = _sha256_of_file(fits_path)
    _write_provenance(prov_path, entry, sha256, len(lc))
    print(f"  Provenance: {prov_path.name}  (sha256={sha256[:16]}...)")
    return True


def _fetch_multi_quarter(entry: dict, lk, fits_path: pathlib.Path, prov_path: pathlib.Path) -> bool:
    """
    Download multiple quarters, stitch them into a single FITS file.

    Each quarter is independently median-normalised before concatenation.
    The merged array is then re-normalised to grand median = 1.0.
    Only quality == 0 and finite cadences are kept within each quarter.

    The ``mast_product_id`` field for multi-quarter entries is a list of
    per-quarter pinned product IDs (parallel to ``quarters``).  An empty list
    or shorter list means those quarters are fetched without pinning.
    """
    import numpy as np

    quarters: list[int] = entry["quarters"]
    pinned_ids: list[str] = entry.get("mast_product_id", [])
    cadence: str = entry["cadence"]
    kic_id: str = entry["kic_id"]

    print(
        f"  Fetching {len(quarters)} quarters for {kic_id} "
        f"(Q{quarters[0]}–Q{quarters[-1]}, {cadence}) ..."
    )

    t_parts: list[np.ndarray] = []
    f_parts: list[np.ndarray] = []
    e_parts: list[np.ndarray] = []
    q_parts: list[np.ndarray] = []
    quarters_fetched: list[int] = []

    for i, q in enumerate(quarters):
        pinned = pinned_ids[i] if i < len(pinned_ids) else None
        print(f"    Q{q} ...", end=" ", flush=True)
        lc = _download_one_quarter(lk, kic_id, q, cadence, pinned)
        if lc is None:
            print("SKIP")
            continue

        t = np.asarray(lc.time.bkjd, dtype=np.float64)
        f = np.asarray(lc.flux.value, dtype=np.float64)
        e = np.asarray(lc.flux_err.value, dtype=np.float64)
        qf = np.asarray(lc.quality, dtype=np.int32)

        # Per-quarter quality mask and normalisation
        mask = np.isfinite(t) & np.isfinite(f) & np.isfinite(e) & (qf == 0)
        t, f, e, qf = t[mask], f[mask], e[mask], qf[mask]
        if len(t) < 10:
            print(f"SKIP (only {len(t)} good cadences after quality mask)")
            continue

        med = float(np.nanmedian(f))
        if med == 0.0 or not np.isfinite(med):
            print("SKIP (zero or NaN median flux)")
            continue
        f = f / med
        e = e / abs(med)

        t_parts.append(t)
        f_parts.append(f)
        e_parts.append(e)
        q_parts.append(qf)
        quarters_fetched.append(q)
        print(f"OK ({len(t)} cadences)")

    if not t_parts:
        print(f"  ERROR: No usable quarters fetched for {kic_id}.", file=sys.stderr)
        return False

    # Concatenate and sort by time (quarters should already be ordered, but be safe)
    t_all = np.concatenate(t_parts)
    f_all = np.concatenate(f_parts)
    e_all = np.concatenate(e_parts)
    q_all = np.concatenate(q_parts)
    order = np.argsort(t_all)
    t_all, f_all, e_all, q_all = t_all[order], f_all[order], e_all[order], q_all[order]

    # Grand re-normalisation: median of the full stitched flux → 1.0
    grand_med = float(np.median(f_all))
    if grand_med > 0.0 and np.isfinite(grand_med):
        f_all = f_all / grand_med
        e_all = e_all / grand_med

    baseline_days = float(t_all[-1] - t_all[0])
    n_cadences = len(t_all)
    print(
        f"  Stitched {len(quarters_fetched)} quarters: "
        f"{n_cadences} cadences, baseline {baseline_days:.1f} d"
    )

    fits_path.parent.mkdir(parents=True, exist_ok=True)
    _write_fits(fits_path, t_all, f_all, e_all, q_all)
    print(f"  Saved: {fits_path.name}")

    sha256 = _sha256_of_file(fits_path)
    _write_provenance(
        prov_path,
        entry,
        sha256,
        n_cadences,
        extra={
            "quarters_fetched": quarters_fetched,
            "baseline_days": round(baseline_days, 1),
        },
    )
    print(f"  Provenance: {prov_path.name}  (sha256={sha256[:16]}...)")
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1].strip())
    parser.add_argument(
        "--target",
        metavar="KIC_ID",
        help="Fetch only this KIC ID (e.g. KIC11904151).  Fetches all if omitted.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-fetch even if the FITS file already exists on disk.",
    )
    args = parser.parse_args()

    if not MANIFEST_PATH.exists():
        print(f"ERROR: Manifest not found: {MANIFEST_PATH}", file=sys.stderr)
        sys.exit(1)

    with open(MANIFEST_PATH) as f:
        manifest = json.load(f)

    entries = manifest["golden_set"]

    if args.target:
        target_norm = args.target.upper().replace(" ", "")
        entries = [
            e for e in entries
            if e["kic_id"].upper().replace(" ", "") == target_norm
        ]
        if not entries:
            print(f"ERROR: Target '{args.target}' not found in manifest.", file=sys.stderr)
            sys.exit(1)

    fetched = 0
    for entry in entries:
        print(f"\n[{entry['kic_id']}] {entry['common_name']}")
        if _fetch_entry(entry, force=args.force):
            fetched += 1

    print(f"\nDone. {fetched}/{len(entries)} file(s) fetched.")
    if fetched > 0:
        print("\nNext steps:")
        print("  git add data/golden/")
        print("  git commit -m 'chore: update golden light curves'")


if __name__ == "__main__":
    main()
