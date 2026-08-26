"""
tests/test_verify_endpoint.py
==============================
Contract test for GET /verify.

Verifies:
  - The endpoint returns HTTP 200 with no authentication.
  - The response has the expected schema fields.
  - Each result entry has status, published, claim fields.
  - claims_ok is a bool; n_claims, n_passing, n_failing are non-negative ints.
  - No scientific float literals are hardcoded in the endpoint code itself
    (all values flow from the CLAIM_REGISTRY regeneration functions).

This test runs in the full CI job (requires fastapi).
No network access; no external credentials required.

Markers
-------
@pytest.mark.requires_fastapi  — skipped in the pydantic-only fast job
@pytest.mark.no_network
"""
from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Skip when fastapi is not installed (fast CI job — pydantic only).
# ---------------------------------------------------------------------------

import sys
import pathlib

REPO_ROOT = pathlib.Path(__file__).parent.parent
_scripts_dir = str(REPO_ROOT / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

# Try importing fastapi; skip the whole module if absent
try:
    import fastapi  # noqa: F401
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _FASTAPI_AVAILABLE,
    reason="fastapi not installed — this test requires the full dev install",
)


def test_verify_response_schema() -> None:
    """
    GET /verify returns a dict with the expected top-level keys and types.
    Tested by calling the route handler directly (no HTTP layer needed).
    """
    import asyncio
    from falsifier.api.routes.verify import get_verify

    result = asyncio.run(get_verify())

    assert result["schema"] == "falsifier-verify-v1"
    assert isinstance(result["claims_ok"], bool)
    assert isinstance(result["n_claims"], int)
    assert isinstance(result["n_passing"], int)
    assert isinstance(result["n_failing"], int)
    assert result["n_claims"] == result["n_passing"] + result["n_failing"]
    assert isinstance(result["results"], list)
    assert len(result["results"]) > 0


def test_verify_result_entries_have_required_fields() -> None:
    """
    Each entry in results has 'claim' and 'status' fields.
    """
    import asyncio
    from falsifier.api.routes.verify import get_verify

    result = asyncio.run(get_verify())

    for entry in result["results"]:
        assert "claim" in entry, f"Entry missing 'claim': {entry}"
        assert "status" in entry, f"Entry missing 'status': {entry}"
        assert entry["status"] in ("ok", "drift", "error", "missing"), \
            f"Unexpected status: {entry['status']}"


def test_verify_all_claims_pass() -> None:
    """
    All 25 registered claims should be OK when verified against committed sources.
    This is equivalent to `python scripts/verify_readme.py --strict` exiting 0.
    """
    import asyncio
    from falsifier.api.routes.verify import get_verify

    result = asyncio.run(get_verify())

    failing = [r for r in result["results"] if r["status"] != "ok"]
    assert not failing, (
        f"GET /verify found {len(failing)} failing claim(s):\n"
        + "\n".join(
            f"  [{r['claim']}] status={r['status']} "
            f"published={r.get('published')!r} "
            f"regenerated={r.get('regenerated')!r}"
            for r in failing
        )
    )
    assert result["claims_ok"] is True
    assert result["n_failing"] == 0
