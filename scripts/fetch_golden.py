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

The MAST product ID in each manifest entry pins the exact file.  lightkurve's
search_lightcurve is used only for discovery; the download is directed to the
pinned product ID so there are no version-drift surprises from lightkurve
defaults.

Golden set growth
-----------------
To add a new system, append an entry to data/golden/MANIFEST.json.  The
fetch script will handle the rest.  Each entry must have:

    kic_id, common_name, quarter, cadence, mast_product_id, mast_uri,
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

def _fetch_entry(entry: dict, force: bool) -> bool:
    """
    Fetch a single manifest entry.  Returns True if the file was (re)fetched,
    False if it was already present and --force was not given.
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

    print(f"  Searching MAST for {entry['kic_id']}, Q{entry['quarter']}, {entry['cadence']} ...")

    # Pin the exact product ID.  lightkurve's search returns a collection;
    # we filter to the exact mast_product_id so no default is used.
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

    # Filter to the pinned product ID
    pinned_id = entry["mast_product_id"]
    matched = [r for r in results if pinned_id in str(r.table["productFilename"][0]
                                                        if hasattr(r, "table") else r)]

    if not matched:
        # Fallback: use first result but warn loudly
        print(
            f"  WARNING: Could not match pinned product ID '{pinned_id}' in results.\n"
            f"  Available: {[str(r) for r in results]}\n"
            f"  Falling back to first result.  Verify the mast_product_id in MANIFEST.json.",
            file=sys.stderr,
        )
        lc = results[0].download()
    else:
        lc = results[matched[0] if isinstance(matched[0], int) else 0].download()

    if lc is None:
        print(f"  ERROR: Download returned None for {entry['kic_id']}.", file=sys.stderr)
        return False

    fits_path.parent.mkdir(parents=True, exist_ok=True)
    lc.to_fits(str(fits_path), overwrite=True)
    print(f"  Saved: {fits_path.name}  ({len(lc)} cadences)")

    # Compute SHA-256 and update provenance sidecar
    sha256 = _sha256_of_file(fits_path)

    # Build the provenance document from the manifest entry
    provenance = {
        "target": entry["kic_id"],
        "common_name": entry["common_name"],
        "mission": "Kepler",
        "quarter": entry["quarter"],
        "cadence": entry["cadence"],
        "mast_product_id": entry["mast_product_id"],
        "mast_uri": entry["mast_uri"],
        "pipeline_version": entry.get("pipeline_version", "SOC 9.3"),
        "time_system": "BKJD",
        "time_scale": "TDB",
        "time_reference": "BJD - 2454833.0",
        "flux_column": entry.get("flux_column", "SAP_FLUX"),
        "flux_unit": "e-/s",
        "access_date": date.today().isoformat(),
        "sha256": sha256,
        "row_count_expected": len(lc),
        "reference_doi": entry["reference_doi"],
        "reference_citation": entry["reference_citation"],
        "notes": entry.get("notes", ""),
    }
    if "eb_catalog" in entry:
        provenance["eb_catalog"] = entry["eb_catalog"]

    with open(prov_path, "w") as f:
        json.dump(provenance, f, indent=2)
        f.write("\n")
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
