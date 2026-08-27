"""
falsifier.pipeline.ingest.cache
=================================
Content-addressed, sidecar-manifest cache for ingest artifacts.

Design
------
Every cached artifact lives in ``<cache_root>/<sha256[:2]>/<sha256>.{ext}``
where ``sha256`` is the hex digest of the *normalised query string*.  A JSON
sidecar ``<sha256>.manifest.json`` lives alongside every artifact and records:

  - ``source_doi``    — citable DOI
  - ``source_url``    — full MAST URI or TAP endpoint URL
  - ``access_date``   — ISO-8601 date of the original fetch
  - ``row_count``     — row/cadence count
  - ``description``   — human-readable label
  - ``sha256``        — SHA-256 of the artifact file bytes (integrity)
  - ``query_hash``    — SHA-256 of the normalised query (cache key)
  - ``retrieved_at``  — ISO-8601 datetime of when the item entered the cache

Cache hit
---------
``get()`` returns ``(path, manifest_dict, retrieved_at)`` when a valid
cached artifact exists.  The caller can enforce ``max_age`` (a
``datetime.timedelta``): if the artifact is older than ``max_age`` *and*
``offline=False``, ``get()`` returns ``None`` (miss) so the caller refetches.
If ``offline=True`` and the artifact is stale, ``StaleArtifactError`` is
raised rather than silently serving stale data.

Integrity
---------
``get()`` verifies the SHA-256 of the cached file against the sidecar before
returning.  A mismatch raises ``CacheCorruptedError``.

Offline mode
------------
When ``offline=True`` is passed to ``get()``, any cache miss raises
``IngestError`` rather than returning ``None``.  This is what makes the
golden regression tests hermetic.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

from .exceptions import (
    CacheCorruptedError,
    IngestError,
    StaleArtifactError,
)


# ---------------------------------------------------------------------------
# Query normalisation — deterministic cache key
# ---------------------------------------------------------------------------

def _normalise(query: str) -> str:
    """
    Normalise a query string to a canonical, whitespace-collapsed, lower-cased
    form so that semantically equivalent queries always produce the same hash.
    """
    nfc = unicodedata.normalize("NFC", query)
    return " ".join(nfc.lower().split())


def query_hash(query: str) -> str:
    """Return the SHA-256 hex digest of the normalised *query* string."""
    return hashlib.sha256(_normalise(query).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Sidecar manifest helpers
# ---------------------------------------------------------------------------

def _sidecar_path(artifact_path: Path) -> Path:
    return artifact_path.with_suffix(artifact_path.suffix + ".manifest.json")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def write_sidecar(
    artifact_path: Path,
    *,
    source_doi: str,
    source_url: str,
    access_date: datetime.date,
    row_count: int,
    description: str,
    query: str,
) -> dict[str, Any]:
    """
    Write a JSON sidecar manifest next to *artifact_path* and return the
    manifest dict.  Must be called immediately after writing the artifact so
    the SHA-256 reflects the committed bytes.
    """
    sha256 = _sha256_file(artifact_path)
    qhash = query_hash(query)
    now = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()

    manifest: dict[str, Any] = {
        "source_doi": source_doi,
        "source_url": source_url,
        "access_date": access_date.isoformat(),
        "row_count": row_count,
        "description": description,
        "sha256": sha256,
        "query_hash": qhash,
        "retrieved_at": now,
    }

    sidecar = _sidecar_path(artifact_path)
    sidecar.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def read_sidecar(artifact_path: Path) -> dict[str, Any] | None:
    """
    Read the sidecar manifest for *artifact_path*.  Returns ``None`` if the
    sidecar does not exist.
    """
    sidecar = _sidecar_path(artifact_path)
    if not sidecar.exists():
        return None
    with open(sidecar, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Cache — get / put
# ---------------------------------------------------------------------------

class IngestCache:
    """
    Content-addressed on-disk cache for ingest artifacts.

    Parameters
    ----------
    root : Path
        Root directory for cached artifacts.  Created if absent.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def _artifact_dir(self, qhash: str) -> Path:
        """Two-level sharding: ``<root>/<qhash[:2]>/``."""
        return self.root / qhash[:2]

    def artifact_path(self, qhash: str, suffix: str) -> Path:
        """
        Canonical path for an artifact with the given query hash and file
        extension (e.g. ``".fits"`` or ``".parquet"``).
        """
        d = self._artifact_dir(qhash)
        return d / f"{qhash}{suffix}"

    # ------------------------------------------------------------------
    # get
    # ------------------------------------------------------------------

    def get(
        self,
        query: str,
        suffix: str,
        *,
        max_age: datetime.timedelta | None = None,
        offline: bool = False,
    ) -> tuple[Path, dict[str, Any], datetime.datetime] | None:
        """
        Look up a cached artifact by normalised *query* string.

        Returns
        -------
        (path, manifest_dict, retrieved_at) on cache hit.
        ``None`` on cache miss (when ``offline=False``).

        Raises
        ------
        CacheCorruptedError
            If the file exists but its SHA-256 does not match the sidecar.
        StaleArtifactError
            If the artifact exceeds *max_age* and ``offline=True``.
        IngestError
            If the cache is empty and ``offline=True``.
        """
        qhash = query_hash(query)
        path = self.artifact_path(qhash, suffix)
        sidecar = _sidecar_path(path)

        if not path.exists() or not sidecar.exists():
            if offline:
                raise IngestError(
                    f"Cache miss in offline mode for query: {query!r}\n"
                    f"  hash    : {qhash}\n"
                    f"  expected: {path}"
                )
            return None

        manifest = read_sidecar(path)
        assert manifest is not None  # sidecar.exists() was checked above

        # Integrity check
        actual_sha256 = _sha256_file(path)
        if actual_sha256 != manifest.get("sha256", ""):
            raise CacheCorruptedError(
                f"SHA-256 mismatch for cached artifact {path.name}.\n"
                f"Delete it and re-run ingest to refetch.",
            )

        # Parse retrieved_at
        retrieved_at = datetime.datetime.fromisoformat(manifest["retrieved_at"])

        # max_age check
        if max_age is not None:
            age = datetime.datetime.now(tz=datetime.timezone.utc) - retrieved_at
            if age > max_age:
                if offline:
                    raise StaleArtifactError(
                        f"Cached artifact for {query!r} is {age} old "
                        f"(max_age={max_age}), and offline=True prevents refetch.\n"
                        f"  path: {path}"
                    )
                return None  # stale; caller will refetch

        return path, manifest, retrieved_at

    # ------------------------------------------------------------------
    # put
    # ------------------------------------------------------------------

    def put(
        self,
        query: str,
        suffix: str,
        data: bytes,
        *,
        source_doi: str,
        source_url: str,
        access_date: datetime.date,
        row_count: int,
        description: str,
    ) -> tuple[Path, dict[str, Any]]:
        """
        Write *data* to the cache and record provenance in the sidecar.

        Returns
        -------
        (path, manifest_dict)
        """
        qhash = query_hash(query)
        path = self.artifact_path(qhash, suffix)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write: write to a temp file in the same directory, then
        # rename into place.  This ensures that a reader never sees a
        # partially-written artifact, and that a crash between write and
        # rename leaves no file for cache.get() to find (the sidecar is
        # written only after the rename succeeds).
        tmp_fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=suffix + ".tmp")
        try:
            try:
                os.write(tmp_fd, data)
            finally:
                os.close(tmp_fd)
            os.replace(tmp_name, path)  # atomic on POSIX; best-effort on Windows
        except BaseException:
            # Clean up the temp file so it does not linger in the cache
            # directory and confuse future runs.
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

        manifest = write_sidecar(
            path,
            source_doi=source_doi,
            source_url=source_url,
            access_date=access_date,
            row_count=row_count,
            description=description,
            query=query,
        )
        return path, manifest
