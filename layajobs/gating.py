"""Gating: cheap keyword pre-filter, then the Laya job-notice decision.

Two stages keep Laya calls rare and the pipeline fast on CPU:

1. `prefilter` — compiled bilingual regex over recruitment vocabulary. Text
   with zero hits never reaches Laya (most of a newspaper will not).
2. `gate_chunk` — the Laya gate decision (`is_job_notice`,
   `contains_classifieds`) with per-field confidence. Keyword-only fallback
   applies when the Laya checkpoint cannot load.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from . import laya_engine

# Recruitment vocabulary seen in Algerian print classifieds (FR + AR).
KEYWORDS = [
    # French
    r"avis\s+de\s+recrutement",
    r"offre(?:s)?\s+d'emploi",
    r"offre(?:s)?\s+d’emploi",
    r"recrutement",
    r"recrute",
    r"concours",              # concours de recrutement / sur épreuves / sur fichiers
    r"postes?\s+(?:à\s+)?pourvoir",
    r"postes?\s+vacants",
    r"candidatures?",
    r"dossier\s+de\s+candidature",
    r"fonction\s+publique",
    r"contrat\s+(?:de\s+travail|à\s+durée|prestation)",
    r"cherche\s+(?:un|une|des)\s+(?:développeur|comptable|secrétaire|ingénieur|technicien|commercial|ouvrier|livreur|chauffeur)",
    # Arabic
    r"إعلان\s+توظيف",
    r"إعلان\s+توظيف",
    r"مسابقة\s+توظيف",
    r"توظيف\s+على\s+أساس\s+الشهادة",
    r"مسابقة\s+على\s+أساس\s+الشهادة",
    r"عروض\s+عمل",
    r"مناصب\s+مالية",
    r"يعلن\s+عن\s+توظيف",
    r"تعلن\s+.*\s+توظيف",
    r"ملف\s+الترشيح",
    r"الترقي\s+في\s+الرتبة",
]

_KEYWORD_RE = re.compile("|".join(KEYWORDS), re.IGNORECASE)

# Confidence at or above this counts as a positive Laya gate decision.
MIN_CONFIDENCE = 0.5


@dataclass
class GateResult:
    """Outcome of gating one chunk."""

    passed: bool
    is_job_notice: Optional[bool] = None
    contains_classifieds: Optional[bool] = None
    confidence: Dict[str, float] = field(default_factory=dict)
    gated_by: str = "keyword_rejected"   # keyword_rejected | laya | keyword_fallback
    keyword_hits: int = 0
    laya_error: Optional[str] = None


def prefilter(text: str) -> int:
    """Count keyword hits (0 => skip everything downstream)."""
    return len(_KEYWORD_RE.findall(text or ""))


def gate_chunk(text: str, *, lang_hint: Optional[str] = None,
               min_confidence: float = MIN_CONFIDENCE) -> GateResult:
    """Gate one chunk through prefilter + Laya.

    - No keyword hits -> rejected without touching Laya.
    - Keyword hit -> Laya decides; a low-confidence negative still rejects
      (conservative: prefer recall at the keyword stage, precision at Laya).
    - Laya unavailable -> keyword hit alone passes, flagged `keyword_fallback`.
    """
    hits = prefilter(text)
    if hits == 0:
        return GateResult(passed=False, keyword_hits=0)

    try:
        res = laya_engine.gate(text, lang=lang_hint)
    except Exception as exc:  # checkpoint missing, torch failure, ...
        return GateResult(passed=True, keyword_hits=hits,
                          gated_by="keyword_fallback", laya_error=str(exc))

    values: Dict[str, Any] = res["values"]
    conf: Dict[str, float] = res["confidence"]
    is_job = bool(values.get("is_job_notice"))
    conf_job = float(conf.get("is_job_notice", 0.0))
    passed = is_job and conf_job >= min_confidence
    return GateResult(
        passed=passed,
        is_job_notice=is_job,
        contains_classifieds=bool(values.get("contains_classifieds")),
        confidence={"is_job_notice": conf_job,
                    "contains_classifieds": float(conf.get("contains_classifieds", 0.0))},
        gated_by="laya",
        keyword_hits=hits,
    )
