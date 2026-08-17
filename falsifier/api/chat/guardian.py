"""
falsifier.api.chat.guardian
============================
Granite Guardian output-safety screening.

Architecture
------------
Granite Guardian (ibm-granite/granite-guardian-3.1-2b) is loaded lazily as a
local HuggingFace transformers model.  Every LLM output is screened before it
reaches the client.

The screen() function:

1. Attempts to load the model from the local HuggingFace cache.
2. If the model is not available (no GPU, not downloaded, transformers not
   installed) it falls back to a rule-based heuristic that flags:
   - fabricated numeric claims not backed by tool calls
   - disallowed biosignature language
3. Returns a GuardianVerdict with:
   - safe: bool
   - risk_label: one of "safe", "fabricated_number", "biosignature_claim",
     "hallucination", "off_topic"
   - screened: the (possibly redacted) text safe to show to the user
   - original: the raw LLM output (never shown to user if safe=False)

If safe=False the caller must substitute the templated explanation from
stage_explanations.json rather than showing the original text.

AGENTS.md enforcement
---------------------
Locked claim: "This project is not a biosignature detector.
No exoplanet biosignature has ever been confirmed."
Any output that introduces a biosignature claim is blocked unconditionally.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

REPO_ROOT = Path(__file__).parent.parent.parent.parent
_EXPLANATIONS_PATH = (
    REPO_ROOT / "data" / "artifacts" / "explanations" / "stage_explanations.json"
)

# ---------------------------------------------------------------------------
# Heuristic patterns (used when Guardian model is unavailable)
# ---------------------------------------------------------------------------

# Phrases that constitute an impermissible biosignature claim.
# Each pattern is (pattern, negation_ok) where negation_ok=True means the
# match is allowed when preceded by "not a" or "no ... confirmed".
_BIOSIGNATURE_PATTERNS: list[tuple[re.Pattern, bool]] = [
    # "biosignature" alone is suspicious, but the locked non-claim phrase
    # "not a biosignature detector" is explicitly allowed.
    (re.compile(r"\bbiosignature\b", re.IGNORECASE), True),
    (re.compile(r"\blife\s+detected\b", re.IGNORECASE), False),
    (re.compile(r"\bsigns?\s+of\s+life\b", re.IGNORECASE), False),
    (re.compile(r"\bhabitable\s+and\s+inhabited\b", re.IGNORECASE), False),
    (re.compile(r"\bconfirmed\s+(?:alien|extraterrestrial)\b", re.IGNORECASE), False),
]

# Allowlisted phrases: text containing ONLY these uses of "biosignature" is safe.
_BIOSIGNATURE_ALLOWLIST = [
    re.compile(r"not\s+a\s+biosignature\s+detector", re.IGNORECASE),
    re.compile(r"no\s+exoplanet\s+biosignature\s+has\s+ever\s+been\s+confirmed", re.IGNORECASE),
    re.compile(r"this\s+project\s+is\s+not\s+a\s+biosignature", re.IGNORECASE),
]

# A fabricated number: a digit sequence NOT preceded by a tool-call citation
# "[source: <tool>(<args>)]".  We check for numbers that look like scientific
# results (floats with ≥3 sig-figs, or explicit unit phrasing) but have no
# adjacent source citation.
_SOURCE_CITATION_RE = re.compile(
    r"\[source:\s*\w+\([^)]*\)\]", re.IGNORECASE
)
_SUSPICIOUS_NUMBER_RE = re.compile(
    r"\b\d+\.\d{3,}\s*(?:days?|hours?|ppm|au|earth\s*radii|r_earth|m_earth|k\b)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# GuardianVerdict
# ---------------------------------------------------------------------------

RiskLabel = Literal[
    "safe",
    "fabricated_number",
    "biosignature_claim",
    "hallucination",
    "off_topic",
]


@dataclass
class GuardianVerdict:
    safe: bool
    risk_label: RiskLabel
    original: str
    screened: str
    model_used: str = "heuristic"
    confidence: float | None = None


# ---------------------------------------------------------------------------
# Rule-based fallback screener
# ---------------------------------------------------------------------------

def _load_non_claims() -> list[str]:
    if _EXPLANATIONS_PATH.exists():
        try:
            with open(_EXPLANATIONS_PATH, encoding="utf-8") as f:
                data = json.load(f)
            return data.get("non_claims", [])
        except Exception:  # noqa: BLE001
            pass
    return [
        "This project is not a biosignature detector.",
        "No exoplanet biosignature has ever been confirmed.",
    ]


def _heuristic_screen(text: str) -> GuardianVerdict:
    """
    Rule-based screening used when the Guardian model is not available.

    Blocks:
    1. Any biosignature claim (unconditional per locked claim).
    2. Floating-point numbers with ≥3 sig-fig decimal places + unit that
       appear in the text WITHOUT an adjacent [source: tool(args)] citation.
    """
    # Check biosignature claims first.
    # The locked non-claim phrase ("not a biosignature detector") is allowlisted —
    # asserting the non-claim is not itself a biosignature claim.
    for pat, negation_ok in _BIOSIGNATURE_PATTERNS:
        if pat.search(text):
            if negation_ok:
                # Check if every match is within an allowlisted context
                all_allowlisted = True
                for m in pat.finditer(text):
                    window_start = max(0, m.start() - 60)
                    window_end = min(len(text), m.end() + 60)
                    window = text[window_start:window_end]
                    if not any(al.search(window) for al in _BIOSIGNATURE_ALLOWLIST):
                        all_allowlisted = False
                        break
                if all_allowlisted:
                    continue  # all matches are within the locked non-claim phrase
            non_claims = _load_non_claims()
            screened = (
                "[Output blocked: biosignature claim detected.]\n\n"
                + "\n".join(non_claims)
            )
            return GuardianVerdict(
                safe=False,
                risk_label="biosignature_claim",
                original=text,
                screened=screened,
            )

    # Check for suspicious unsourced numbers
    citations = set(_SOURCE_CITATION_RE.findall(text))
    suspicious_matches = _SUSPICIOUS_NUMBER_RE.finditer(text)
    for m in suspicious_matches:
        # Check if there is a source citation within 120 chars of this number
        start = max(0, m.start() - 120)
        end = min(len(text), m.end() + 120)
        window = text[start:end]
        if not _SOURCE_CITATION_RE.search(window):
            screened = (
                "[Output blocked: numeric claim without source citation.  "
                "All numbers must originate from a pipeline tool call "
                "with a [source: tool(args)] citation.]\n\n"
                "Please call the appropriate tool (e.g. get_planet_params, "
                "get_vetting_results) to retrieve this value from the pipeline."
            )
            return GuardianVerdict(
                safe=False,
                risk_label="fabricated_number",
                original=text,
                screened=screened,
            )

    return GuardianVerdict(
        safe=True,
        risk_label="safe",
        original=text,
        screened=text,
    )


# ---------------------------------------------------------------------------
# Granite Guardian model screener (lazy-loaded)
# ---------------------------------------------------------------------------

_guardian_pipeline = None
_guardian_load_attempted = False


def _try_load_guardian():
    """
    Attempt to load ibm-granite/granite-guardian-3.1-2b from the local
    HuggingFace cache.  Sets _guardian_pipeline on success.

    Silently falls back to heuristic mode if:
    - transformers is not installed
    - the model is not in the local cache (no network call is made)
    - CUDA / MPS is not available
    """
    global _guardian_pipeline, _guardian_load_attempted
    if _guardian_load_attempted:
        return
    _guardian_load_attempted = True
    try:
        from transformers import pipeline as hf_pipeline  # type: ignore[import]
        _guardian_pipeline = hf_pipeline(
            "text-classification",
            model="ibm-granite/granite-guardian-3.1-2b",
            local_files_only=True,   # never make a network call
            device_map="auto",
        )
    except Exception:  # noqa: BLE001  (ImportError, OSError, etc.)
        _guardian_pipeline = None


def _granite_screen(text: str) -> GuardianVerdict:
    """
    Screen text using the local Granite Guardian model.

    Returns a GuardianVerdict.  Falls back to heuristic if the model
    is not available or the inference fails.
    """
    _try_load_guardian()
    if _guardian_pipeline is None:
        return _heuristic_screen(text)

    try:
        result = _guardian_pipeline(text, truncation=True, max_length=512)
        # Granite Guardian returns {"label": "SAFE"/"UNSAFE", "score": float}
        label = result[0]["label"].upper()
        score = float(result[0]["score"])
        if label == "UNSAFE":
            screened = (
                "[Output blocked by Granite Guardian safety screening.]\n\n"
                + "\n".join(_load_non_claims())
            )
            return GuardianVerdict(
                safe=False,
                risk_label="hallucination",
                original=text,
                screened=screened,
                model_used="ibm-granite/granite-guardian-3.1-2b",
                confidence=score,
            )
        return GuardianVerdict(
            safe=True,
            risk_label="safe",
            original=text,
            screened=text,
            model_used="ibm-granite/granite-guardian-3.1-2b",
            confidence=score,
        )
    except Exception:  # noqa: BLE001
        # Inference error — fall back to heuristic
        return _heuristic_screen(text)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def screen(text: str, use_model: bool = True) -> GuardianVerdict:
    """
    Screen an LLM output before it reaches the client.

    Parameters
    ----------
    text : str
        The raw LLM output to screen.
    use_model : bool
        If True (default), try to use the Granite Guardian model; fall back
        to heuristic if unavailable.  Set to False to force heuristic mode
        (useful in tests).

    Returns
    -------
    GuardianVerdict
        .safe       — True if the text is safe to show.
        .risk_label — category of the risk, or "safe".
        .screened   — text to show the user (redacted if safe=False).
        .original   — original LLM output (never shown if safe=False).
    """
    if use_model:
        return _granite_screen(text)
    return _heuristic_screen(text)
