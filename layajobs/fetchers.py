"""Fetching: source registry, polite HTTP, e-paper PDF discovery + caching.

v1 philosophy: never fake data. A source that cannot be probed is recorded
`unverified` with the error; `run` only processes PDFs that actually exist on
disk (either downloaded here or dropped manually into data/raw/<slug>/).
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests
import tomllib

USER_AGENT = ("laya-jobs/0.1 (local research pipeline; contact: local user)")
DEFAULT_TIMEOUT = 25.0
POLITE_DELAY = 2.0          # seconds between requests to the same host
MAX_PDF_LINKS_PER_SOURCE = 8

_STATUS_FILENAME = "source_status.json"


@dataclass
class Source:
    slug: str
    name: str
    language: str
    kind: str
    base_url: str
    name_ar: Optional[str] = None
    epaper_url: Optional[str] = None
    status: str = "unverified"
    insecure_tls: bool = False

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Source":
        return cls(
            slug=d["slug"], name=d["name"], language=d["language"],
            kind=d["kind"], base_url=d["base_url"],
            name_ar=d.get("name_ar"), epaper_url=d.get("epaper_url"),
            status=d.get("status", "unverified"),
            insecure_tls=bool(d.get("insecure_tls", False)),
        )


def load_sources(config_path: str | Path) -> List[Source]:
    with open(config_path, "rb") as f:
        data = tomllib.load(f)
    return [Source.from_dict(s) for s in data.get("sources", [])]


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

_last_hit: Dict[str, float] = {}


def _polite_wait(url: str) -> None:
    host = urlparse(url).netloc
    last = _last_hit.get(host)
    if last is not None:
        wait = POLITE_DELAY - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
    _last_hit[host] = time.monotonic()


def fetch_url(url: str, *, timeout: float = DEFAULT_TIMEOUT,
              insecure_tls: bool = False) -> requests.Response:
    """GET with a polite per-host delay and a honest User-Agent."""
    _polite_wait(url)
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT},
                        allow_redirects=True, verify=not insecure_tls)
    resp.raise_for_status()
    return resp


# ---------------------------------------------------------------------------
# PDF discovery
# ---------------------------------------------------------------------------

_A_HREF_RE = re.compile(r"<a\b[^>]*?href\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)
_PDFISH_RE = re.compile(r"\.pdf(\?|#|$)|/pdf|kiosk|epaper|e-paper|journal.{0,12}pdf",
                        re.IGNORECASE)


_QUOTED_PDF_RE = re.compile(
    r"[\"']((?:https?:)?/?/?[\w./%~\-]+\.pdf(?:\?[^\"']*)?)[\"']", re.IGNORECASE)


def find_pdf_links(html: str, base_url: str) -> List[tuple[str, str]]:
    """Return (absolute_url, anchor_text) candidates that look like e-paper PDFs.

    Catches both <a href> links and PDF URLs embedded in quoted JS strings
    (kiosk readers often build the download link client-side).
    """
    out: List[tuple[str, str]] = []
    seen: set[str] = set()
    raw = html or ""
    for m in _QUOTED_PDF_RE.finditer(raw):
        candidate = urljoin(base_url, m.group(1))
        if candidate in seen or not candidate.lower().startswith(("http://", "https://")):
            continue
        seen.add(candidate)
        out.append((candidate, "embedded-pdf"))
    for m in _A_HREF_RE.finditer(raw):
        href = m.group(1).strip()
        tail = html[m.end(): m.end() + 200]
        text_m = re.match(r"\s*>([^<]{0,80})", tail)
        text = (text_m.group(1).strip() if text_m else "")
        candidate = urljoin(base_url, href)
        if not candidate.lower().startswith(("http://", "https://")):
            continue
        if candidate in seen:
            continue
        if not _PDFISH_RE.search(candidate) and not _PDFISH_RE.search(text):
            continue
        seen.add(candidate)
        out.append((candidate, text))
    return out[:MAX_PDF_LINKS_PER_SOURCE]


def discover_epaper_pdfs(source: Source) -> List[tuple[str, str]]:
    """Probe a source's e-paper page and return candidate PDF links.

    Raises on network failure — the caller records the error per source.
    """
    target = source.epaper_url or source.base_url
    resp = fetch_url(target, insecure_tls=source.insecure_tls)
    resp.encoding = resp.encoding or "utf-8"
    try:
        html = resp.text
    except Exception:
        html = resp.content.decode("utf-8", errors="replace")
    return find_pdf_links(html, str(resp.url))


# ---------------------------------------------------------------------------
# Download + cache
# ---------------------------------------------------------------------------

def _safe_filename(url: str) -> str:
    tail = [p for p in urlparse(url).path.split("/") if p]
    name = tail[-1] if tail else "edition.pdf"
    name = re.sub(r"[^A-Za-z0-9._\-]", "_", name)
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name


def download_pdf(url: str, dest_dir: str | Path, *,
                 slug: str, issue_date: Optional[_dt.date] = None,
                 timeout: float = 120.0,
                 insecure_tls: bool = False) -> Optional[Path]:
    """Download a PDF into data/raw/<slug>/ (cached by filename). Returns path or None."""
    dest_dir = Path(dest_dir) / slug
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = _safe_filename(url)
    if issue_date:
        name = f"{issue_date.isoformat()}-{name}"
    dest = dest_dir / name
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    try:
        _polite_wait(url)
        with requests.get(url, timeout=timeout, stream=True,
                          headers={"User-Agent": USER_AGENT},
                          verify=not insecure_tls) as r:
            r.raise_for_status()
            ctype = r.headers.get("content-type", "")
            if ctype and "pdf" not in ctype.lower() and not url.lower().endswith(".pdf"):
                return None
            tmp = dest.with_suffix(".part")
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    f.write(chunk)
            tmp.replace(dest)
        return dest
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Verification (CLI `verify` command)
# ---------------------------------------------------------------------------

def load_status(data_dir: str | Path) -> Dict[str, Any]:
    p = Path(data_dir) / _STATUS_FILENAME
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def save_status(data_dir: str | Path, status: Dict[str, Any]) -> Path:
    p = Path(data_dir) / _STATUS_FILENAME
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def verify_source(source: Source) -> Dict[str, Any]:
    """Probe base_url and epaper_url; return a status record (never raises)."""
    rec: Dict[str, Any] = {"slug": source.slug, "name": source.name,
                           "kind": source.kind, "checked_at": _dt.date.today().isoformat()}
    ok_base = ok_epaper = False
    n_pdfs = 0
    try:
        fetch_url(source.base_url, insecure_tls=source.insecure_tls)
        ok_base = True
    except Exception as exc:
        rec["base_error"] = str(exc)[:200]
    if source.epaper_url:
        try:
            links = discover_epaper_pdfs(source)
            n_pdfs = len(links)
            ok_epaper = True
            rec["epaper_pdf_candidates"] = [u for u, _ in links]
        except Exception as exc:
            rec["epaper_error"] = str(exc)[:200]
    if ok_epaper and n_pdfs > 0:
        rec["status"] = "verified"
    elif ok_base:
        rec["status"] = "reachable"
    else:
        rec["status"] = "unverified"
    return rec
