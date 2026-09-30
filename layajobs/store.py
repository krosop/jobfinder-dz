"""SQLite persistence for job offers: schema, dedup upsert, queries.

One `jobs.db` next to the code (configurable). Dedup key is the hash of
(organization, title, deadline, source) — republished notices collapse into
one row whose `times_seen` counter and `first_seen`/`last_seen` timestamps
track republications.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS offers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dedup_key TEXT NOT NULL UNIQUE,
    source_newspaper TEXT,
    source_slug TEXT,
    source_file TEXT,
    page INTEGER,
    job_title TEXT,
    organization_or_company TEXT,
    sector TEXT,
    contract_type TEXT,
    wilaya_location TEXT,
    positions_count INTEGER,
    required_qualifications TEXT,      -- JSON array
    application_deadline TEXT,         -- ISO date or NULL
    application_deadline_raw TEXT,
    deadline_kind TEXT,
    contact_email TEXT,
    contact_phone TEXT,
    contact_address_or_portal TEXT,
    language TEXT,
    snippet TEXT,
    laya_confidence TEXT,              -- JSON object
    gate TEXT,
    times_seen INTEGER NOT NULL DEFAULT 1,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_offers_source ON offers(source_slug);
CREATE INDEX IF NOT EXISTS idx_offers_deadline ON offers(application_deadline);
CREATE INDEX IF NOT EXISTS idx_offers_wilaya ON offers(wilaya_location);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    mode TEXT,
    sources_attempted INTEGER DEFAULT 0,
    sources_ok INTEGER DEFAULT 0,
    pdfs_downloaded INTEGER DEFAULT 0,
    pdfs_cached INTEGER DEFAULT 0,
    pdfs_needs_ocr INTEGER DEFAULT 0,
    chunks_total INTEGER DEFAULT 0,
    chunks_gated INTEGER DEFAULT 0,
    offers_extracted INTEGER DEFAULT 0,
    offers_stored INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    detail TEXT                        -- JSON log
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dedup_key(o: Dict[str, Any]) -> str:
    parts = [
        (o.get("organization_or_company") or "").casefold(),
        (o.get("job_title") or "").casefold(),
        o.get("application_deadline") or "",
        o.get("source_slug") or "",
        # Board offers carry a unique URL; keeping it in the key prevents
        # same-title offers from different companies colliding, while
        # re-fetching the same offer still dedups (URL identical).
        o.get("source_file") or "",
    ]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:32]


class Store:
    def __init__(self, db_path: str | Path = "data/jobs.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # -- offers -------------------------------------------------------------

    def upsert_offer(self, offer: Dict[str, Any]) -> tuple[int, bool]:
        """Insert or update one offer. Returns (row_id, inserted_new)."""
        contact = offer.get("contact_info") or {}
        now = _now()
        key = _dedup_key(offer)
        cur = self.conn.execute(
            "SELECT id, times_seen FROM offers WHERE dedup_key = ?", (key,))
        row = cur.fetchone()
        if row:
            self.conn.execute(
                "UPDATE offers SET times_seen = times_seen + 1, last_seen = ? WHERE id = ?",
                (now, row["id"]))
            self.conn.commit()
            return row["id"], False
        cur = self.conn.execute(
            """
            INSERT INTO offers (
                dedup_key, source_newspaper, source_slug, source_file, page,
                job_title, organization_or_company, sector, contract_type,
                wilaya_location, positions_count, required_qualifications,
                application_deadline, application_deadline_raw, deadline_kind,
                contact_email, contact_phone, contact_address_or_portal,
                language, snippet, laya_confidence, gate,
                times_seen, first_seen, last_seen
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                key,
                offer.get("source_newspaper"),
                offer.get("source_slug"),
                offer.get("source_file"),
                offer.get("page"),
                offer.get("job_title"),
                offer.get("organization_or_company"),
                offer.get("sector"),
                offer.get("contract_type"),
                offer.get("wilaya_location"),
                offer.get("positions_count"),
                json.dumps(offer.get("required_qualifications") or [], ensure_ascii=False),
                offer.get("application_deadline"),
                offer.get("application_deadline_raw"),
                offer.get("deadline_kind"),
                contact.get("email"),
                contact.get("phone"),
                contact.get("address_or_portal"),
                offer.get("language"),
                offer.get("snippet"),
                json.dumps(offer.get("laya_confidence") or {}, ensure_ascii=False),
                offer.get("gate"),
                1, now, now,
            ))
        self.conn.commit()
        return cur.lastrowid, True

    def query(self, *, source: Optional[str] = None,
              sector: Optional[str] = None,
              since: Optional[str] = None,
              limit: int = 200) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM offers WHERE 1=1"
        params: List[Any] = []
        if source:
            sql += " AND source_slug = ?"
            params.append(source)
        if sector:
            sql += " AND sector = ?"
            params.append(sector)
        if since:
            sql += " AND first_seen >= ?"
            params.append(since)
        sql += " ORDER BY first_seen DESC, id DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> Dict[str, Any]:
        total = self.conn.execute("SELECT COUNT(*) c FROM offers").fetchone()["c"]
        by_source = self.conn.execute(
            "SELECT COALESCE(source_newspaper, source_slug, '?') src, COUNT(*) c "
            "FROM offers GROUP BY 1 ORDER BY c DESC").fetchall()
        by_sector = self.conn.execute(
            "SELECT sector, COUNT(*) c FROM offers GROUP BY 1 ORDER BY c DESC").fetchall()
        by_lang = self.conn.execute(
            "SELECT language, COUNT(*) c FROM offers GROUP BY 1 ORDER BY c DESC").fetchall()
        return {
            "total": total,
            "by_source": [dict(r) for r in by_source],
            "by_sector": [dict(r) for r in by_sector],
            "by_language": [dict(r) for r in by_lang],
        }

    # -- runs ---------------------------------------------------------------

    def start_run(self, mode: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs (started_at, mode) VALUES (?, ?)", (_now(), mode))
        self.conn.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int, **counters: Any) -> None:
        sets = ", ".join(f"{k} = ?" for k in counters)
        self.conn.execute(
            f"UPDATE runs SET finished_at = ?, {sets} WHERE id = ?",
            (_now(), *counters.values(), run_id))
        self.conn.commit()
