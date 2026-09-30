"""Offline tests for the Telegram digest pipeline (no network, no Laya)."""
from __future__ import annotations

import datetime as dt

from layajobs import digest as dg
from layajobs.telegram import PrefsStore, _chunks
from layajobs.digest import parse_pref_command


def _row(**kw):
    base = {
        "job_title": "Ingénieur Helpdesk Senior",
        "organization_or_company": "Al-Baraka Bank",
        "sector": "Private",
        "contract_type": "CDI",
        "wilaya_location": "Alger",
        "application_deadline": "2026-11-29",
        "first_seen": "2026-09-30T08:00:00",
        "snippet": "maintenance informatique",
        "contact_address_or_portal": "https://emploitic.com/offres/x",
    }
    base.update(kw)
    return base


class TestClassification:
    def test_new_today(self):
        out = dg.classify_offers([_row()], today=dt.date(2026, 9, 30))
        assert [r["job_title"] for r in out["new"]] == ["Ingénieur Helpdesk Senior"]
        assert not out["remaining"] and not out["expired"]

    def test_remaining_seen_before(self):
        out = dg.classify_offers(
            [_row(first_seen="2026-09-20T08:00:00")], today=dt.date(2026, 9, 30))
        assert out["remaining"] and not out["new"] and not out["expired"]

    def test_expired_deadline_passed(self):
        out = dg.classify_offers(
            [_row(application_deadline="2026-09-01")], today=dt.date(2026, 9, 30))
        assert out["expired"] and not out["new"] and not out["remaining"]

    def test_no_deadline_never_expires(self):
        out = dg.classify_offers(
            [_row(application_deadline=None, first_seen="2026-08-01T00:00:00")],
            today=dt.date(2026, 9, 30))
        assert out["remaining"]


class TestPrefs:
    def test_parse_city(self):
        assert parse_pref_command("cities", "Alger Oran") == \
            {"cities": ["alger", "oran"]}

    def test_parse_empty_clears(self):
        assert parse_pref_command("cities", "") == {"cities": []}

    def test_city_filter(self):
        prefs = dg.normalize_prefs({"cities": ["alger"]})
        assert dg.offer_matches(_row(), prefs)
        assert not dg.offer_matches(_row(wilaya_location="Oran"), prefs)

    def test_sector_exact(self):
        prefs = dg.normalize_prefs({"sectors": ["public"]})
        assert not dg.offer_matches(_row(), prefs)
        assert dg.offer_matches(_row(sector="Public"), prefs)

    def test_contract_substring(self):
        prefs = dg.normalize_prefs({"contracts": ["cdd"]})
        assert dg.offer_matches(_row(contract_type="CDD Ou Mission"), prefs)

    def test_keyword_fr_ar(self):
        assert dg.offer_matches(
            _row(), dg.normalize_prefs({"keywords": ["مهندس"]})) is False
        assert dg.offer_matches(
            _row(job_title="مهندس دولة في الإعلام الآلي"),
            dg.normalize_prefs({"keywords": ["مهندس"]}))

    def test_no_prefs_matches_everything(self):
        prefs = dg.normalize_prefs({})
        assert dg.offer_matches(_row(), prefs)


class TestFormatting:
    def test_digest_marks_new_and_remaining(self):
        rows = [_row(), _row(job_title="Comptable", first_seen="2026-09-28T00:00:00")]
        msgs = dg.build_digest(rows, {}, today=dt.date(2026, 9, 30))
        text = "\n".join(msgs)
        assert "NOUVEAUTÉS (1)" in text and "TOUJOURS OUVERTES (1)" in text
        assert "Ingénieur Helpdesk Senior" in text and "Comptable" in text

    def test_digest_empty(self):
        msgs = dg.build_digest([], {"cities": ["oran"]}, today=dt.date(2026, 9, 30))
        assert "Aucune offre" in msgs[0]

    def test_expired_not_shown(self):
        rows = [_row(application_deadline="2026-09-01")]
        msgs = dg.build_digest(rows, {}, today=dt.date(2026, 9, 30))
        assert "expirée" in "\n".join(msgs)

    def test_html_escaped(self):
        msgs = dg.build_digest(
            [_row(job_title="Ingénieur <script>alert(1)</script>")],
            {}, today=dt.date(2026, 9, 30))
        assert "<script>" not in "\n".join(msgs)
        assert "&lt;script&gt;" in "\n".join(msgs)

    def test_chunks_split(self):
        long = "\n\n".join(f"offer {i}" for i in range(500))
        parts = _chunks(long, 500)
        assert len(parts) > 1
        assert all(len(p) <= 500 for p in parts)
        assert "offer 0" in parts[0]


class TestPrefsStore:
    def test_roundtrip(self, tmp_path):
        ps = PrefsStore(tmp_path / "t.db")
        ps.set(123, {"cities": ["alger"], "sectors": [], "contracts": [],
                     "keywords": ["مهندس"]})
        assert ps.get(123)["cities"] == ["alger"]
        assert ps.get(123)["keywords"] == ["مهندس"]
        assert ps.all_chats() == ["123"]

    def test_unknown_chat_defaults(self, tmp_path):
        ps = PrefsStore(tmp_path / "t.db")
        assert ps.get(999) == {"cities": [], "sectors": [], "contracts": [],
                               "keywords": []}
