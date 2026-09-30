"""Laya decision engine: singleton agent load + typed decision schemas.

Laya (v0.3.x) is a non-autoregressive System 1 decision engine: it answers
fixed-option questions (choice / boolean / score) with calibrated probabilities,
in a single forward pass, on CPU. It cannot generate free text — free-text
fields come from layajobs.extractor instead.

The `multilingual` checkpoint (mmBERT backbone) is used because notices arrive
in French and Arabic.
"""
from __future__ import annotations

import threading
from typing import Any, Dict, Optional

import laya
from pydantic import BaseModel, Field as PydField
from typing import Literal

# ---------------------------------------------------------------------------
# Decision schemas (Laya maps enum -> choice question, bool -> noul question)
# ---------------------------------------------------------------------------

class GateDecision(BaseModel):
    """Chunk-level gate: does this text contain at least one job notice?"""
    is_job_notice: bool = PydField(
        description="Does this text contain a recruitment announcement, "
                    "job offer, or public-service recruitment contest?")
    contains_classifieds: bool = PydField(
        description="Does this text look like a classified-ads page "
                    "(petites annonces / إعلانات مصنفة)?")

class OfferFields(BaseModel):
    """Block-level classification for a chunk that passed the gate."""
    sector: Literal["Public", "Private", "Unknown"] = PydField(
        description="Is the recruiting organization a public administration "
                    "or a private company?")
    contract_type: Literal["CDI", "CDD", "Statutaire", "Non spécifié"] = PydField(
        description="What contract type does the offer mention? "
                    "'Statutaire' covers fonction publique posts.")
    language: Literal["fr", "ar", "mixed"] = PydField(
        description="Primary language of the text.")

SCHEMAS = {"gate": GateDecision, "offer": OfferFields}

# ---------------------------------------------------------------------------
# Agent singleton
# ---------------------------------------------------------------------------

_MODEL_ID = "convaiinnovations/laya"
_SUBFOLDER = "multilingual"

_lock = threading.Lock()
_agent: Optional[Any] = None
_load_error: Optional[Exception] = None


def get_agent():
    """Load the multilingual Laya agent once per process (lazy, thread-safe)."""
    global _agent, _load_error
    if _agent is not None:
        return _agent
    with _lock:
        if _agent is None:
            try:
                _agent = laya.load(_MODEL_ID, subfolder=_SUBFOLDER)
            except Exception as exc:  # keep the error for a clean CLI message
                _load_error = exc
                raise
    return _agent


def available() -> bool:
    """True when the Laya checkpoint can be loaded (cached after first check)."""
    try:
        get_agent()
        return True
    except Exception:
        return False


def load_error() -> Optional[Exception]:
    return _load_error


# ---------------------------------------------------------------------------
# Decision wrappers (thin, so tests can stub them)
# ---------------------------------------------------------------------------

def decide(text: str, schema_name: str, *, lang: Optional[str] = None,
           return_details: bool = False) -> Any:
    """Run one Laya decision. `schema_name` is 'gate' or 'offer'.

    Returns the projected values dict (or DecisionResult with return_details).
    """
    agent = get_agent()
    schema = SCHEMAS[schema_name]
    kwargs: Dict[str, Any] = {}
    if lang and lang != "mixed":
        kwargs["lang"] = lang
    return agent.decide(text, schema=schema, return_details=return_details, **kwargs)


def gate(text: str, *, lang: Optional[str] = None) -> Dict[str, Any]:
    """Gate decision + per-field confidence."""
    res = decide(text, "gate", lang=lang, return_details=True)
    return {
        "values": res.values,
        "confidence": res.confidence,
    }


def classify_offer(text: str, *, lang: Optional[str] = None) -> Dict[str, Any]:
    """Offer-field classification + per-field confidence."""
    res = decide(text, "offer", lang=lang, return_details=True)
    return {
        "values": res.values,
        "confidence": res.confidence,
    }
