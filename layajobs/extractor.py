"""Rule-based extraction of job offers from gated newspaper text.

Bilingual (FR/AR) deterministic rules pull free-text fields — titles, orgs,
deadlines, qualifications, contacts — that Laya cannot generate. Laya still
decides the enum fields (sector, contract_type) via an injected classifier,
so tests can stub it and the pipeline degrades gracefully without it.

Every field that cannot be grounded in the text stays None / []: the caller's
schema keeps nulls rather than hallucinated values.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from typing import Any, Callable, Dict, List, Optional

from . import normalize

# ---------------------------------------------------------------------------
# Notice boundaries
# ---------------------------------------------------------------------------

# Strong anchors: a match very likely starts a new notice.
_ANCHORS = [
    r"avis\s+de\s+recrutement",
    r"offre[s]?\s+d['\u2019]emploi",
    r"appel\s+(?:\u00e0|a)\s+candidature[s]?",
    r"concours\s+(?:de\s+recrutement|sur\s+\u00e9preuves|sur\s+fichiers|sur\s+tests|sur\s+dossier|d['\u2019]admission|national)",
    r"recrute\b",
    r"\u0625\u0639\u0644\u0627\u0646\s+\u062a\u0648\u0638\u064a\u0641",          # إعلان توظيف
    r"(\u0625|\u0627)\u0639\u0644\u0627\u0646\s+\u0648\u0638\u0627\u0626\u0641",  # إعلان وظائف
    r"\u0645\u0633\u0627\u0628\u0642\u0629\s+\u062a\u0648\u0638\u064a\u0641",     # مسابقة توظيف
    r"\u0645\u0633\u0627\u0628\u0642\u0629\s+\u0639\u0644\u0649\s+\u0623\u0633\u0627\u0633\s+\u0627\u0644\u0634\u0647\u0627\u062f\u0629",  # مسابقة على أساس الشهادة
    r"\u0639\u0631\u0648\u0636\s+\u0639\u0645\u0644",                              # عروض عمل
    r"\u0645\u0646\u0627\u0635\u0628\s+\u0645\u0627\u0644\u064a\u0629",            # مناصب مالية
]
_ANCHOR_RE = re.compile(
    "|".join("(?m:^[ \\t]*" + a + ")" for a in _ANCHORS), re.IGNORECASE)


def split_notices(text: str) -> List[str]:
    """Split a chunk into notice blocks at anchor boundaries.

    Anchors only count at line start: print notices carry a heading line
    ("AVIS DE RECRUTEMENT", "إعلان توظيف"), while the same words mid-line
    ("... recrute ...", "فتح مسابقة توظيف ...") are body text, not boundaries.
    Overlapping matches at the same position keep the longest anchor.
    Text with no anchor (but which passed the gate) becomes one block.
    """
    text = text or ""
    matches = [m for m in _ANCHOR_RE.finditer(text)]
    # Drop overlaps: sort by (start, longest first), skip anything that begins
    # inside the previous kept match.
    kept: List[re.Match] = []
    for m in sorted(matches, key=lambda m: (m.start(), -(m.end() - m.start()))):
        if kept and m.start() < kept[-1].end():
            continue
        kept.append(m)
    if not kept:
        return [text.strip()] if text.strip() else []
    blocks: List[str] = []
    starts = [m.start() for m in kept]
    if starts[0] > 0:
        blocks.append(text[: starts[0]].strip())
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        block = text[start:end].strip()
        if block:
            blocks.append(block)
    return [b for b in blocks if len(b.split()) >= 4]


# ---------------------------------------------------------------------------
# Bilingual lexicons
# ---------------------------------------------------------------------------

_RANK_WORDS = [
    # FR
    r"ing[eé]nieur", r"technicien", r"comptable", r"cadre", r"secr[eé]taire",
    r"d[eé]veloppeur", r"informaticien", r"administrateur", r"[eé]conomiste",
    r"gestionnaire", r"magasinier", r"chauffeur", r"livreur", r"ouvrier",
    r"commercial", r"vendeur", r"pharmacien", r"m[eé]decin", r"chirurgien",
    r"sage[- ]femme", r"infirmi[eè]re?", r"enseignant", r"formateur",
    r"architecte", r"topographe", r"juriste", r"consultant", r"fiscaliste",
    r"soudeur", r"menuisier", r"[eé]lectricien", r"plombier", r"m[eé]canicien",
    r"attach[eé]", r"r[eé]dacteur", r"inspecteur", r"professeur",
    r"ma[iî]tre\s+de\s+conf[eé]rences", r"traducteur", r"biblioth[eé]caire",
    r"sociologue", r"d[eé]mographe", r"psychologue", r"directeur",
    r"chef\s+de\s+(?:service|d[eé]partement)", r"contr[oô]leur",
    r"planificateur", r"statisticien", r"biologiste", r"v[eé]t[eé]rinaire",
    r"procureur", r"juge", r"greffier", r"agent\s+(?:de\s+|d')\w+",
    # AR — deliberately excludes إطار (= "framework" in legal news) and
    # ملاحظ (= matches ملاحظة "note"): both too generic for rank detection.
    r"\u0645\u0647\u0646\u062f\u0633",        # مهندس (engineer)
    r"\u0645\u0633\u0627\u0639\u062f",        # مساعد (assistant)
    r"\u062a\u0642\u0646\u064a",            # تقني (technician)
    r"\u0643\u0627\u062a\u0628",            # كاتب (clerk)
    r"\u0645\u0644\u062d\u0627\u0642",        # ملحق (attaché)
    r"\u0645\u062d\u0627\u0633\u0628",        # محاسب (accountant)
    r"\u0633\u0643\u0631\u062a\u064a\u0631",  # سكرتير
    r"\u0633\u0627\u0626\u0642",              # سائق (driver)
    r"\u0639\u0627\u0645\u0644",              # عامل
    r"\u0628\u0627\u0626\u0639",              # بائع (seller)
    r"\u0635\u064a\u0627\u062f\u0644",        # صيدلي
    r"\u0637\u0628\u064a\u0628",              # طبيب
    r"\u0645\u0645\u0631\u0636",              # ممرض
    r"\u0645\u0639\u0644\u0645",              # معلم
    r"\u0623\u0633\u0627\u0630\u062a",        # أستاذ
    r"\u0645\u062f\u064a\u0631",              # مدير
    r"\u0645\u0641\u0627\u0648\u0636",        # مفوض
    r"\u0645\u0631\u0627\u0642\u0628",        # مراقب
    r"\u0645\u062e\u0628\u0631",              # مخبر
    r"\u062d\u0631\u0641\u064a",              # حرفي
]
_RANK_RE = re.compile("|".join(_RANK_WORDS), re.IGNORECASE)

_ORG_KEYWORDS = [
    r"S\.?A\.?R\.?L", r"E\.?U\.?R\.?L", r"S\.?P\.?A\.?", r"S\.?N\.?C", r"EPE", r"EPIC",
    r"soci[eé]t[eé]", r"entreprise", r"groupe", r"agence", r"direction",
    r"[eé]tablissement", r"universit[eé]", r"h[oô]pital", r"centre", r"commune",
    r"wilaya", r"daira", r"cabinet", r"clinique", r"\u00e9cole", r"institut",
    r"laboratoire", r"banque", r"assurance", r"h[oô]tel", r"restaurant",
    # AR
    r"\u0634\u0631\u0643\u0629",        # شركة
    r"\u0645\u0624\u0633\u0633\u0629",  # مؤسسة
    r"\u0645\u062f\u064a\u0631\u064a\u0629",  # مديرية
    r"\u0645\u0631\u0641\u0642",        # مرفق
    r"\u062c\u0627\u0645\u0639\u0629",  # جامعة
    r"\u0645\u0633\u062a\u0634\u0641\u0649",  # مستشفى
    r"\u0628\u0644\u062f\u064a\u0629",  # بلدية
    r"\u0648\u0644\u0627\u064a\u0629",  # ولاية
    r"\u062f\u0627\u0626\u0631\u0629",  # دائرة
    r"\u0648\u0643\u0627\u0644\u0629",  # وكالة
    r"\u062f\u064a\u0648\u0627\u0646",  # ديوان
    r"\u0645\u0639\u0647\u062f",        # معهد
    r"\u0645\u062c\u0645\u0639",        # مجمع
    r"\u0645\u062c\u0645\u0648\u0639\u0629",  # مجموعة
    r"\u0645\u062f\u0631\u0633\u0629",  # مدرسة
]
_ORG_KW_RE = re.compile("|".join(_ORG_KEYWORDS), re.IGNORECASE)

_ORG_VERBS = [
    r"recrute", r"cherche", r"recherche", r"souhaite\s+recruter",
    r"ouvre\s+un\s+concours", r"lance\s+un\s+avis",
    r"\u062a\u0639\u0644\u0646",      # تعلن
    r"\u064a\u0639\u0644\u0646",      # يعلن
    r"\u062a\u0628\u062d\u062b",      # تبحث
    r"\u062a\u0633\u062a\u0639\u0645\u0644",  # تستعمل
    r"\u062a\u0648\u0638\u0641",      # توظف
]
# \b so "recrute" never matches inside "recrutement" (heading lines).
_ORG_VERB_RE = re.compile(r"\b(?:" + "|".join(_ORG_VERBS) + r")\b", re.IGNORECASE)

_TITLE_PATTERNS = [
    r"postes?\s+(?:de\s+d'[eé]tape\s+)?(?:de\s+|:\s*)([^.;\n]{4,90})",
    r"au\s+poste\s+de\s+([^.;\n]{4,90})",
    r"grade\s+(?:de\s+|:\s*)([^.;\n]{4,90})",
    r"pour\s+le\s+(?:compte\s+de\s+)?([^.;\n]{4,90})",
    r"\u0644\u0644[\u0627\u0625]\u0644\u062a\u062d\u0627\u0642\s+\u0628\u0631\u062a\u0628\u0629\s*[:\u061b]?\s*([^\u061b.\n]{4,120})",  # للالتحاق/للإلتحاق برتبة:
    r"\u0631\u062a\u0628\u0629\s*[:\u061b]\s*([^\u061b.\n]{4,120})",  # رتبة:
]

_QUAL_LABELS = [
    r"dipl[oô]me", r"profil", r"conditions?", r"exp[eé]rience", r"sp[eé]cialit[eé]",
    r"qualification", r"formation",
    r"\u0627\u0644\u0634\u0631\u0648\u0637",   # الشروط
    r"\u0627\u0644\u0645\u0624\u0647\u0644",   # المؤهل
    r"\u0627\u0644\u0634\u0647\u0627\u062f\u0629",  # الشهادة
    r"\u0627\u0644\u062a\u062e\u0635\u0635",   # التخصص
    r"\u0627\u0644\u062e\u0628\u0631\u0629",   # الخبرة
]
_QUAL_LABEL_RE = re.compile(r"^\s*(?:" + "|".join(_QUAL_LABELS) + r")\b\s*[:\u061b]?\s*", re.IGNORECASE)

_BULLET_RE = re.compile(r"^\s*[-\u2022\u25cf*\u2013]\s+")

_POSITIONS_RE = re.compile(
    r"(\d{1,3})\s*(?:\(\s*\d{1,3}\s*\)\s*)?\s*"
    r"(postes?|places?|emplois?|\u0645\u0646\u0635\u0628|\u0645\u0646\u0627\u0635\u0628|\u0645\u0648\u0627\u0639\u064a\u062f)",
    re.IGNORECASE)
_POSITIONS_AR_FIRST_RE = re.compile(
    r"(\u0645\u0646\u0635\u0628|\u0645\u0646\u0627\u0635\u0628)\s*[:\u061b]?\s*(\d{1,3})")

_DEADLINE_MARKER = (
    r"(?:date\s+limite|d[eé]lai|delai|au\s+plus\s+tard|cl[oô]ture|avant\s+le|"
    r"candidatures?\s+.{0,30}(?:avant|jusqu)|d[eé]p[oô]t\s+des\s+dossiers|"
    r"\u0641\u064a\s+\u0623\u062c\u0644|\u0623\u0642\u0635\u0627\u0647|\u0623\u0642\u0635\u0649|\u0642\u0628\u0644|\u0622\u062e\u0631\s+\u0623\u062c\u0644|\u0645\u0648\u0639\u062f)"
)
_DEADLINE_SENT_RE = re.compile(
    r"[^\n.;\u061b]*" + _DEADLINE_MARKER + r"[^\n.;\u061b]*", re.IGNORECASE)

_AR_CHAR_RE = re.compile(r"[\u0600-\u06FF]")


def _lang_of(text: str) -> str:
    if not text:
        return "fr"
    ar = len(_AR_CHAR_RE.findall(text))
    letters = max(1, sum(ch.isalpha() for ch in text))
    return "ar" if ar / letters >= 0.3 else "fr"


def _clean(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    s = re.sub(r"\s+", " ", s).strip(" :;,.،؛-\u2013\u2014")
    return s or None


# Titles/orgs that look like admin notes, conditions, or document names —
# common in web-published announcements (not print classifieds).
_JUNK_TITLE_RE = re.compile(
    r"^\s*(\u0645\u0644\u0627\u062d\u0638\u0629|\u0623\u0646\u0652?\s|\u0634\u0647\u0627\u062f\u0629\s+\u0637\u0628\u064a\u0629|\u0641\u064a\s+\u0625\u0637\u0627\u0631|"
    r"note|n\.?b\.?|\u0633\u064a\u062a\u0645|\u0642\u0627\u0626\u0645\u0629)", re.IGNORECASE)
_JUNK_ORG_RE = re.compile(
    r"^\s*(\u0623\u0646\u0652?\s|\u0627\u0644\u0630\u064a|\u0627\u0644\u062a\u064a|\u062d\u064a\u062b|\u0627\u0644\u0645\u062a\u0631\u0634\u062d|\u0644\u0627\s+\u064a\u0643\u0648\u0646)", re.IGNORECASE)


def _plausible_title(title: Optional[str]) -> bool:
    if not title:
        return False
    words = title.split()
    if not (2 <= len(words) <= 14):
        return False
    # News-headline vocabulary: ministry news about meetings, agreements and
    # calendars mentions "concours" without offering any post.
    if re.search(r"\u0645\u062d\u0627\u0636\u0631|\u0634\u0631\u0627\u0643\u0629|\u0627\u062a\u0641\u0627\u0642\u064a\u0629|\u0631\u0632\u0646\u0627\u0645\u0629|\u0646\u062f\u0648\u0629|\u0645\u0644\u062a\u0642\u0649|\u0627\u062c\u062a\u0645\u0627\u0639|\u0644\u0642\u0627\u0621|\u062a\u0639\u0632\u064a\u0632|\u0645\u0628\u0627\u062f\u0631\u0629", title):
        return False
    if _JUNK_TITLE_RE.search(title):
        return False
    return True


def _plausible_org(org: Optional[str]) -> bool:
    if not org:
        return False
    if len(org.split()) > 16 or _JUNK_ORG_RE.search(org):
        return False
    return True


# ---------------------------------------------------------------------------
# Field rules
# ---------------------------------------------------------------------------

def _find_title(block: str) -> Optional[str]:
    # 1) explicit "poste de X" / "رتبة: X" patterns
    for pat in _TITLE_PATTERNS:
        m = re.search(pat, block, re.IGNORECASE)
        if m:
            title = _clean(m.group(1))
            if title and _RANK_RE.search(title):
                return title
    # 2) first line containing a rank word
    for line in block.splitlines():
        line = line.strip()
        if 4 <= len(line) <= 120 and _RANK_RE.search(line):
            # drop org-verb tails like "SARL X recrute un comptable"
            m = _ORG_VERB_RE.search(line)
            if m and m.start() < _RANK_RE.search(line).start():
                tail = line[m.end():]
                rank = _RANK_RE.search(tail)
                if rank:
                    return _clean(tail[rank.start():])
            return _clean(line)
    return None


def _find_org(block: str) -> Optional[str]:
    for line in block.splitlines():
        line = line.strip()
        if not line or len(line) > 200:
            continue
        vm = _ORG_VERB_RE.search(line)
        if vm:
            subject = line[: vm.start()].strip()
            # "La société SARL X, spécialisée ..., recrute" -> keep "La société SARL X";
            # Arabic verb-first "تعلن مديرية ... عن فتح" handled below.
            subject = re.split(r"[,،]|\s+عن\s+", subject)[0].strip(" :\u2013-")
            subject = _clean(subject)
            if subject and (_ORG_KW_RE.search(subject) or len(subject.split()) >= 2):
                return subject
            # verb-first Arabic: "تعلن مديرية ... عن" -> org after verb;
            # also cut before event-noun phrases (تنظيم مسابقة, نتائج ...).
            after = line[vm.end():]
            after = re.split(r"[,،]|\s+عن\s+|\s+\u062a\u0646\u0638\u064a\u0645\s+|\s+\u0646\u062a\u0627\u0626\u062c\s+", after)[0]
            after_m = _ORG_KW_RE.search(after)
            if after_m:
                return _clean(after[after_m.start(): after_m.start() + 80])
        km = _ORG_KW_RE.search(line)
        if km and len(line.split()) <= 12:
            head = re.split(r"[,،]", line)[0]
            # An organization never starts with a job rank — that is a
            # title line ("كاتب مديرية رئيسي") whose keyword fooled us.
            if _RANK_RE.match(head.strip()):
                continue
            return _clean(head) or _clean(line)
    return None


def _find_deadline(block: str, issue_date) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Returns (raw fragment, ISO date, kind)."""
    for line in block.splitlines():
        if not normalize.looks_like_deadline_context(line):
            continue
        m = _DEADLINE_SENT_RE.search(line)
        fragment = _clean(m.group(0)) if m else _clean(line)
        if not fragment:
            continue
        iso, kind = normalize.resolve_deadline(fragment, issue_date=issue_date)
        if iso or kind == "relative":
            return fragment, iso, kind
    # last resort: any date anywhere, only if the block has deadline words
    if normalize.looks_like_deadline_context(block):
        iso, kind = normalize.resolve_deadline(block, issue_date=issue_date)
        if iso:
            return _clean(block[:120]), iso, kind
    return None, None, None


