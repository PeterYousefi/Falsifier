#!/usr/bin/env python3
"""
scripts/check_badge_owner.py
==============================
CI check: every github.com URL in README.md must reference the actual
repository owner/name, not a stale fork or a placeholder name.

Usage
-----
    python scripts/check_badge_owner.py [--readme README.md] [--owner OWNER] [--repo REPO]

The owner and repo default to the values detected from ``git remote get-url origin``.
Override with --owner / --repo for environments where git is unavailable.

Exit codes
----------
  0  All github.com URLs reference the correct owner/repo.
  1  One or more URLs reference a different owner/repo.
  2  Could not determine the expected owner/repo (no git remote, no override).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

# Matches github.com/<owner>/<repo> in any URL scheme
_GITHUB_URL_RE = re.compile(
    r"https?://github\.com/([^/\s\"'\)]+)/([^/\s\"'\)#]+)"
)


def _detect_owner_repo_from_git() -> tuple[str, str] | None:
    """
    Run ``git remote get-url origin`` and parse owner/repo.

    Returns (owner, repo) on success, None if git is unavailable or the remote
    is not a github.com URL.
    """
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            timeout=10,
        )
        if result.returncode != 0:
            return None
        remote_url = result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    # HTTPS:  https://github.com/owner/repo.git
    # SSH:    git@github.com:owner/repo.git
    https_m = _GITHUB_URL_RE.search(remote_url)
    if https_m:
        owner = https_m.group(1)
        repo = https_m.group(2).removesuffix(".git")
        return owner, repo

    ssh_m = re.search(r"git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$", remote_url)
    if ssh_m:
        return ssh_m.group(1), ssh_m.group(2)

    return None


def check_readme_urls(
    readme_path: Path,
    expected_owner: str,
    expected_repo: str,
) -> list[str]:
    """
    Scan README.md for github.com URLs and report those that reference
    a different owner/repo than expected.

    Returns a list of error strings.  Empty list = all OK.
    """
    text = readme_path.read_text(encoding="utf-8")
    errors: list[str] = []

    for lineno, line in enumerate(text.splitlines(), start=1):
        for m in _GITHUB_URL_RE.finditer(line):
            owner = m.group(1)
            repo = m.group(2).removesuffix(".git")
            if owner != expected_owner or repo != expected_repo:
                errors.append(
                    f"{readme_path.name}:{lineno}: "
                    f"github.com URL references {owner}/{repo!r} "
                    f"but expected {expected_owner}/{expected_repo!r} "
                    f"— update to match the real repository."
                )

    return errors


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Check that every github.com URL in README.md names the correct "
            "owner/repo for this repository."
        )
    )
    p.add_argument(
        "--readme",
        type=Path,
        default=REPO_ROOT / "README.md",
        help="Path to README.md (default: repo root README.md)",
    )
    p.add_argument(
        "--owner",
        default=None,
        help="Expected GitHub owner (default: auto-detect from git remote)",
    )
    p.add_argument(
        "--repo",
        default=None,
        help="Expected GitHub repo name (default: auto-detect from git remote)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # Determine expected owner/repo
    if args.owner and args.repo:
        expected_owner = args.owner
        expected_repo = args.repo
    else:
        detected = _detect_owner_repo_from_git()
        if detected is None:
            print(
                "ERROR: Could not detect owner/repo from git remote.\n"
                "Pass --owner and --repo explicitly.",
                file=sys.stderr,
            )
            return 2
        expected_owner, expected_repo = detected

    print(f"Expected owner/repo: {expected_owner}/{expected_repo}")

    if not args.readme.exists():
        print(f"ERROR: README not found: {args.readme}", file=sys.stderr)
        return 1

    errors = check_readme_urls(args.readme, expected_owner, expected_repo)

    if not errors:
        print(f"OK — all github.com URLs in {args.readme.name} reference {expected_owner}/{expected_repo}")
        return 0

    for err in errors:
        print(f"ERROR: {err}", file=sys.stderr)
    print(
        f"\n{len(errors)} URL(s) reference the wrong owner/repo.  "
        "Update them to match this repository.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
