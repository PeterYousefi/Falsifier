"""
falsifier.pipeline.io
======================
Serialisation helpers for pipeline artifacts.

  input_hash(model)             — SHA-256 of serialised model JSON
  artifact_write(model, dir)    — write model to disk, return ArtifactRef
  artifact_read(ref, cls)       — read + verify SHA-256, return validated model
  ArtifactCorruptedError        — raised when SHA-256 check fails
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from .contracts.manifest import ArtifactRef

T = TypeVar("T", bound=BaseModel)


class ArtifactCorruptedError(RuntimeError):
    """
    Raised when the SHA-256 of a file on disk does not match the value
    recorded in its ``ArtifactRef``.  The artifact must be deleted and the
    upstream stage re-run.
    """

    def __init__(self, message: str, *, path: Path, expected: str, actual: str) -> None:
        super().__init__(message)
        self.path = path
        self.expected = expected
        self.actual = actual

    def __str__(self) -> str:
        return (
            f"{super().__str__()}\n"
            f"  path     : {self.path}\n"
            f"  expected : {self.expected}\n"
            f"  actual   : {self.actual}"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def input_hash(model: BaseModel) -> str:
    """
    Return the SHA-256 hex digest of ``model.model_dump_json()``.

    Used to detect cache hits: if the upstream output's hash matches a stored
    artifact's ``StageManifest.input_hash``, the stage body can be skipped.
    """
    return hashlib.sha256(
        model.model_dump_json().encode("utf-8")
    ).hexdigest()


def artifact_write(model: BaseModel, directory: Path) -> ArtifactRef:
    """
    Serialise *model* to a deterministic JSON filename under *directory*.

    Filename format::

        {stage}_{pipeline_run_id}_{sha256[:8]}.json

    where ``stage`` comes from ``model.manifest.stage`` and
    ``pipeline_run_id`` from ``model.input.pipeline_run_id``.

    Computes the SHA-256 of the written file bytes and includes it in the
    returned ``ArtifactRef``.
    """
    stage = model.manifest.stage  # type: ignore[attr-defined]
    run_id = model.input.pipeline_run_id  # type: ignore[attr-defined]

    # Compute a short content tag from the serialised bytes before writing
    content = model.model_dump_json(indent=2)
    short_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:8]

    filename = f"{stage}_{run_id}_{short_hash}.json"
    path = (directory / filename).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(content, encoding="utf-8")
    sha256 = _sha256_file(path)

    return ArtifactRef(
        path=path,
        sha256=sha256,
        stage=stage,
        pipeline_run_id=run_id,
    )


def artifact_read(ref: ArtifactRef, model_class: type[T]) -> T:
    """
    Read and validate a pipeline artifact from disk.

    1. Reads the file at ``ref.path``.
    2. Verifies the SHA-256 of the file bytes against ``ref.sha256``;
       raises ``ArtifactCorruptedError`` if they differ.
    3. Deserialises with ``model_class.model_validate_json()``.
    """
    path = ref.path
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != ref.sha256:
        raise ArtifactCorruptedError(
            f"Artifact integrity check failed: {path.name}",
            path=path,
            expected=ref.sha256,
            actual=actual,
        )
    return model_class.model_validate_json(raw.decode("utf-8"))
