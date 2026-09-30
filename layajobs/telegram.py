"""Telegram bot: raw Bot API client (requests only), per-chat preferences
stored in the SQLite database, and a long-poll command loop.

Commands:
  /start /help        - what the bot does
  /city Alger Oran    - only offers in these wilayas ("/city" alone clears)
  /sector Private     - Private | Public | Unknown
  /contract CDI CDD   - contract types as stored ("Statutaire", ...)
  /keyword مهندس      - words that must appear in title/description/org
  /any                - clear ALL filters
  /prefs              - show current filters
  /digest             - get the digest now

The bot token is read from data/telegram_token.txt (never committed).
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from . import digest
from .store import Store

API_BASE = "https://api.telegram.org/bot{token}/{method}"
POLL_TIMEOUT = 30          # long-poll seconds
ERROR_BACKOFF = 5          # seconds after a failed request

_PREF_COMMANDS = {
    "/city": "cities",
    "/sector": "sectors",
    "/contract": "contracts",
    "/keyword": "keywords",
}


# ---------------------------------------------------------------------------
# Token + persistence
# ---------------------------------------------------------------------------

def token_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / "telegram_token.txt"


def load_token(data_dir: str | Path) -> Optional[str]:
    # env wins (Docker / CI); file is the local fallback
    env = os.environ.get("TELEGRAM_TOKEN", "").strip()
    if env:
        return env
    p = token_path(data_dir)
    if p.exists():
        tok = p.read_text(encoding="utf-8").strip()
        return tok or None
    return None


def save_token(data_dir: str | Path, token: str) -> Path:
    p = token_path(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(token.strip(), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Raw Bot API
# ---------------------------------------------------------------------------

class TelegramError(RuntimeError):
    pass


class Bot:
    def __init__(self, token: str) -> None:
        self.token = token
        self.offset = 0

    def _call(self, method: str, **params: Any) -> Any:
        try:
            r = requests.post(API_BASE.format(token=self.token, method=method),
                              json=params, timeout=(10, POLL_TIMEOUT + 10))
        except requests.RequestException as exc:
            raise TelegramError(f"{method}: {exc}") from exc
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if not data.get("ok"):
            raise TelegramError(f"{method}: {data.get('description', r.status_code)}")
        return data["result"]

    def me(self) -> Dict[str, Any]:
        return self._call("getMe")

    def send(self, chat_id: int | str, text: str,
             reply_markup: Optional[Dict[str, Any]] = None) -> None:
        # 4096-char hard limit per message; split on our part boundaries.
        for chunk in _chunks(text, 3800):
            params: Dict[str, Any] = {
                "chat_id": chat_id, "text": chunk, "parse_mode": "HTML",
                "disable_web_page_preview": True}
            if reply_markup:
                params["reply_markup"] = reply_markup
            self._call("sendMessage", **params)

    def edit_markup(self, chat_id: int | str, message_id: int,
                    reply_markup: Dict[str, Any]) -> None:
        self._call("editMessageReplyMarkup", chat_id=chat_id,
                   message_id=message_id, reply_markup=reply_markup)

    def answer_callback(self, callback_query_id: str,
                        text: Optional[str] = None) -> None:
        params: Dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            params["text"] = text
        self._call("answerCallbackQuery", **params)

    def updates(self) -> List[Dict[str, Any]]:
        result = self._call("getUpdates", offset=self.offset, timeout=POLL_TIMEOUT,
                            allowed_updates=["message", "callback_query"])
        for u in result:
            self.offset = max(self.offset, u["update_id"] + 1)
        return result


def _chunks(text: str, size: int) -> List[str]:
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    parts: List[str] = []
    while text:
        cut = text.rfind("\n\n", 0, size)
        if cut < size // 2:
            cut = text.rfind("\n", 0, size)
        if cut < size // 2:
            cut = size
        parts.append(text[:cut].strip())
        text = text[cut:].strip()
    return [p for p in parts if p]


# ---------------------------------------------------------------------------
# Preferences storage (telegram_prefs table in the same DB)
# ---------------------------------------------------------------------------

_PREF_SCHEMA = """
CREATE TABLE IF NOT EXISTS telegram_prefs (
    chat_id TEXT PRIMARY KEY,
    prefs   TEXT NOT NULL DEFAULT '{}',
    registered_at TEXT NOT NULL
);
"""


class PrefsStore:
    def __init__(self, db_path: str | Path) -> None:
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_PREF_SCHEMA)
        self.conn.commit()

    def get(self, chat_id: int | str) -> Dict[str, List[str]]:
        row = self.conn.execute(
            "SELECT prefs FROM telegram_prefs WHERE chat_id = ?", (str(chat_id),)
        ).fetchone()
        return digest.normalize_prefs(json.loads(row["prefs"]) if row else {})

    def set(self, chat_id: int | str, prefs: Dict[str, List[str]]) -> None:
        self.conn.execute(
            "INSERT INTO telegram_prefs (chat_id, prefs, registered_at) VALUES (?,?,?) "
            "ON CONFLICT(chat_id) DO UPDATE SET prefs = excluded.prefs",
            (str(chat_id), json.dumps(prefs, ensure_ascii=False),
             time.strftime("%Y-%m-%dT%H:%M:%S")))
        self.conn.commit()

    def all_chats(self) -> List[str]:
        rows = self.conn.execute("SELECT chat_id FROM telegram_prefs").fetchall()
        return [r["chat_id"] for r in rows]


# ---------------------------------------------------------------------------
# Command handling
# ---------------------------------------------------------------------------

HELP_TEXT = (
    "🤖 <b>jobfinderDZ</b> — offres d'emploi Algérie, actualisées chaque jour.\n\n"
    "Filtres (s'appliquent à votre récapitulatif quotidien) :\n"
    "/city Alger Oran — wilayas voulues (/city seul efface)\n"
    "/sector Private — Private | Public | Unknown\n"
    "/contract CDI CDD — types de contrat\n"
    "/keyword مهندس comptable — mots-clés (FR/AR)\n"
    "/any — effacer tous les filtres\n"
    "/prefs — voir vos filtres\n"
    "/digest — recevoir les offres maintenant\n\n"
    "Le récapitulatif distingue 🆕 nouveautés et 🔄 offres toujours ouvertes; "
    "les offres expirées sont retirées automatiquement."
)


def prefs_summary(prefs: Dict[str, List[str]]) -> str:
    chips = []
    labels = {"cities": "villes", "sectors": "secteurs", "contracts": "contrats",
              "keywords": "mots-clés"}
    for key, label in labels.items():
        chips.append(f"{label}: {', '.join(prefs[key]) if prefs[key] else '—'}")
    return "⚙️ Vos filtres — " + " · ".join(chips)


def handle_message(bot: Bot, prefs_store: PrefsStore, store: Store,
                   message: Dict[str, Any],
                   wizard: Optional[Any] = None) -> None:
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()
    if not chat_id or not text:
        return
    cmd, _, args = text.partition(" ")

    try:
        # Conversational onboarding: /start (or any first greeting) launches
        # the language-choice wizard; free text is consumed by an active one.
        if wizard is not None:
            if cmd in ("/start", "start"):
                wizard.start(bot, chat_id)
                return
            if wizard.handle_text(bot, chat_id, text):
                return

        if cmd in ("/help", "help"):
            bot.send(chat_id, HELP_TEXT)
            return
        if cmd == "/wizard":
            if wizard is not None:
                wizard.start(bot, chat_id, restart=True)
                return
        if cmd == "/any":
            prefs_store.set(chat_id, digest.default_prefs())
            bot.send(chat_id, "✅ Tous les filtres effacés — vous recevrez tout.")
            return
        if cmd == "/prefs":
            bot.send(chat_id, prefs_summary(prefs_store.get(chat_id)))
            return
        if cmd in _PREF_COMMANDS:
            key = _PREF_COMMANDS[cmd]
            update = digest.parse_pref_command(key, args)
            prefs = prefs_store.get(chat_id)
            prefs.update(update)
            prefs_store.set(chat_id, prefs)
            bot.send(chat_id, "✅ " + prefs_summary(prefs))
            return
        if cmd == "/digest":
            rows = store.query(limit=5000)
            messages = digest.build_digest(rows, prefs_store.get(chat_id))
            for m in messages:
                bot.send(chat_id, m)
            return
        # Unknown free text: launch onboarding (the UI-like flow).
        if wizard is not None:
            wizard.start(bot, chat_id, restart=True)
        else:
            bot.send(chat_id, HELP_TEXT)
    except TelegramError as exc:
        bot.send(chat_id, f"⚠️ Erreur Telegram: {_esc_ok(exc)}")
    except Exception as exc:  # never crash the poll loop
        try:
            bot.send(chat_id, f"⚠️ Erreur interne: {str(exc)[:120]}")
        except Exception:
            pass


def _esc_ok(exc: Exception) -> str:
    return str(exc).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")[:160]


def poll_forever(bot: Bot, prefs_store: PrefsStore, store: Store,
                 wizard: Optional[Any] = None) -> None:
    """Long-poll loop; Ctrl+C to stop. Routes messages and button taps."""
    me = bot.me()
    print(f"polling as @{me.get('username')} — Ctrl+C to stop")
    while True:
        try:
            for update in bot.updates():
                message = update.get("message") or {}
                callback = update.get("callback_query")
                if message:
                    handle_message(bot, prefs_store, store, message, wizard=wizard)
                elif callback and wizard is not None:
                    cb_chat = ((callback.get("message") or {}).get("chat") or {})
                    chat_id = cb_chat.get("id")
                    data = callback.get("data") or ""
                    msg_id = ((callback.get("message") or {}).get("message_id"))
                    if chat_id and data:
                        try:
                            wizard.handle_callback(bot, chat_id, data, msg_id)
                        except Exception as exc:
                            print(f"callback error: {exc}")
                        try:
                            bot.answer_callback(callback["id"])
                        except Exception:
                            pass
        except TelegramError as exc:
            print(f"poll error: {exc}; retrying in {ERROR_BACKOFF}s")
            time.sleep(ERROR_BACKOFF)
        except KeyboardInterrupt:
            print("stopped")
            return


# ---------------------------------------------------------------------------
# Embedded daily refresh thread (used by the Docker deployment: one process
# = listener + 06:00 push). Runs `layajobs.cli.cmd_daily` logic in-process.
# ---------------------------------------------------------------------------

def _daily_once(prefs_store: "PrefsStore", store: "Store",
                pages: int = 20) -> int:
    """One harvest+digest pass. Returns stored count. Defined lazily to avoid
    a cli<->telegram import cycle."""
    from . import boards, digest as digest_mod, ministries  # local import
    counters = {"stored": 0, "extracted": 0}
    for offer in boards.harvest_emploitic(max_pages=pages):
        _, inserted = store.upsert_offer(offer)
        counters["extracted"] += 1
        counters["stored"] += 1 if inserted else 0
    for _slug, offers in ministries.harvest_all().items():
        for o in offers:
            _, inserted = store.upsert_offer(o.to_json())
            counters["extracted"] += 1
            counters["stored"] += 1 if inserted else 0
    rows = store.query(limit=5000)
    for chat_id in prefs_store.all_chats():
        try:
            for m in digest_mod.build_digest(rows, prefs_store.get(chat_id)):
                bot_send_digest(chat_id, m)
        except Exception as exc:
            print(f"[daily] chat {chat_id} failed: {exc}")
    print(f"[daily] done — {counters['stored']} new offers stored")
    return counters["stored"]


_bot_instance: Optional["Bot"] = None


def bot_send_digest(chat_id: int | str, text: str) -> None:
    """Send via the module's bot if set (thread-safe enough for our use)."""
    if _bot_instance is None:
        raise TelegramError("no bot instance")
    _bot_instance.send(chat_id, text)