def _find_qualifications(block: str) -> List[str]:
    quals: List[str] = []
    lines = block.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        m = _QUAL_LABEL_RE.match(stripped)
        if m:
            content = _clean(stripped[m.end():])
            if content:
                quals.append(content)
            # gather following bullet/short lines
            for follow in lines[i + 1: i + 5]:
                f = follow.strip()
                if not f:
                    break
                if _QUAL_LABEL_RE.match(f) or len(f) > 200:
                    break
                if _BULLET_RE.match(f):
                    quals.append(_clean(_BULLET_RE.sub("", f)) or "")
                else:
                    quals.append(_clean(f) or "")
                if len(quals) >= 8:
                    return [q for q in quals if q]
        elif _BULLET_RE.match(stripped):
            body = _clean(_BULLET_RE.sub("", stripped))
            if body and (_RANK_RE.search(body) or normalize.match_wilaya(body)
                         or re.search(r"dipl[oô]me|\u0634\u0647\u0627\u062f\u0629|\u062e\u0628\u0631\u0629|exp[eé]rience", body, re.IGNORECASE)):
                quals.append(body)
    return [q for q in quals if q][:8]


def _find_contacts(block: str) -> Dict[str, Optional[str]]:
    emails = normalize.extract_emails(block)
    phones = normalize.extract_phones(block)
    portal = None
    address = None
    for line in block.splitlines():
        low = line.lower()
        if portal is None and (re.search(r"https?://|www\.", low) or
                               re.search(r"portail|site\s+web|candidature\s+en\s+ligne|\u0627\u0644\u0628\u0648\u0627\u0628\u0629", low, re.IGNORECASE)):
            portal = _clean(line)[:120]
        if address is None and re.search(
                r"adresse|\u0639\u0646\u0648\u0627\u0646|\u0645\u0642\u0631|\u062d\u064a\s|\u0634\u0627\u0631\u0639|cit[eé]\s|rue\s", low, re.IGNORECASE):
            address = _clean(line)[:160]
    return {
        "email": emails[0] if emails else None,
        "phone": phones[0] if phones else None,
        "address_or_portal": portal or address,
    }


