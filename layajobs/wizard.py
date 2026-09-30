"""Conversational onboarding wizard for the Telegram bot.

Any first message from a user triggers: language choice (FR/AR/EN) →
welcome explanation → 4 preference steps with tappable inline keyboards
(wilayas multi-select, sector, contract, keywords free text) → confirmation
→ save + immediate digest.

Wizard state lives in-process (single bot process), keyed by chat id.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import digest, i18n, normalize
from .telegram import Bot, PrefsStore, Store, _chunks

# ---------------------------------------------------------------------------
# Keyboards
# ---------------------------------------------------------------------------

def _kb(rows: List[List[Dict[str, Any]]]) -> Dict[str, Any]:
    return {"inline_keyboard": [[b for b in row] for row in rows]}


def _btn(label: str, data: str) -> Dict[str, Any]:
    return {"text": label, "callback_data": data}


_LANG_KB = _kb([[_btn(i18n.LANG_NAMES[l], f"lang:{l}") for l in ("fr", "ar", "en")]])

_CONTRACT_CHOICES = ["CDI", "CDD", "Statutaire", "Non spécifié"]
_SECTOR_CHOICES = ["Private", "Public", "Unknown"]

# Bilingual quick-pick keywords (FR + AR), toggle buttons in step 4.
_KEYWORD_CHOICES = [
    "مهندس", "ingénieur", "technicien", "تقني",
    "comptable", "محاسب", "secrétaire", "سكرتير",
    "سائق", "chauffeur", "commercial", "vendeur",
    "informatique", "infirmier", "ممرض", "finance",
]


def _wilaya_kb(selected: set[int]) -> Dict[str, Any]:
    rows: List[List[Dict[str, Any]]] = []
    row: List[Dict[str, Any]] = []
    for code, (fr, _ar) in normalize.WILAYAS.items():
        label = ("✅ " if code in selected else "") + fr
        row.append(_btn(label, f"wiz:city:{code}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([_btn(i18n.t("fr", "btn_all"), "wiz:city:all"),
                 _btn(i18n.t("fr", "btn_done"), "wiz:next")])
    return rows and _kb(rows) or _kb([[]])


def _toggle_kb(choices: List[str], selected: List[str], field: str,
               lang: str, *, any_label: Optional[str] = None) -> Dict[str, Any]:
    sel = [s.casefold() for s in selected]
    rows: List[List[Dict[str, Any]]] = []
    row: List[Dict[str, Any]] = []
    for c in choices:
        on = c.casefold() in sel
        rows_label = ("✅ " if on else "") + c
        row.append(_btn(rows_label, f"wiz:{field}:{c}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    if any_label:
        rows.append([_btn(any_label, f"wiz:{field}:__all__")])
    rows.append([_btn(i18n.t(lang, "btn_done"), "wiz:next")])
    return _kb(rows)


def _confirm_kb(lang: str) -> Dict[str, Any]:
    return _kb([[_btn(i18n.t(lang, "btn_save"), "wiz:save"),
                 _btn(i18n.t(lang, "btn_restart"), "wiz:restart")]])


# ---------------------------------------------------------------------------
# Wizard state machine
# ---------------------------------------------------------------------------

class Wizard:
    """Per-chat onboarding flow. State is in-memory (single bot process)."""

    def __init__(self, prefs_store: PrefsStore, store: Store) -> None:
        self.prefs_store = prefs_store
        self.store = store
        self.sessions: Dict[int, Dict[str, Any]] = {}

    # -- helpers ------------------------------------------------------------

    def _state(self, chat_id: int) -> Dict[str, Any]:
        if chat_id not in self.sessions:
            prefs = self.prefs_store.get(chat_id)
            self.sessions[chat_id] = {"lang": "fr", "step": "lang", "data": prefs}
        return self.sessions[chat_id]

    def _summary(self, lang: str, data: Dict[str, List[str]]) -> str:
        labels = {"cities": i18n.t(lang, "lbl_cities"),
                  "sectors": i18n.t(lang, "lbl_sectors"),
                  "contracts": i18n.t(lang, "lbl_contracts"),
                  "keywords": i18n.t(lang, "lbl_keywords")}
        lines = []
        for key, label in labels.items():
            values = ", ".join(data.get(key) or []) or i18n.t(lang, "lbl_none")
            lines.append(f"• <b>{label}:</b> {values}")
        return "\n".join(lines)

    def _send_step(self, bot: Bot, chat_id: int) -> None:
        st = self._state(chat_id)
        lang, step, data = st["lang"], st["step"], st["data"]
        if step == "wilaya":
            selected = set()
            for value in data["cities"]:
                for code, (fr, ar) in normalize.WILAYAS.items():
                    if value in (fr.casefold(), ar.casefold()):
                        selected.add(code)
            bot.send(chat_id, i18n.t(lang, "ask_wilaya", count=len(selected)),
                     reply_markup=_wilaya_kb(selected))
        elif step == "sector":
            bot.send(chat_id, i18n.t(lang, "ask_sector"),
                     reply_markup=_toggle_kb(
                         _SECTOR_CHOICES, data["sectors"], "sector", lang,
                         any_label=i18n.t(lang, "btn_any_sector")))
        elif step == "contract":
            bot.send(chat_id, i18n.t(lang, "ask_contract"),
                     reply_markup=_toggle_kb(
                         _CONTRACT_CHOICES, data["contracts"], "contract", lang))
        elif step == "keywords":
            bot.send(chat_id, i18n.t(lang, "ask_keywords"),
                     reply_markup=_toggle_kb(
                         _KEYWORD_CHOICES, data["keywords"], "keyword", lang))
        elif step == "confirm":
            bot.send(chat_id, i18n.t(lang, "confirm_intro",
                                     summary=self._summary(lang, data)),
                     reply_markup=_confirm_kb(lang))

    _ORDER = ["wilaya", "sector", "contract", "keywords", "confirm"]

    def _goto(self, bot: Bot, chat_id: int, step: str) -> None:
        st = self._state(chat_id)
        st["step"] = step
        self._send_step(bot, chat_id)

    # -- entry points -------------------------------------------------------

    def start(self, bot: Bot, chat_id: int, *, restart: bool = False) -> None:
        if restart:
            self.sessions.pop(chat_id, None)
        st = self._state(chat_id)
        if st["step"] == "lang" or restart:
            st["step"] = "lang"
            bot.send(chat_id, i18n.t("fr", "pick_language"), reply_markup=_LANG_KB)
        else:
            self._send_step(bot, chat_id)

    # -- callbacks ----------------------------------------------------------

    def handle_callback(self, bot: Bot, chat_id: int, data: str,
                        message_id: Optional[int] = None) -> None:
        st = self._state(chat_id)
        lang = st["lang"]
        kind, _, value = data.partition(":")

        if kind == "lang":
            st["lang"] = value if value in i18n.STRINGS else "fr"
            st["step"] = "wilaya"
            bot.send(chat_id, i18n.t(st["lang"], "welcome"))
            self._send_step(bot, chat_id)
            return

        if kind != "wiz":
            return
        field, _, raw = value.partition(":")
        d = st["data"]

        if field == "city":
            if raw == "all":
                d["cities"] = []
                self._goto(bot, chat_id, "sector")
                return
            code = int(raw)
            name = normalize.WILAYAS[code][0]
            fold = name.casefold()
            if fold in d["cities"]:
                d["cities"].remove(fold)
            else:
                d["cities"].append(fold)
            # refresh the same message (no spam)
            if message_id:
                selected = {int(normalize.WILAYAS[c][0].casefold() == v or c)
                            for c, v in []}  # placeholder, rebuilt below
                selected = set()
                for v in d["cities"]:
                    for code2, (fr, _ar) in normalize.WILAYAS.items():
                        if v == fr.casefold():
                            selected.add(code2)
                try:
                    bot.edit_markup(chat_id, message_id,
                                    _wilaya_kb(selected))
                except Exception:
                    self._send_step(bot, chat_id)
            else:
                self._send_step(bot, chat_id)
            return

        if field in ("sector", "contract", "keyword"):
            key = {"sector": "sectors", "contract": "contracts",
                   "keyword": "keywords"}[field]
            if raw == "__all__":
                d[key] = []
            elif raw.casefold() in [c.casefold() for c in d[key]]:
                d[key] = [c for c in d[key] if c.casefold() != raw.casefold()]
            elif len(d[key]) >= 10:
                pass  # keyword cap
            else:
                d[key].append(raw)
            any_label = i18n.t(lang, "btn_any_sector") if field == "sector" else None
            choices = {"sector": _SECTOR_CHOICES, "contract": _CONTRACT_CHOICES,
                       "keyword": _KEYWORD_CHOICES}[field]
            try:
                if message_id:
                    bot.edit_markup(chat_id, message_id,
                                    _toggle_kb(choices, d[key], field, lang,
                                               any_label=any_label))
                else:
                    self._send_step(bot, chat_id)
            except Exception:
                self._send_step(bot, chat_id)
            return

        if field == "next":
            idx = self._ORDER.index(st["step"])
            st["step"] = self._ORDER[min(idx + 1, len(self._ORDER) - 1)]
            self._send_step(bot, chat_id)
            return

        if field == "restart":
            st["data"] = digest.default_prefs()
            st["step"] = "lang"
            bot.send(chat_id, i18n.t(lang, "pick_language"), reply_markup=_LANG_KB)
            return

        if field == "save":
            self.prefs_store.set(chat_id, st["data"])
            self.sessions.pop(chat_id, None)
            bot.send(chat_id, i18n.t(lang, "saved_msg"))
            rows = self.store.query(limit=5000)
            for m in digest.build_digest(rows, self.prefs_store.get(chat_id)):
                bot.send(chat_id, m)
            return

    # -- free text (keywords step, or unknown input) ------------------------

    def handle_text(self, bot: Bot, chat_id: int, text: str) -> bool:
        """Consume text while a wizard session is active. Returns True if used."""
        if chat_id not in self.sessions:
            return False
        st = self.sessions[chat_id]
        if st["step"] == "keywords":
            words = [w.strip().casefold() for w in text.split() if w.strip()]
            st["data"]["keywords"] = words[:10]
            self._goto(bot, chat_id, "confirm")
            return True
        if st["step"] == "lang":
            return True   # waiting for a language button; ignore text
        return False
