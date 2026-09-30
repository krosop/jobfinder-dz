"""Tests for layajobs.normalize — dates, wilayas, phones, emails."""
from __future__ import annotations

import datetime as dt

import pytest

from layajobs import normalize


class TestParseDate:
    def test_french_month(self):
        assert normalize.parse_date("avant le 25 octobre 2026") == dt.date(2026, 10, 25)

    def test_french_first_of_month(self):
        assert normalize.parse_date("le 1er novembre 2026") == dt.date(2026, 11, 1)

    def test_numeric_day_first(self):
        # Algerian convention: day/month/year
        assert normalize.parse_date("dossier avant le 05/03/2027") == dt.date(2027, 3, 5)

    def test_iso(self):
        assert normalize.parse_date("2026-01-15") == dt.date(2026, 1, 15)

    def test_arabic_month(self):
        assert normalize.parse_date("في أجل أقصاه 20 نوفمبر 2026") == dt.date(2026, 11, 20)

    def test_garbage_returns_none(self):
        assert normalize.parse_date("aucune date ici") is None
        assert normalize.parse_date("") is None

    def test_impossible_date_returns_none(self):
        assert normalize.parse_date("le 31 février 2026") is None


class TestRelative:
    def test_french_days(self):
        assert normalize.parse_relative_days("dans un délai de 15 jours") == 15

    def test_arabic_days(self):
        assert normalize.parse_relative_days("في أجل أقصاه 15 يوما من تاريخ النشر") == 15

    def test_month_word(self):
        assert normalize.parse_relative_days("dans un délai d'un mois") == 30

    def test_resolve_anchors_to_issue_date(self):
        iso, kind = normalize.resolve_deadline(
            "15 يوما من تاريخ النشر", issue_date=dt.date(2026, 9, 30))
        assert iso == "2026-10-15"
        assert kind == "relative"

    def test_absolute_wins_over_relative(self):
        iso, kind = normalize.resolve_deadline("avant le 25 octobre 2026 ou 10 jours")
        assert kind == "absolute"
        assert iso == "2026-10-25"


class TestWilayas:
    def test_french(self):
        assert normalize.match_wilaya("Blida") == "Blida"

    def test_arabic(self):
        assert normalize.match_wilaya("ولاية باتنة") == "Batna"

    def test_case_accent_insensitive(self):
        assert normalize.match_wilaya("ANNABA") == "Annaba"
        assert normalize.match_wilaya("tizi ouzou") == "Tizi Ouzou"

    def test_algiers_alias(self):
        assert normalize.match_wilaya("الجزائر العاصمة") == "Alger"

    def test_unknown_returns_none(self):
        assert normalize.match_wilaya(" nowhere ") is None
        assert normalize.match_wilaya("") is None


class TestContacts:
    def test_landline(self):
        assert normalize.extract_phones("Tél : 025.41.08.92") == ["025410892"]

    def test_mobile(self):
        assert normalize.extract_phones("0661 22 33 44") == ["0661223344"]

    def test_arabic_digits(self):
        assert normalize.extract_phones("الهاتف: ٠٣٣٨٠٠٠٠٠") == ["033800000"]

    def test_no_random_numbers(self):
        assert normalize.extract_phones("commande n° 1234567890123456") == []

    def test_email(self):
        assert normalize.extract_emails("écrire à Recrutement@Batimetal-dz.com.") == \
            ["recrutement@batimetal-dz.com"]

    def test_deadline_context(self):
        assert normalize.looks_like_deadline_context("au plus tard le 25 octobre")
        assert normalize.looks_like_deadline_context("في أجل أقصاه 15 يوما")
        assert not normalize.looks_like_deadline_context("la réunion se tiendra le 12 mars")
