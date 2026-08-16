# falsifier/pipeline/contracts/__init__.py
"""
falsifier.pipeline.contracts
==============================
Re-exports all public pipeline contract models.

Import any contract directly from this package:

    from falsifier.pipeline.contracts import VetOutput, ClassifyOutput, TCE

Design invariants enforced here at import time
----------------------------------------------
- ``ClassifyOutput`` must not have a ``disposition`` field (rankers rank, vetters vet).
- ``RetrieveOutput`` must not have a ``status`` field (pipeline is sync, API layer owns state).
- ``DisequilibriumOutput`` must not have a ``disposition`` field (screening only).
"""

from .manifest import (
    ArtifactRef,
    DatasetProvenance,
    StageManifest,
    UnitedArray,
)
from .ingest import (
    IngestInput,
    IngestOutput,
    LightCurveSegment,
    StellarParams,
)
from .detrend import (
    DetrendInput,
    DetrendOutput,
    DetrendedSegment,
)
from .search import (
    SearchInput,
    SearchOutput,
    TCE,
)
from .vet import (
    Disposition,
    VetInput,
    VetOutput,
    VettingTestName,
    VettingTestOutcome,
    VettingTestResult,
)
from .classify import (
    CalibrationMeta,
    ClassifyInput,
    ClassifyOutput,
)
from .retrieve import (
    RetrievalConfig,
    RetrievedSpectrum,
    RetrieveInput,
    RetrieveOutput,
)
from .disequilibrium import (
    ChemicalSpeciesProfile,
    DisequilibriumInput,
    DisequilibriumOutput,
    FastChemConfig,
    GibbsMinimisationResult,
)

__all__ = [
    # manifest
    "ArtifactRef",
    "DatasetProvenance",
    "StageManifest",
    "UnitedArray",
    # ingest
    "IngestInput",
    "IngestOutput",
    "LightCurveSegment",
    "StellarParams",
    # detrend
    "DetrendInput",
    "DetrendOutput",
    "DetrendedSegment",
    # search
    "SearchInput",
    "SearchOutput",
    "TCE",
    # vet
    "Disposition",
    "VetInput",
    "VetOutput",
    "VettingTestName",
    "VettingTestOutcome",
    "VettingTestResult",
    # classify
    "CalibrationMeta",
    "ClassifyInput",
    "ClassifyOutput",
    # retrieve  (JobStatus is deliberately absent — it belongs in the API layer)
    "RetrievalConfig",
    "RetrievedSpectrum",
    "RetrieveInput",
    "RetrieveOutput",
    # disequilibrium
    "ChemicalSpeciesProfile",
    "DisequilibriumInput",
    "DisequilibriumOutput",
    "FastChemConfig",
    "GibbsMinimisationResult",
]

# ---------------------------------------------------------------------------
# CI gate assertions (enforced at import time, not only in tests)
# ---------------------------------------------------------------------------

assert "disposition" not in ClassifyOutput.model_fields, (
    "ClassifyOutput must not have a 'disposition' field.  "
    "Rankers rank; vetters vet.  Read disposition from VetOutput."
)

assert "status" not in RetrieveOutput.model_fields, (
    "RetrieveOutput must not have a 'status' field.  "
    "Pipeline contracts are synchronous.  Job state belongs in the API layer."
)

assert "disposition" not in DisequilibriumOutput.model_fields, (
    "DisequilibriumOutput must not have a 'disposition' field.  "
    "This stage is a thermochemical screening tool only.  "
    "AGENTS.md Locked Claim: not a biosignature detector."
)
