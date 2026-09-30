"""Self-scraping demo: ministry concours via the WP REST API — no Laya.

Proof that the rule extractor alone (classify stubbed to empty) can pull
structured offers from real published announcements. Laya stays optional:
`gate`/`sector` come from deterministic rules here.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Dict, List

import requests

from layajobs.extractor import dedupe_offers, extract_offers
from layajobs.fetchers import DEFAULT_TIMEOUT, USER_AGENT, _polite_wait
from layajobs.store import Store

API = "https://www.mjustice.gov.dz/wp-json/wp/v2/posts"

_NO_LAYA = {"values": {}, "confidence": {}}   # classifier stub: rules only


def _strip_html(raw: str) -> str:
    text = re.sub(r"<[^>]+>", "\n", raw or "")
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&laquo;", "«").replace("&raquo;", "»")
                .replace("&#8217;", "'").replace("&#8211;", "–"))
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def fetch_posts(search: str, per_page: int = 8) -> List[Dict[str, Any]]:
    _polite_wait(API)
    # .gov.dz TLS certs are routinely invalid; verify=False like the fetchers.
    r = requests.get(API, params={"search": search, "per_page": per_page},
                     timeout=DEFAULT_TIMEOUT, headers={"User-Agent": USER_AGENT},
                     verify=False)
    r.raise_for_status()
    return r.json()


def main() -> int:
    store = Store("data/jobs.db")
    offers_all: List[Dict[str, Any]] = []
    posts = fetch_posts("توظيف") + fetch_posts("مسابقة")
    seen = set()
    for post in posts:
        link = post.get("link", "")
        if link in seen:
            continue
        seen.add(link)
        content = _strip_html(post.get("content", {}).get("rendered", ""))
        if len(content.split()) < 30:
            continue
        issue = dt.date.fromisoformat(post.get("date", "")[:10] or dt.date.today().isoformat())
        offers = extract_offers(
            content,
            source_name="Ministère de la Justice (web)",
            source_slug="mjustice-concours",
            source_file=link,
            issue_date=issue,
            classify=lambda text, lang="ar": dict(_NO_LAYA),   # rules only
        )
        offers = dedupe_offers(offers)
        print(f"[post] {post.get('date', '')[:10]} {link[:80]}")
        for o in offers:
            _, inserted = store.upsert_offer(o.to_json())
            offers_all.append(o)
            print(f"   [{'new' if inserted else 'dup'}] {o.job_title!r} @ "
                  f"{o.organization_or_company!r} | {o.contract_type} | "
                  f"deadline={o.application_deadline or o.application_deadline_raw}")
    print(f"\n{len(offers_all)} offers scraped with rules only (Laya not used)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
