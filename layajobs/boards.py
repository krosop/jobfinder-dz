"""Adapters for online job boards (HTML/JSON sources, not print PDFs).

v1 ships a full Emploitic adapter: the Next.js pages embed a Schema.org
JobPosting (`structuredJobData`) inside `__NEXT_DATA__`, so offers are
recovered as structured JSON without a headless browser. Other boards
(emploipartner, triemploi, ...) are listed in sources.toml with their
measured status and can be added here following the same pattern.

Board offers reuse the same Offer shape and the same SQLite store; the
offer URL is kept in `source_file` for provenance.
"""
from __future__ import annotations

import html as _html
import json
import re
from typing import Any, Dict, Iterator, List, Optional
from urllib.parse import urljoin

import requests

from . import normalize
from .fetchers import DEFAULT_TIMEOUT, USER_AGENT, _polite_wait

_EMPLOITIC_BASE = "https://emploitic.com/"
_LISTING_PATH = "offres-d-emploi"

_OFFER_HREF_RE = re.compile(
    r"href\s*=\s*[\"'](/entreprises/[^\"']+/offres-d-emploi/[^\"']+)[\"']", re.IGNORECASE)
_NEXT_DATA_RE = re.compile(
    r"<script id=\"__NEXT_DATA__\" type=\"application/json\">(.*?)</script>", re.S)

# Schema.org employmentType -> Algerian contract vocabulary
_CONTRACT_MAP = {
    "FULL_TIME": "CDI",
    "PART_TIME": "Non spécifié",
    "TEMPORARY": "CDD",
    "CONTRACTOR": "CDD",
    "FIXED_TERM": "CDD",
    "INTERN": "Stage",
    "VOLUNTEER": "Non spécifié",
    "PERMANENT": "CDI",
}


def _get(url: str, *, insecure_tls: bool = True) -> requests.Response:
    _polite_wait(url)
    resp = requests.get(url, timeout=DEFAULT_TIMEOUT,
                        headers={"User-Agent": USER_AGENT},
                        verify=not insecure_tls, allow_redirects=True)
    resp.raise_for_status()
    return resp


