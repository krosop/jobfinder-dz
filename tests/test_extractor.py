"""Tests for layajobs.extractor on bilingual fixtures (no Laya required)."""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Dict

import pytest

from layajobs.extractor import dedupe_offers, extract_offers, split_notices

FIXTURES = Path(__file__).parent / "fixtures"

FR = (FIXTURES / "fr_notice.txt").read_text(encoding="utf-8")
AR = (FIXTURES / "ar_notice.txt").read_text(encoding="utf-8")


def _stub_classify(values: Dict[str, Any]) -> Any:
    """Deterministic stand-in for the Laya classifier."""
    def _classify(text: str, *, lang: str = "fr") -> Dict[str, Any]:
        return {"values": dict(values), "confidence": {"sector": 0.9, "contract_type": 0.9}}
    return _classify


class TestSplitNotices:
    def test_fr_splits_in_two(self):
        blocks = split_notices(FR)
        assert len(blocks) == 2
        assert "BATIMETAL" in blocks[0]
        assert "ESI" in blocks[1]

    def test_ar_splits_in_two(self):
        blocks = split_notices(AR)
        assert len(blocks) == 2

    def test_no_anchor_single_block(self):
        assert len(split_notices("some text without anchors")) == 1


class TestExtractFR:
    offers = extract_offers(FR, source_name="Test FR", source_slug="test-fr",
                            issue_date=dt.date(2026, 9, 30),
                            classify=_stub_classify({"sector": "Private",
                                                     "contract_type": "CDI"}))

    def test_two_offers(self):
        assert len(self.offers) == 2

    def test_first_org_and_title(self):
        o = self.offers[0]
        assert o.organization_or_company and "BATIMETAL" in o.organization_or_company
        assert o.job_title and "ingénieur" in o.job_title.lower()

    def test_deadline(self):
        o = self.offers[0]
        assert o.application_deadline == "2026-10-25"
        assert o.deadline_kind == "absolute"

    def test_contacts(self):
        o = self.offers[0]
        assert o.contact_info["email"] == "recrutement@batimetal-dz.com"
        assert o.contact_info["phone"] == "025410892"

    def test_wilaya(self):
        assert self.offers[0].wilaya_location == "Blida"

    def test_laya_values_flow_through(self):
        assert self.offers[0].sector == "Private"
        assert self.offers[1].contract_type == "CDI"

    def test_positions(self):
        # "04 postes" in the ESI notice
        assert self.offers[1].positions_count == 4


class TestExtractAR:
    offers = extract_offers(AR, source_name="Test AR", source_slug="test-ar",
                            issue_date=dt.date(2026, 9, 30),
                            classify=_stub_classify({"sector": "Public",
                                                     "contract_type": "Statutaire"}))

    def test_two_offers(self):
        assert len(self.offers) == 2

    def test_public_org(self):
        o = self.offers[0]
        assert o.organization_or_company and "مديرية" in o.organization_or_company
        assert o.job_title and "مهندس" in o.job_title

    def test_relative_deadline_resolved(self):
        o = self.offers[0]
        assert o.deadline_kind == "relative"
        assert o.application_deadline == "2026-10-15"  # issue + 15 days

    def test_arabic_phone(self):
        assert self.offers[0].contact_info["phone"] == "033800000"

    def test_second_offer_contacts(self):
        o = self.offers[1]
        assert o.contact_info["email"] == "recrute@spar-oran.dz"
        assert o.application_deadline == "2026-11-20"
        assert o.wilaya_location == "Oran"

    def test_language_tagged(self):
        assert all(o.language == "ar" for o in self.offers)


class TestDedup:
    def test_same_org_title_deadline_collapses(self):
        offers = extract_offers(FR, source_name="T", source_slug="t",
                                classify=_stub_classify({"sector": "Private",
                                                         "contract_type": "CDI"}))
        doubled = offers + [type(offers[0])(**{**offers[0].__dict__})]
        assert len(dedupe_offers(doubled)) == len(offers)
