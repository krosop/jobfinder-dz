"""Daily digest: classify stored offers as NEW / REMAINING / EXPIRED and
format personalized Telegram messages.

Classification (from the store's own bookkeeping):
  NEW       - first_seen is today
  REMAINING - seen before, still open (no deadline, or deadline >= today)
  EXPIRED   - application_deadline < today  (excluded by default)

Per-chat preferences (city / sector / contract / keywords) filter the offers.
"""
from __future__ import annotations

import datetime as _dt
import json
from typing import Any, Dict, List, Optional

MAX_OFFERS_PER_MESSAGE = 25


# ---------------------------------------------------------------------------
# Preference handling
# ---------------------------------------------------------------------------

def default_prefs() -> Dict[str, Any]:
    return {"cities": [], "sectors": [], "contracts": [], "keywords": []}


def normalize_prefs(raw: Optional[Dict[str, Any]]) -> Dict[str, List[str]]:
    """Coerce stored prefs to a clean {cities, sectors, contracts, keywords} dict."""
    prefs = default_prefs()
    for key in prefs:
        value = (raw or {}).get(key) or []
        if isinstance(value, str):
            value = [value]
        prefs[key] = [str(v).strip().casefold() for v in value if str(v).strip()]
    return prefs


def parse_pref_command(key: str, args: str) -> Dict[str, List[str]]:
    """Parse '/city Alger Oran' -> {'cities': ['alger','oran']}. '/city' clears."""
    words = [w for w in (args or "").split() if w.strip()]
    return {key: [w.casefold() for w in words]}


def _match_any(field: Optional[str], wanted: List[str]) -> bool:
    """True if the (casefolded) field contains any wanted token, or no tokens set."""
    if not wanted:
        return True
    if not field:
        return False
    f = str(field).casefold()
    return any(w in f for w in wanted)


def offer_matches(offer: Dict[str, Any], prefs: Dict[str, List[str]]) -> bool:
    """Apply city / sector / contract / keyword filters to one offer row."""
    if not _match_any(offer.get("wilaya_location"), prefs["cities"]):
        return False
    if prefs["sectors"] and str(offer.get("sector") or "").casefold() not in prefs["sectors"]:
        return False
    if not _match_any(offer.get("contract_type"), prefs["contracts"]):
        return False
    if prefs["keywords"]:
        hay = " ".join([
            str(offer.get("job_title") or ""),
            str(offer.get("snippet") or ""),
            str(offer.get("organization_or_company") or ""),
        ]).casefold()
        if not any(k in hay for k in prefs["keywords"]):
            return False
    return True


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_offers(rows: List[Dict[str, Any]], *,
                    today: Optional[_dt.date] = None) -> Dict[str, List[Dict[str, Any]]]:
    """Split offer rows into {'new', 'remaining', 'expired'}."""
    today = today or _dt.date.today()
    today_iso = today.isoformat()
    out: Dict[str, List[Dict[str, Any]]] = {"new": [], "remaining": [], "expired": []}
    for r in rows:
        first_seen = str(r.get("first_seen") or "")[:10]
        deadline = str(r.get("application_deadline") or "")[:10]
        if deadline and deadline < today_iso:
            out["expired"].append(r)
        elif first_seen == today_iso:
            out["new"].append(r)
        else:
            out["remaining"].append(r)
    return out


# ---------------------------------------------------------------------------
# Formatting (Telegram HTML)
# ---------------------------------------------------------------------------

def _esc(s: Any) -> str:
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _offer_line(r: Dict[str, Any]) -> str:
    title = _esc(r.get("job_title") or "Offre")
    org = _esc(r.get("organization_or_company") or "Employeur non précisé")
    bits = [f"🏢 {org}"]
    if r.get("contract_type"):
        bits.append(f"📄 {_esc(r['contract_type'])}")
    if r.get("wilaya_location"):
        bits.append(f"📍 {_esc(r['wilaya_location'])}")
    if r.get("application_deadline"):
        bits.append(f"⏳ avant {_esc(r['application_deadline'])}")
    link = r.get("contact_address_or_portal") or ""
    line = f"<b>{title}</b>\n" + " · ".join(bits)
    if str(link).startswith("http"):
        line += f'\n🔗 <a href="{_esc(link)}">voir l\'offre</a>'
    return line


def format_digest(classes: Dict[str, List[Dict[str, Any]]], *,
                  prefs: Dict[str, List[str]],
                  max_new: int = MAX_OFFERS_PER_MESSAGE,
                  max_remaining: int = 8) -> List[str]:
    """Build one or more Telegram HTML messages for the classified offers."""
    parts: List[str] = []
    today = _dt.date.today().strftime("%d/%m/%Y")

    def _pref_note() -> str:
        chips = []
        if prefs["cities"]:
            chips.append("villes: " + ", ".join(prefs["cities"]))
        if prefs["sectors"]:
            chips.append("secteurs: " + ", ".join(prefs["sectors"]))
        if prefs["contracts"]:
            chips.append("contrats: " + ", ".join(prefs["contracts"]))
        if prefs["keywords"]:
            chips.append("mots-clés: " + ", ".join(prefs["keywords"]))
        return f"\n🔎 Filtres — {' · '.join(chips)}" if chips else ""

    if not (classes["new"] or classes["remaining"]):
        note = (f"\n\n⛔ {len(classes['expired'])} offre(s) expirée(s) ce jour."
                if classes["expired"] else "")
        return [("📭 Aucune offre correspondant à vos filtres aujourd'hui"
                 f" ({today}).{note}{_pref_note()}")]

    head = f"📑 <b>Offres d'emploi — {today}</b>{_pref_note()}"
    if classes["new"]:
        shown = classes["new"][:max_new]
        block = head + f"\n\n🆕 <b>NOUVEAUTÉS ({len(classes['new'])})</b>\n\n" + \
            "\n\n".join(_offer_line(r) for r in shown)
        if len(classes["new"]) > max_new:
            block += f"\n\n… et {len(classes['new']) - max_new} autre(s) nouvelle(s)"
        parts.append(block)
    if classes["remaining"]:
        shown = classes["remaining"][:max_remaining]
        block = (f"\n🔄 <b>TOUJOURS OUVERTES ({len(classes['remaining'])})</b> — "
                 "aperçu des plus récentes :\n\n" +
                 "\n\n".join(_offer_line(r) for r in shown))
        parts.append(block)
    if classes["expired"]:
        parts.append(f"⛔ {len(classes['expired'])} offre(s) expirée(s) ce jour — "
                     "exclue(s) du récapitulatif.")
    return parts


def build_digest(rows: List[Dict[str, Any]], prefs_raw: Optional[Dict[str, Any]], *,
                 today: Optional[_dt.date] = None) -> List[str]:
    """Full pipeline: prefs -> filter -> classify -> formatted messages."""
    prefs = normalize_prefs(prefs_raw)
    matching = [r for r in rows if offer_matches(r, prefs)]
    classes = classify_offers(matching, today=today)
    return format_digest(classes, prefs=prefs)
