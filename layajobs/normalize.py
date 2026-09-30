"""Normalize extracted values: dates, wilayas, phones, emails, contact blocks.

Pure Python, deterministic, bilingual (FR/AR). Everything here returns None rather
than guessing: a null field beats a hallucinated one.
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Optional

# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

FRENCH_MONTHS = {
    "janvier": 1, "fevrier": 1, "février": 1, "janv": 1,
    "fevrier": 2, "février": 2, "fev": 2, "fév": 2,
    "mars": 3, "mar": 3,
    "avril": 4, "avr": 4,
    "mai": 5,
    "juin": 6, "jun": 6,
    "juillet": 7, "juil": 7, "jul": 7,
    "aout": 8, "août": 8, "aou": 8, "aoû": 8,
    "septembre": 9, "sept": 9, "sep": 9,
    "octobre": 10, "oct": 10,
    "novembre": 11, "nov": 11,
    "decembre": 12, "décembre": 12, "dec": 12, "déc": 12,
}

# Arabic month names (Maghreb usage often keeps French month names; these are the
# classical / Levantine names that do appear in Algerian notices).
ARABIC_MONTHS = {
    "يناير": 1, "كانون الثاني": 1,
    "فبراير": 2, "شباط": 2,
    "مارس": 3, "آذار": 3,
    "أبريل": 4, "ابريل": 4, "نيسان": 4,
    "ماي": 5, "أيار": 5, "ايار": 5,
    "يونيو": 6, "يونيو": 6, "حزيران": 6,
    "يوليو": 7, "يوليو": 7, "تموز": 7,
    "أغسطس": 8, "اغسطس": 8, "آب": 8,
    "سبتمبر": 9, "أيلول": 9, "ايلول": 9,
    "أكتوبر": 10, "اكتوبر": 10, "تشرين الأول": 10,
    "نوفمبر": 11, "تشرين الثاني": 11,
    "ديسمبر": 12, "كانون الأول": 12,
}

_MONTH_ALIASES = {**FRENCH_MONTHS, **ARABIC_MONTHS}

# "15 janvier 2026" / "15 يناير 2026" / "15 janvier 26"
_DATE_TEXT_RE = re.compile(
    r"\b(\d{1,2})(?:er|eme|ème)?\s+([A-Za-zÀ-ÿ\u0600-\u06FF]+(?:\s+[A-Za-zÀ-ÿ\u0600-\u06FF]+)?)\s+(\d{4}|\d{2})\b"
)

# ISO and numeric dates: 2026-01-15, 15/01/2026, 15-01-2026
_DATE_NUMERIC_RE = re.compile(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b|\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b")

# Relative deadlines: "15 jours", "quinze (15) jours", "15 يوما", "un mois".
# Number words are accepted because notices write "délai d'un mois".
_RELATIVE_RE = re.compile(
    r"(?:\b(un|une|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|quinze)\b|(\d{1,3}))"
    r"\s*(?:\(\s*\d{1,3}\s*\)\s*)?"
    r"(jours|jour|يوم|أيام|ايام|mois|month|شهر|أشهر|اشهر|ans|an|سنة|سنوات)"
, re.IGNORECASE)

_WORD_NUMBERS = {"un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5,
                 "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10, "quinze": 15}

_REL_UNITS_DAYS = {"jour": 1, "jours": 1, "يوم": 1, "أيام": 1, "ايام": 1,
                   "mois": 30, "month": 30, "شهر": 30, "أشهر": 30, "اشهر": 30,
                   "an": 365, "ans": 365, "سنة": 365, "سنوات": 365}

# Deadline context markers: text right before/after a date that marks it as a deadline.
_DEADLINE_MARKERS = [
    "date limite", "délai", "delai", "au plus tard", "clôture", "cloture",
    "dernier délai", "dernier delai", "avant le", "jusqu'au", "jusqu au",
    "candidatures", "dépôt des candidatures", "depot des dossiers",
    "أجل", "أجلى", "آخر أجل", "موعد", "قبل", "في أجل", "أقصاه", "أقصى",
]


def _month_from_word(word: str) -> Optional[int]:
    w = word.strip().lower()
    if w in _MONTH_ALIASES:
        return _MONTH_ALIASES[w]
    # Arabic multi-word months ("كانون الثاني")
    for alias, num in ARABIC_MONTHS.items():
        if " " in alias and alias in word.lower():
            return num
    return None


def parse_date(text: str, *, issue_date: Optional[_dt.date] = None) -> Optional[_dt.date]:
    """Parse an absolute date (FR/AR month names, ISO, d/m/y) from a fragment.

    Two-digit years are rolled forward within 1990-2089. Ambiguous d/m versus
    m/d is resolved as day-first (Algerian convention).
    """
    if not text:
        return None

    m = _DATE_NUMERIC_RE.search(text)
    if m:
        if m.group(1):  # ISO y-m-d
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:           # d/m/y, day-first
            d, mo, y = int(m.group(4)), int(m.group(5)), int(m.group(6))
        if y < 100:
            y = 2000 + y if y < 90 else 1900 + y
        try:
            return _dt.date(y, mo, d)
        except ValueError:
            return None

    m = _DATE_TEXT_RE.search(text)
    if m:
        day, month_word, year = int(m.group(1)), m.group(2), m.group(3)
        month = _month_from_word(month_word)
        if month is None:
            return None
        y = int(year)
        if y < 100:
            y = 2000 + y if y < 90 else 1900 + y
        try:
            return _dt.date(y, month, day)
        except ValueError:
            return None
    return None


def parse_relative_days(text: str) -> Optional[int]:
    """Parse '15 jours' / 'un mois' / '15 يوما' into a day count, if present."""
    if not text:
        return None
    m = _RELATIVE_RE.search(text)
    if not m:
        return None
    n = _WORD_NUMBERS.get((m.group(1) or "").lower()) or int(m.group(2))
    unit = m.group(3).lower()
    return n * _REL_UNITS_DAYS.get(unit)


def resolve_deadline(
    raw: str,
    *,
    issue_date: Optional[_dt.date] = None,
) -> tuple[Optional[str], Optional[str]]:
    """Resolve a raw deadline fragment into (ISO date or None, kind).

    kind is one of "absolute", "relative", "unparseable". Absolute dates win;
    relative delays are anchored to `issue_date` when given.
    """
    raw = (raw or "").strip()
    if not raw:
        return None, "unparseable"
    d = parse_date(raw)
    if d:
        return d.isoformat(), "absolute"
    days = parse_relative_days(raw)
    if days is not None:
        base = issue_date or _dt.date.today()
        return (base + _dt.timedelta(days=days)).isoformat(), "relative"
    return None, "unparseable"


# ---------------------------------------------------------------------------
# Wilayas (the 58 Algerian provinces, FR + AR)
# ---------------------------------------------------------------------------

# code -> (french, arabic). Ordered by code; matching is accent/case-insensitive.
WILAYAS: dict[int, tuple[str, str]] = {
    1: ("Adrar", "أدرار"), 2: ("Chlef", "الشلف"), 3: ("Laghouat", "الأغواط"),
    4: ("Oum El Bouaghi", "أم البواقي"), 5: ("Batna", "باتنة"), 6: ("Béjaïa", "بجاية"),
    7: ("Biskra", "بسكرة"), 8: ("Béchar", "بشار"), 9: ("Blida", "البليدة"),
    10: ("Bouira", "البويرة"), 11: ("Tamanrasset", "تمنراست"), 12: ("Tébessa", "تبسة"),
    13: ("Tlemcen", "تلمسان"), 14: ("Tiaret", "تيارت"), 15: ("Tizi Ouzou", "تيزي وزو"),
    16: ("Alger", "الجزائر"), 17: ("Djelfa", "الجلفة"), 18: ("Jijel", "جيجل"),
    19: ("Sétif", "سطيف"), 20: ("Saïda", "سعيدة"), 21: ("Skikda", "سكيكدة"),
    22: ("Sidi Bel Abbès", "سيدي بلعباس"), 23: ("Annaba", "عنابة"), 24: ("Guelma", "قالمة"),
    25: ("Constantine", "قسنطينة"), 26: ("Médéa", "المدية"), 27: ("Mostaganem", "مستغانم"),
    28: ("M'Sila", "المسيلة"), 29: ("Mascara", "معسكر"), 30: ("Ouargla", "ورقلة"),
    31: ("Oran", "وهران"), 32: ("El Bayadh", "البيض"), 33: ("Illizi", "إليزي"),
    34: ("Bordj Bou Arreridj", "برج بوعريريج"), 35: ("Boumerdès", "بومرداس"),
    36: ("El Tarf", "الطارف"), 37: ("Tindouf", "تندوف"), 38: ("Tissemsilt", "تيسمسيلت"),
    39: ("El Oued", "الوادي"), 40: ("Khenchela", "خنشلة"), 41: ("Souk Ahras", "سوق أهراس"),
    42: ("Tipaza", "تيبازة"), 43: ("Mila", "ميلة"), 44: ("Aïn Defla", "عين الدفلى"),
    45: ("Naâma", "النعامة"), 46: ("Aïn Témouchent", "عين تموشنت"),
    47: ("Ghardaïa", "غرداية"), 48: ("Relizane", "غليزان"),
    49: ("Timimoun", "تيميمون"), 50: ("Bordj Badji Mokhtar", "برج باجي مختار"),
    51: ("Ouled Djellal", "أولاد جلال"), 52: ("Béni Abbès", "بني عباس"),
    53: ("In Salah", "عين صالح"), 54: ("In Guezzam", "عين قزام"),
    55: ("Touggourt", "تقرت"), 56: ("Djanet", "جانت"),
    57: ("El M'Ghair", "المغير"), 58: ("El Meniaa", "المنيعة"),
}

_ALGIER_ALIASES = {"alger", "الجزائر العاصمة", "el djazair", "الجزائرية"}


def _fold(text: str) -> str:
    """Casefold + strip common French diacritics for tolerant matching."""
    table = str.maketrans("àâäéèêëîïôöùûüçÀÂÄÉÈÊËÎÏÔÖÙÛÜÇ", "aaaeeeeiioouuucAAAEEEEIIOOUUUC")
    return text.translate(table).casefold().strip()


def match_wilaya(text: str) -> Optional[str]:
    """Return the canonical French wilaya name if `text` names one, else None."""
    if not text:
        return None
    folded = _fold(text)
    # Exact / substring match against every alias.
    best: tuple[int, str] | None = None
    for code, (fr, ar) in WILAYAS.items():
        for alias in (fr, ar):
            a = _fold(alias)
            if a and a in folded:
                # Prefer the longest alias hit (El Oued vs El ..., Batna vs Batna-xyz)
                if best is None or len(a) > best[0]:
                    best = (len(a), fr)
    # Algiers spellings that differ from the canonical entry
    for alias in _ALGIER_ALIASES:
        if _fold(alias) in folded:
            if best is None or len(_fold(alias)) > best[0]:
                best = (len(_fold(alias)), "Alger")
    return best[1] if best else None


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------

# Algerian numbers: +213, 0 (5|6|7) mobiles, 0 (2|3|4) landlines; tolerate dots,
# spaces and dashes as separators. Only match sequences of >= 9 digits.
_PHONE_RE = re.compile(
    r"(?:\+?213[\s.\-]?|0(?=[2-7]))"
    r"(?:[\s.\-]?\d){7,9}"
)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def normalize_phone(raw: str) -> Optional[str]:
    """Clean a phone number to digits (+international form when clear)."""
    if not raw:
        return None
    raw = raw.translate(_AR_DIGITS)
    digits = re.sub(r"[^\d+]", "", raw)
    if digits.startswith("+213"):
        pass
    elif digits.startswith("213"):
        digits = "+" + digits
    elif digits.startswith("0") and 9 <= len(digits) <= 10:
        pass  # national format, keep as-is
    else:
        return None
    if not (9 <= len(digits.lstrip("+")) <= 13):
        return None
    return digits


def extract_phones(text: str) -> list[str]:
    """Find all phone-looking numbers in a text block, normalized."""
    # Arabic-Indic digits must be folded before the regex runs.
    text = (text or "").translate(_AR_DIGITS)
    out, seen = [], set()
    for m in _PHONE_RE.finditer(text):
        num = normalize_phone(m.group(0))
        if num and num not in seen:
            seen.add(num)
            out.append(num)
    return out


def extract_emails(text: str) -> list[str]:
    """Find all email addresses in a text block (lowercased, deduped)."""
    out, seen = [], set()
    for m in _EMAIL_RE.finditer(text or ""):
        e = m.group(0).lower().rstrip(".")
        if e not in seen:
            seen.add(e)
            out.append(e)
    return out


def looks_like_deadline_context(text: str) -> bool:
    """True when a fragment carries deadline language, not just any date."""
    t = (text or "").lower()
    return any(marker in t for marker in _DEADLINE_MARKERS)