def _find_positions(block: str) -> Optional[int]:
    m = _POSITIONS_RE.search(block)
    if m:
        try:
            n = int(m.group(1))
            return n if 1 <= n <= 999 else None
        except ValueError:
            return None
    m = _POSITIONS_AR_FIRST_RE.search(block)
    if m:
        try:
            n = int(m.group(2))
            return n if 1 <= n <= 999 else None
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Offer assembly
# ---------------------------------------------------------------------------

@dataclass
class Offer:
    """One extracted job offer with provenance."""

    source_newspaper: Optional[str]
    job_title: Optional[str]
    organization_or_company: Optional[str]
    sector: str
    contract_type: str
    wilaya_location: Optional[str]
    required_qualifications: List[str] = dc_field(default_factory=list)
    positions_count: Optional[int] = None
    application_deadline_raw: Optional[str] = None
    application_deadline: Optional[str] = None
    deadline_kind: Optional[str] = None
    contact_info: Dict[str, Optional[str]] = dc_field(default_factory=dict)
    language: str = "fr"
    source_slug: Optional[str] = None
    source_file: Optional[str] = None
    page: Optional[int] = None
    snippet: Optional[str] = None
    laya_confidence: Dict[str, float] = dc_field(default_factory=dict)
    gate: str = "laya"   # laya | keyword_fallback

    def to_json(self) -> Dict[str, Any]:
        return {
            "source_newspaper": self.source_newspaper,
            "job_title": self.job_title,
            "organization_or_company": self.organization_or_company,
            "sector": self.sector,
            "contract_type": self.contract_type,
            "wilaya_location": self.wilaya_location,
            "required_qualifications": self.required_qualifications,
            "positions_count": self.positions_count,
            "application_deadline": self.application_deadline,
            "application_deadline_raw": self.application_deadline_raw,
            "deadline_kind": self.deadline_kind,
            "contact_info": self.contact_info,
            "language": self.language,
            "source_slug": self.source_slug,
            "source_file": self.source_file,
            "page": self.page,
            "snippet": self.snippet,
            "laya_confidence": self.laya_confidence,
            "gate": self.gate,
        }


