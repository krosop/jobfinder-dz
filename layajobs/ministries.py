"""Ministry WordPress REST adapters — structured concours announcements.

Several Algerian ministries run WordPress and expose their posts (including
recruitment-contest announcements) via the standard REST API, which works
where their HTML pages 403. Posts are fetched by keyword, HTML-stripped, and
run through the rule extractor with a no-Laya classifier: announcements are
curated text, the sanity filters drop news noise, so no gate is needed.

Measured 2026-09-30:
  education  OK   (large concours volume: ~26k posts announced for the sector)
  sante      OK   (concours national sur titres)
  interieur  OK   (DGSN / wilaya announcements)
  mjustice   OK   (magistrate & staff contests, FR + AR posts)
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Dict, List, Optional

import requests

from .extractor import Offer, dedupe_offers, extract_offers
from .fetchers import DEFAULT_TIMEOUT, USER_AGENT, _polite_wait

# slug -> (display name, WP REST base, language)
MINISTRIES: Dict[str, Dict[str, str]] = {
    "education": {
        "name": "Ministère de l'Éducation Nationale (web)",
        "api": "https://www.education.gov.dz/wp-json/wp/v2/posts",
        "lang": "ar",
    },
    "sante": {
        "name": "Ministère de la Santé (web)",
        "api": "https://www.sante.gov.dz/wp-json/wp/v2/posts",
        "lang": "fr",
    },
    "interieur": {
        "name": "Ministère de l'Intérieur (web)",
        "api": "https://www.interieur.gov.dz/wp-json/wp/v2/posts",
        "lang": "ar",
    },
    "mjustice": {
        "name": "Ministère de la Justice (web)",
        "api": "https://www.mjustice.gov.dz/wp-json/wp/v2/posts",
        "lang": "ar",
    },
}

# Search terms: recruitment-contest vocabulary in FR and AR.
_SEARCH_TERMS = ["مسابقة", "توظيف", "concours", "recrutement"]

_NO_LAYA = {"values": {}, "confidence": {}}


def _strip_html(raw: str) -> str:
    text = re.sub(r"<[^>]+>", "\n", raw or "")
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&laquo;", "«").replace("&raquo;", "»")
                .replace("&#8217;", "'").replace("&#8211;", "–"))
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _fetch_posts(api: str, term: str, per_page: int = 10) -> List[Dict[str, Any]]:
    _polite_wait(api)
    # .gov.dz TLS certs are routinely invalid — same policy as fetchers.
    r = requests.get(api, params={"search": term, "per_page": per_page},
                     timeout=DEFAULT_TIMEOUT, headers={"User-Agent": USER_AGENT},
                     verify=False)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else []


def _post_to_offers(post: Dict[str, Any], slug: str,
                    source_name: str, lang_hint: str) -> List[Offer]:
    """Turn one WP post into rule-extracted offers (0..n, sanity-filtered)."""
    link = str(post.get("link") or "")
    content = _strip_html(post.get("content", {}).get("rendered", ""))
    # Posts below 30 words are notices/results stubs with no offer body.
    if len(content.split()) < 30:
        return []
    try:
        issue = dt.date.fromisoformat(str(post.get("date") or "")[:10])
    except ValueError:
        issue = dt.date.today()
    offers = extract_offers(
        content,
        source_name=source_name,
        source_slug=slug,
        source_file=link,
        issue_date=issue,
        lang_hint=lang_hint,
        gate_by="rules_only",
        strict_rank=True,
        classify=lambda text, lang=None: dict(_NO_LAYA),
    )
    return dedupe_offers(offers)


def harvest_ministry(slug: str, per_page: int = 10,
                     *, verbose: bool = False) -> List[Offer]:
    """Fetch + extract one ministry (all search terms, posts deduped by link)."""
    conf = MINISTRIES.get(slug)
    if not conf:
        raise KeyError(f"unknown ministry slug: {slug}")
    seen_links: set[str] = set()
    out: List[Offer] = []
    for term in _SEARCH_TERMS:
        try:
            posts = _fetch_posts(conf["api"], term, per_page=per_page)
        except Exception as exc:
            if verbose:
                print(f"  [{slug}] search {term!r} failed: {str(exc)[:80]}")
            continue
        for post in posts:
            link = str(post.get("link") or "")
            if not link or link in seen_links:
                continue
            seen_links.add(link)
            out.extend(_post_to_offers(post, slug, conf["name"], conf["lang"]))
    if verbose:
        print(f"  [{slug}] {len(out)} offer(s) from {len(seen_links)} post(s)")
    return out


def harvest_all(slugs: Optional[List[str]] = None, *,
                verbose: bool = False) -> Dict[str, List[Offer]]:
    """Harvest every ministry (or the given subset). Returns slug -> offers."""
    slugs = slugs or list(MINISTRIES)
    result: Dict[str, List[Offer]] = {}
    for slug in slugs:
        try:
            result[slug] = harvest_ministry(slug, verbose=verbose)
        except Exception as exc:
            if verbose:
                print(f"  [{slug}] harvest failed: {str(exc)[:100]}")
            result[slug] = []
    return result