def _strip_html(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", _html.unescape(raw or ""))
    return re.sub(r"\s+", " ", text).strip()


def emploitic_listing_urls(max_pages: int = 3) -> Iterator[List[str]]:
    """Yield batches of offer-path URLs from the Emploitic listing pages."""
    for page in range(1, max_pages + 1):
        url = f"{_EMPLOITIC_BASE}{_LISTING_PATH}?page={page}"
        try:
            resp = _get(url)
        except Exception:
            return
        paths = list(dict.fromkeys(
            m.group(1) for m in _OFFER_HREF_RE.finditer(resp.text)))
        if not paths:
            return
        yield [urljoin(_EMPLOITIC_BASE, p) for p in paths]


def _next_data(resp: requests.Response) -> Optional[Dict[str, Any]]:
    m = _NEXT_DATA_RE.search(resp.text)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def emploitic_offer(url: str) -> Optional[Dict[str, Any]]:
    """Fetch one Emploitic offer page and return its structured job data."""
    try:
        resp = _get(url)
        data = _next_data(resp)
    except Exception:
        return None
    if not data:
        return None
    pp = (data.get("props") or {}).get("pageProps") or {}
    sjd = pp.get("structuredJobData")
    if isinstance(sjd, str):
        try:
            sjd = json.loads(sjd)
        except json.JSONDecodeError:
            sjd = None
    if not isinstance(sjd, dict) or not sjd.get("title"):
        return None
    sjd["_url"] = str(resp.url)
    sjd["_is_expired"] = bool(pp.get("isExpired"))
    return sjd


def emploitic_to_offer(sjd: Dict[str, Any]) -> Dict[str, Any]:
    """Map Emploitic structured job data to the pipeline offer shape."""
    org = sjd.get("hiringOrganization") or {}
    locations = sjd.get("jobLocation") or []
    if isinstance(locations, dict):
        locations = [locations]
    place = locations[0] if locations else {}
    address = place.get("address") or {}
    locality = address.get("addressLocality") or address.get("addressRegion") or ""

    desc = _strip_html(str(sjd.get("description") or ""))
    quals: List[str] = []
    for key in ("educationRequirements", "experienceRequirements"):
        v = sjd.get(key)
        if isinstance(v, str) and v.strip():
            quals.append(_strip_html(v)[:200])
        elif isinstance(v, list):
            quals.extend(_strip_html(str(x))[:200] for x in v if x)

    deadline = None
    valid_through = str(sjd.get("validThrough") or "")
    if len(valid_through) >= 10:
        deadline = valid_through[:10]

    contract = _CONTRACT_MAP.get(
        str(sjd.get("employmentType") or "").upper(), "Non spécifié")

    return {
        "source_newspaper": "Emploitic (web)",
        "source_slug": "emploitic",
        "source_file": sjd.get("_url"),
        "page": None,
        "job_title": _strip_html(str(sjd.get("title") or "")) or None,
        "organization_or_company": _strip_html(str(org.get("name") or "")) or None,
        # Deterministic: Emploitic hosts private employers (public concours
        # never use CV-board flows), so sector is Private by construction.
        # Laya's independent guess is kept as advisory confidence metadata.
        "sector": "Private",
        "contract_type": contract,
        "wilaya_location": normalize.match_wilaya(locality),
        "positions_count": None,
        "required_qualifications": quals[:8],
        "application_deadline": deadline,
        "application_deadline_raw": valid_through or None,
        "deadline_kind": "absolute" if deadline else None,
        "contact_info": {"email": None, "phone": None,
                         "address_or_portal": sjd.get("_url")},
        "language": "fr",
        "snippet": desc[:280] or None,
        # full description, used for Laya classification, not stored
        "full_text": desc,
        "laya_confidence": {},
        "gate": "board_json",
    }


def fetch_emploitic(max_offers: int = 12, max_pages: int = 3) -> List[Dict[str, Any]]:
    """Collect up to `max_offers` structured offers from Emploitic."""
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for batch in emploitic_listing_urls(max_pages=max_pages):
        for url in batch:
            if url in seen:
                continue
            seen.add(url)
            sjd = emploitic_offer(url)
            if sjd and not sjd.get("_is_expired"):
                out.append(emploitic_to_offer(sjd))
            if len(out) >= max_offers:
                return out
    return out


# ---------------------------------------------------------------------------
# Mass harvester: 20 structured offers per listing request, straight from
# __NEXT_DATA__.searchResult.data (title, description, company sector,
# locations, contract, education, experience, profession, published date).
# ---------------------------------------------------------------------------

def _labels(node: Any) -> List[str]:
    if isinstance(node, dict):
        node = [node]
    out = []
    for item in node or []:
        label = (item or {}).get("label")
        if label:
            out.append(str(label).strip())
    return out


def _listing_to_offer(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    title = _strip_html(str(item.get("title") or ""))
    if not title:
        return None
    alias = str(item.get("alias") or "")
    company = item.get("company") or {}
    org = _strip_html(str(company.get("name") or ""))
    if item.get("isAnonymous"):
        org = org or None          # company hidden by the advertiser
    company_sector = _labels(company.get("sector"))
    locations = _labels(item.get("location"))
    contracts = _labels(item.get("contractType"))
    education = _labels(item.get("educationLevel"))
    experience = _labels(item.get("experienceYears"))
    profession = _labels(item.get("profession"))
    published = str(item.get("publishedAt") or "")[:10] or None
    offer_url = (urljoin(_EMPLOITIC_BASE, f"/offres-d-emploi/{alias}")
                 if alias else None)
    wilaya = None
    for loc in locations:
        # labels look like "Alger, Algérie" or "Oran, Algérie"
        first = loc.split(",")[0].strip()
        wilaya = normalize.match_wilaya(first)
        if wilaya:
            break
    desc = _strip_html(str(item.get("description") or ""))
    quals = education + experience
    return {
        "source_newspaper": "Emploitic (web)",
        "source_slug": "emploitic",
        "source_file": offer_url,
        "page": None,
        "job_title": title,
        "organization_or_company": org,
        "sector": "Private",          # board offers are private employers
        "contract_type": contracts[0] if contracts else "Non spécifié",
        "wilaya_location": wilaya,
        "positions_count": None,
        "required_qualifications": quals[:8],
        "application_deadline": None,  # deadline only exists on detail pages
        "application_deadline_raw": None,
        "deadline_kind": None,
        "contact_info": {"email": None, "phone": None,
                         "address_or_portal": offer_url},
        "language": "fr",
        "snippet": desc[:280] or None,
        "full_text": desc,
        # free-form metadata slot (profession, company sector, publish date)
        "laya_confidence": {
            **({"profession": profession[:2]} if profession else {}),
            **({"company_sector": company_sector[0]} if company_sector else {}),
            **({"published_at": published} if published else {}),
        },
        "gate": "board_json",
    }


def harvest_emploitic(max_pages: int = 20, *, verbose: bool = False) -> List[Dict[str, Any]]:
    """Harvest structured offers straight from Emploitic listing pages.

    One request per 20 offers (vs one per offer for the detail-page mode).
    Stops early when a page yields no offers.
    """
    out: List[Dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        url = f"{_EMPLOITIC_BASE}{_LISTING_PATH}?page={page}"
        try:
            resp = _get(url)
        except Exception as exc:
            if verbose:
                print(f"  page {page}: fetch failed ({exc})")
            break
        data = _next_data(resp)
        items = (((data or {}).get("props") or {}).get("pageProps")
                 or {}).get("searchResult", {}).get("data") or []
        if not items:
            break
        added = 0
        for item in items:
            offer = _listing_to_offer(item)
            if offer:
                out.append(offer)
                added += 1
        if verbose:
            print(f"  page {page}: {added} offers")
    return out
