"""i18n strings for the Telegram onboarding wizard (FR / AR / EN)."""
from __future__ import annotations

from typing import Any, Dict

LANG_NAMES = {"fr": "🇫🇷 Français", "ar": "🇩🇿 العربية", "en": "🇬🇧 English"}

STRINGS: Dict[str, Dict[str, str]] = {
    "fr": {
        "pick_language": "👋 Bienvenue sur <b>jobfinderDZ</b> !\n\nChoisissez votre langue :",
        "welcome": "🤖 <b>jobfinderDZ</b> — les offres d'emploi d'Algérie, actualisées chaque jour.\n\n"
                   "Chaque matin je vous envoie :\n"
                   "🆕 les <b>nouvelles</b> offres correspondant à votre profil\n"
                   "🔄 celles encore <b>ouvertes</b> (les expirées sont retirées automatiquement)\n\n"
                   "Configurons vos préférences en 4 étapes — vous pouvez passer chacune avec « Tout » ou « Passer ».",
        "ask_wilaya": "📍 <b>Étape 1/4 — Wilayas</b>\nTouchez pour choisir ({count} sélectionnée(s)) :",
        "ask_sector": "🏢 <b>Étape 2/4 — Secteur</b>\nQuelles offres voulez-vous suivre ?",
        "ask_contract": "📄 <b>Étape 3/4 — Type de contrat</b>",
        "ask_keywords": "🔎 <b>Étape 4/4 — Mots-clés</b>\n"
                        "Touchez les mots qui vous intéressent (ou tapez-les en un message), puis Valider :",
        "confirm_intro": "✅ <b>Récapitulatif de vos préférences</b>\n\n{summary}\n\nEnregistrer ?",
        "saved_msg": "🎉 Préférences enregistrées ! Voici vos offres du jour :",
        "choose_one": "Choisissez au moins une wilaya, ou « Tout ».",
        "saved_toast": "Enregistré ✓",
        "unknown_input": "Tapez /start pour configurer vos préférences (en FR / عربية / EN).",
        "btn_all": "🌍 Tout",
        "btn_done": "✔️ Valider",
        "btn_next": "➡️ Suite",
        "btn_prev": "⬅️ Retour",
        "btn_skip": "⏭️ Passer",
        "btn_restart": "🔄 Recommencer",
        "btn_save": "✅ Enregistrer",
        "btn_private": "🏢 Privé",
        "btn_public": "🏛️ Public",
        "btn_any_sector": "❓ Indifférent",
        "lbl_cities": "Villes", "lbl_sectors": "Secteurs",
        "lbl_contracts": "Contrats", "lbl_keywords": "Mots-clés",
        "lbl_none": "—",
    },
    "ar": {
        "pick_language": "👋 مرحباً بك في <b>jobfinderDZ</b> !\n\nاختر لغتك :",
        "welcome": "🤖 <b>jobfinderDZ</b> — عروض العمل في الجزائر، تُحدَّث كل يوم.\n\n"
                   "كل صباح أرسل لك :\n"
                   "🆕 العروض <b>الجديدة</b> المطابقة لملفك\n"
                   "🔄 العروض <b>ما زالت مفتوحة</b> (تُحذف المنتهية تلقائياً)\n\n"
                   "لنضبط تفضيلاتك في 4 خطوات — يمكنك تجاوز أي خطوة بـ « الكل » أو « تخطي ».",
        "ask_wilaya": "📍 <b>الخطوة 1/4 — الولايات</b>\nاضغط للاختيار ({count} مختارة) :",
        "ask_sector": "🏢 <b>الخطوة 2/4 — القطاع</b>\nأي عروض تريد متابعتها ؟",
        "ask_contract": "📄 <b>الخطوة 3/4 — نوع العقد</b>",
        "ask_keywords": "🔎 <b>الخطوة 4/4 — الكلمات المفتاحية</b>\n"
                        "اضغط على الكلمات التي تهمك (أو اكتبها في رسالة)، ثم تأكيد :",
        "confirm_intro": "✅ <b>ملخص تفضيلاتك</b>\n\n{summary}\n\nهل تريد الحفظ ؟",
        "saved_msg": "🎉 تم حفظ التفضيلات ! إليك عروض اليوم :",
        "choose_one": "اختر ولاية واحدة على الأقل، أو « الكل ».",
        "saved_toast": "تم الحفظ ✓",
        "unknown_input": "أرسل /start لضبط تفضيلاتك (بالعربية / FR / EN).",
        "btn_all": "🌍 الكل",
        "btn_done": "✔️ تأكيد",
        "btn_next": "➡️ التالي",
        "btn_prev": "⬅️ السابق",
        "btn_skip": "⏭️ تخطي",
        "btn_restart": "🔄 إعادة",
        "btn_save": "✅ حفظ",
        "btn_private": "🏢 خاص",
        "btn_public": "🏛️ عمومي",
        "btn_any_sector": "❓ بلا تفضيل",
        "lbl_cities": "الولايات", "lbl_sectors": "القطاعات",
        "lbl_contracts": "العقود", "lbl_keywords": "الكلمات",
        "lbl_none": "—",
    },
    "en": {
        "pick_language": "👋 Welcome to <b>jobfinderDZ</b> !\n\nChoose your language :",
        "welcome": "🤖 <b>jobfinderDZ</b> — Algeria job offers, refreshed daily.\n\n"
                   "Every morning I send you:\n"
                   "🆕 <b>new</b> offers matching your profile\n"
                   "🔄 offers still <b>open</b> (expired ones are removed automatically)\n\n"
                   "Let's set your preferences in 4 steps — you can skip any step with “All” or “Skip”.",
        "ask_wilaya": "📍 <b>Step 1/4 — Wilayas</b>\nTap to choose ({count} selected) :",
        "ask_sector": "🏢 <b>Step 2/4 — Sector</b>\nWhich offers do you want to follow ?",
        "ask_contract": "📄 <b>Step 3/4 — Contract type</b>",
        "ask_keywords": "🔎 <b>Step 4/4 — Keywords</b>\n"
                        "Tap the words that interest you (or type them in one message), then Done :",
        "confirm_intro": "✅ <b>Your preferences</b>\n\n{summary}\n\nSave ?",
        "saved_msg": "🎉 Preferences saved! Here are today's offers :",
        "choose_one": "Pick at least one wilaya, or “All”.",
        "saved_toast": "Saved ✓",
        "unknown_input": "Send /start to set your preferences (FR / عربية / EN).",
        "btn_all": "🌍 All",
        "btn_done": "✔️ Done",
        "btn_next": "➡️ Next",
        "btn_prev": "⬅️ Back",
        "btn_skip": "⏭️ Skip",
        "btn_restart": "🔄 Restart",
        "btn_save": "✅ Save",
        "btn_private": "🏢 Private",
        "btn_public": "🏛️ Public",
        "btn_any_sector": "❓ Any",
        "lbl_cities": "Cities", "lbl_sectors": "Sectors",
        "lbl_contracts": "Contracts", "lbl_keywords": "Keywords",
        "lbl_none": "—",
    },
}


def t(lang: str, key: str, **kw: Any) -> str:
    """Translate `key` in `lang` (fallback FR), with {placeholders} filled."""
    table = STRINGS.get(lang) or STRINGS["fr"]
    text = table.get(key) or STRINGS["fr"].get(key) or key
    if kw:
        try:
            text = text.format(**kw)
        except (KeyError, IndexError):
            pass
    return text
