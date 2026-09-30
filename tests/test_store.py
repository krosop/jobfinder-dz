"""Tests for layajobs.store — upsert dedup, queries, stats."""
from __future__ import annotations

from pathlib import Path

import pytest

from layajobs.extractor import extract_offers
from layajobs.store import Store

FIXTURES = Path(__file__).parent / "fixtures"
FR = (FIXTURES / "fr_notice.txt").read_text(encoding="utf-8")


def _stub_classify(values):
    def _c(text, *, lang="fr"):
        return {"values": dict(values), "confidence": {"sector": 0.9}}
    return _c


@pytest.fixture()
def tmp_store(tmp_path):
    return Store(tmp_path / "test.db")


def _offers():
    return extract_offers(FR, source_name="Test FR", source_slug="test-fr",
                          classify=_stub_classify({"sector": "Private",
                                                   "contract_type": "CDI"}))


def test_upsert_insert_then_dedup(tmp_store):
    offers = _offers()
    ids = []
    for o in offers:
        rid, inserted = tmp_store.upsert_offer(o.to_json())
        ids.append(rid)
    # same offers again -> no new rows, times_seen bumps
    for o in offers:
        rid, inserted = tmp_store.upsert_offer(o.to_json())
        assert not inserted
    assert len(ids) == len(offers)
    rows = tmp_store.query()
    assert len(rows) == len(offers)
    assert all(r["times_seen"] == 2 for r in rows)


def test_query_filters(tmp_store):
    for o in _offers():
        tmp_store.upsert_offer(o.to_json())
    rows = tmp_store.query(source="test-fr")
    assert rows
    assert all(r["source_slug"] == "test-fr" for r in rows)
    assert tmp_store.query(source="nonexistent") == []


def test_stats(tmp_store):
    for o in _offers():
        tmp_store.upsert_offer(o.to_json())
    s = tmp_store.stats()
    assert s["total"] == len(_offers())
    assert s["by_sector"][0]["sector"] == "Private"


def test_run_records(tmp_store):
    rid = tmp_store.start_run("ingest")
    tmp_store.finish_run(rid, chunks_total=10, chunks_gated=2, offers_stored=1)
    row = tmp_store.conn.execute("SELECT * FROM runs WHERE id = ?", (rid,)).fetchone()
    assert row["chunks_total"] == 10
    assert row["offers_stored"] == 1
    assert row["finished_at"] is not None