def run_with_daily(pages: int = 20) -> None:
    """Bot polling + daily-refresh thread (Docker CMD entry point)."""
    import threading
    from datetime import datetime, timedelta
    global _bot_instance
    token = load_token(os.environ.get("LAYAJOBS_DATA", "data"))
    bot = Bot(token)
    _bot_instance = bot
    prefs_store = PrefsStore(os.environ.get("LAYAJOBS_DATA", "data") + "/jobs.db")
    store = Store(os.environ.get("LAYAJOBS_DATA", "data") + "/jobs.db")
    wizard = None
    try:
        from .wizard import Wizard
        wizard = Wizard(prefs_store, store)
    except Exception:
        pass

    def daily_loop() -> None:
        # run at 06:00 Algeria (UTC+1) — i.e. 05:00 UTC — then every 24h
        target_hour_utc = 5
        while True:
            now = datetime.utcnow()
            run_at = now.replace(hour=target_hour_utc, minute=0, second=0,
                                 microsecond=0)
            if run_at <= now:
                run_at += timedelta(days=1)
            wait_s = (run_at - now).total_seconds()
            print(f"[daily] next refresh at {run_at.isoformat()}Z "
                  f"({wait_s / 3600:.1f}h) — sleeping")
            time.sleep(max(60, wait_s))
            try:
                _daily_once(prefs_store, store, pages=pages)
            except Exception as exc:
                print(f"[daily] failed: {exc}")

    threading.Thread(target=daily_loop, daemon=True).start()
    poll_forever(bot, prefs_store, store, wizard=wizard)
