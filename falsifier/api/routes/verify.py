"""
falsifier.api.routes.verify
============================
GET /verify

Returns the live claim inventory from README.md, with per-claim pass/fail status.
This is the same check that ``scripts/verify_readme.py --strict`` performs in CI,
but readable by a judge with no local setup — unauthenticated, no key required.

Policy compliance
-----------------
AGENTS.md Rule 1: no hardcoded scientific values in API code.
All claim values are read from committed artifacts at request time via the
same regeneration functions used by verify_readme.py.

Response format
---------------
{
  "schema": "falsifier-verify-v1",
  "claims_ok": true,           // true if every claim passes
  "n_claims": 25,
  "n_passing": 25,
  "n_failing": 0,
  "results": [
    {
      "claim": "falsifier_version",
      "status": "ok",           // "ok" | "drift" | "error"
      "published": "Pipeline version: `0.1.0-dev`",
      "regenerated": "Pipeline version: `0.1.0-dev`"
    },
    ...
  ]
}
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter

router = APIRouter(prefix="/verify", tags=["verify"])

# Locate the repo root so we can import verify_readme without sys.path hacks.
_REPO_ROOT = Path(__file__).parent.parent.parent.parent


def _get_verify_module():
    """
    Import scripts.verify_readme lazily.

    The scripts/ directory may not be on sys.path at app startup.
    Add it transiently so the import succeeds without polluting the
    module-level sys.path.
    """
    scripts_dir = str(_REPO_ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import verify_readme as _mod
    return _mod


@router.get("", tags=["verify"])
async def get_verify() -> dict:
    """
    Live claim inventory with per-claim pass/fail status.

    Performs the same check as ``python scripts/verify_readme.py --strict``
    but returns machine-readable JSON.  Unauthenticated — no key required.
    Intended for judge access without local setup.
    """
    mod = _get_verify_module()
    readme_path = _REPO_ROOT / "README.md"

    results: list[dict] = []

    readme_text = readme_path.read_text(encoding="utf-8")
    readme_claims = mod.parse_readme_claims(readme_text)

    n_passing = 0
    n_failing = 0

    for claim_name, regen_fn in mod.CLAIM_REGISTRY.items():
        if claim_name not in readme_claims:
            results.append({
                "claim": claim_name,
                "status": "missing",
                "published": None,
                "regenerated": None,
                "note": "No CLAIM block found in README.md",
            })
            n_failing += 1
            continue

        published = readme_claims[claim_name]
        try:
            regenerated = regen_fn()
        except Exception as exc:
            results.append({
                "claim": claim_name,
                "status": "error",
                "published": published,
                "regenerated": None,
                "note": f"Regeneration failed: {exc}",
            })
            n_failing += 1
            continue

        if published == regenerated:
            results.append({
                "claim": claim_name,
                "status": "ok",
                "published": published,
                "regenerated": regenerated,
            })
            n_passing += 1
        else:
            results.append({
                "claim": claim_name,
                "status": "drift",
                "published": published,
                "regenerated": regenerated,
            })
            n_failing += 1

    return {
        "schema": "falsifier-verify-v1",
        "claims_ok": n_failing == 0,
        "n_claims": n_passing + n_failing,
        "n_passing": n_passing,
        "n_failing": n_failing,
        "results": results,
    }