def _classify_block(block: str, lang: str,
                    classify: Optional[Callable[..., Dict[str, Any]]]) -> Dict[str, Any]:
    """Laya classification of enum fields, with graceful degradation."""
    if classify is None:
        try:
            from . import laya_engine
            classify = laya_engine.classify_offer
        except Exception:
            classify = None
    if classify is None:
        return {"values": {}, "confidence": {}}
    try:
        return classify(block, lang=lang)
    except Exception:
        return {"values": {}, "confidence": {}}


def _contract_override(block: str) -> Optional[str]:
    low = block.lower()
    if re.search(r"cdi|dur[eé]e\s+ind[eé]termin[eé]e", low):
        return "CDI"
    if re.search(r"cdd|dur[eé]e\s+d[eé]termin[eé]e", low):
        return "CDD"
    if re.search(r"fonction\s+publique|statutaire|\u0645\u0633\u0627\u0628\u0642\u0629\s+\u0639\u0644\u0649\s+\u0623\u0633\u0627\u0633\s+\u0627\u0644\u0634\u0647\u0627\u062f\u0629|\u0627\u0644\u0648\u0637\u0646\u064a\u0629", low):
        return "Statutaire"
    return None


def extract_offers(
    text: str,
    *,
    source_name: Optional[str] = None,
    source_slug: Optional[str] = None,
    source_file: Optional[str] = None,
    page: Optional[int] = None,
    issue_date=None,
    lang_hint: Optional[str] = None,
    gate_by: str = "laya",
    strict_rank: bool = False,
    classify: Optional[Callable[..., Dict[str, Any]]] = None,
) -> List[Offer]:
    """Extract structured offers from one gated chunk of newspaper text."""
    offers: List[Offer] = []
    blocks = split_notices(text)
    # When anchors exist, the preamble (text before the first anchor) is page
    # furniture — admin notes, program context, results tables. Skip it.
    has_anchors = bool(_ANCHOR_RE.search(text or ""))
    for block in blocks:
        if has_anchors and not _ANCHOR_RE.search(block):
            continue
        lang = lang_hint if lang_hint in ("fr", "ar") else _lang_of(block)
        title = _find_title(block)
        org = _find_org(block)
        # Sanity filters: drop admin notes / conditions posing as fields.
        if not _plausible_title(title):
            title = None
        if not _plausible_org(org):
            org = None
        # Required-document bullets ("شهادة ... تثبت أن ...", "1- شهادة
        # ماستر ...", "وشهادة الكفاءة ...") are candidate conditions, not
        # job titles — they start with a document word (after optional list
        # numbering and the conjunction و).
        if title and re.match(r"^\s*(?:\d{1,2}\s*[-.)]\s*)*\u0648?\s*\u0634\u0647\u0627\u062f\u0629", title):
            title = None
        # A block needs a plausible title or org to be a notice; the gate may
        # have passed a general "candidatures" page with no offer.
        if not title and not org:
            continue
        # Rules-only mode (no Laya gate upstream): require a rank word IN THE
        # TITLE — news articles always mention ministries (وزارة/مديرية), so
        # an org-keyword check would let news noise through.
        if strict_rank and not _RANK_RE.search(title or ""):
            continue
        deadline_raw, deadline_iso, deadline_kind = _find_deadline(block, issue_date)
        quals = _find_qualifications(block)
        contacts = _find_contacts(block)
        positions = _find_positions(block)
        wilaya = None
        for candidate in (org, block[:200]):
            wilaya = normalize.match_wilaya(candidate or "")
            if wilaya:
                break

        cls = _classify_block(block, lang, classify)
        values = cls.get("values", {}) or {}
        conf = cls.get("confidence", {}) or {}
        sector = values.get("sector") or "Unknown"
        contract = _contract_override(block) or values.get("contract_type") or "Non sp\u00e9cifi\u00e9"

        offers.append(Offer(
            source_newspaper=source_name,
            job_title=title,
            organization_or_company=org,
            sector=sector,
            contract_type=contract,
            wilaya_location=wilaya,
            required_qualifications=quals,
            positions_count=positions,
            application_deadline_raw=deadline_raw,
            application_deadline=deadline_iso,
            deadline_kind=deadline_kind,
            contact_info=contacts,
            language=lang,
            source_slug=source_slug,
            source_file=source_file,
            page=page,
            snippet=block[:280],
            laya_confidence={
                k: round(float(v), 4) for k, v in conf.items() if isinstance(v, (int, float))
            },
            gate=gate_by,
        ))
    return offers


def dedupe_offers(offers: List[Offer]) -> List[Offer]:
    """Drop offers with identical (org, title, deadline) — keep the first."""
    seen: set[tuple] = set()
    out: List[Offer] = []
    for o in offers:
        key = (
            (o.organization_or_company or "").casefold(),
            (o.job_title or "").casefold(),
            o.application_deadline or "",
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(o)
    return out
