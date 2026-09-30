"""laya-jobs CLI: verify / fetch / ingest / run / export / stats.

    python -m layajobs verify            # probe every source
    python -m layajobs fetch             # discover + download e-paper PDFs
    python -m layajobs ingest            # process PDFs already in data/raw/
    python -m layajobs run               # fetch + ingest in one pass
    python -m layajobs run --dry-run     # fetch + gate only, no DB writes
    python -m layajobs export            # Excel + JSONL from the database
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

from . import export as export_mod
from . import boards, digest as digest_mod, fetchers, gating, laya_engine, ministries
from . import normalize, store, telegram as telegram_mod, textlayer, wizard as wizard_mod
from .extractor import dedupe_offers, extract_offers

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_SOURCES = PROJECT_ROOT / "config" / "sources.toml"
# data dir is overridable (Docker volume): LAYAJOBS_DATA=/data
code_data = PROJECT_ROOT / "data"
DATA_DIR = Path(os.environ.get("LAYAJOBS_DATA", code_data))
RAW_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "jobs.db"


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

def cmd_verify(args: argparse.Namespace) -> int:
    sources = fetchers.load_sources(CONFIG_SOURCES)
    if args.source:
        sources = [s for s in sources if s.slug in args.source]
        if not sources:
            print("no matching source slugs", file=sys.stderr)
            return 2
    status = fetchers.load_status(DATA_DIR)
    for s in sources:
        print(f"[verify] {s.slug:<22} ", end="", flush=True)
        rec = fetchers.verify_source(s)
        status[s.slug] = rec
        n_pdfs = len(rec.get("epaper_pdf_candidates") or [])
        print(f"{rec['status']:<11} {n_pdfs} pdf candidates")
        for err_key in ("base_error", "epaper_error"):
            if rec.get(err_key):
                print(f"           {err_key}: {rec[err_key]}")
    fetchers.save_status(DATA_DIR, status)
    print(f"\nstatus written to {DATA_DIR / 'source_status.json'}")
    return 0


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------

def cmd_fetch(args: argparse.Namespace) -> int:
    sources = fetchers.load_sources(CONFIG_SOURCES)
    if args.source:
        sources = [s for s in sources if s.slug in args.source]
    status = fetchers.load_status(DATA_DIR)
    total = 0
    for s in sources:
        print(f"[fetch] {s.slug}")
        try:
            links = fetchers.discover_epaper_pdfs(s)
        except Exception as exc:
            print(f"        discovery failed: {exc}")
            status[s.slug] = {**status.get(s.slug, {}), "status": "unverified",
                              "epaper_error": str(exc)[:200]}
            continue
        if not links:
            print("        no PDF candidates found")
            status[s.slug] = {**status.get(s.slug, {}), "status": "reachable"}
            continue
        rec = status.get(s.slug, {})
        rec.update(status="verified", epaper_pdf_candidates=[u for u, _ in links])
        status[s.slug] = rec
        downloaded = 0
        for url, _text in links:
            path = fetchers.download_pdf(url, RAW_DIR, slug=s.slug)
            if path:
                downloaded += 1
                print(f"        saved {path.name}")
            if downloaded >= args.max_pdfs:
                break
        total += downloaded
    fetchers.save_status(DATA_DIR, status)
    print(f"\n{total} PDF(s) under {RAW_DIR}")
    return 0


# ---------------------------------------------------------------------------
# ingest / run
# ---------------------------------------------------------------------------

def _ingest_pdf(pdf_path: Path, source: Any, st: store.Store, run_id: int,
                counters: Dict[str, int], *, dry_run: bool) -> None:
    chunks = textlayer.pdf_to_chunks(pdf_path)
    counters["chunks_total"] += len(chunks)
    for chunk in chunks:
        if chunk.needs_ocr:
            counters["pdfs_needs_ocr"] += 0  # per-PDF flag handled below
        g = gating.gate_chunk(chunk.text, lang_hint=source.language)
        if not g.passed:
            continue
        counters["chunks_gated"] += 1
        offers = extract_offers(
            chunk.text,
            source_name=source.name,
            source_slug=source.slug,
            source_file=pdf_path.name,
            page=chunk.page,
            lang_hint=source.language,
            gate_by=g.gated_by,
        )
        offers = dedupe_offers(offers)
        if dry_run:
            for o in offers:
                print(f"  [dry-run] p{chunk.page} {o.job_title!r} @ {o.organization_or_company!r}")
            continue
        for o in offers:
            _, inserted = st.upsert_offer(o.to_json())
            if inserted:
                counters["offers_stored"] += 1
            counters["offers_extracted"] += 1
    ocr_pages = textlayer.needs_ocr_pages(pdf_path)
    if ocr_pages:
        counters["pdfs_needs_ocr"] += 1


def _source_for_slug(slug: str, sources: List[Any]) -> Any:
    for s in sources:
        if s.slug == slug:
            return s
    return None


def cmd_ingest(args: argparse.Namespace) -> int:
    sources = fetchers.load_sources(CONFIG_SOURCES)
    st = store.Store(DB_PATH)
    run_id = st.start_run("dry-run" if args.dry_run else "ingest")
    counters: Dict[str, int] = {
        "chunks_total": 0, "chunks_gated": 0, "offers_extracted": 0,
        "offers_stored": 0, "pdfs_needs_ocr": 0, "errors": 0,
    }
    pdfs = sorted(RAW_DIR.glob("*/*.pdf")) if RAW_DIR.exists() else []
    if args.source:
        pdfs = [p for p in pdfs if p.parent.name in args.source]
    if not pdfs:
        print(f"no PDFs under {RAW_DIR} — run `laya-jobs fetch` first or drop files there")
        st.finish_run(run_id, **counters)
        return 0
    if not args.dry_run and not laya_engine.available():
        err = laya_engine.load_error()
        print(f"Laya checkpoint unavailable: {err}", file=sys.stderr)
        return 1
    try:
        for pdf in pdfs:
            source = _source_for_slug(pdf.parent.name, sources)
            if source is None:
                print(f"[ingest] {pdf.parent.name}: unknown source, skipping")
                continue
            print(f"[ingest] {source.slug} / {pdf.name}")
            try:
                _ingest_pdf(pdf, source, st, run_id, counters, dry_run=args.dry_run)
            except Exception as exc:
                counters["errors"] += 1
                print(f"        ERROR: {exc}")
    finally:
        st.finish_run(run_id, **counters)
    print(f"\nchunks={counters['chunks_total']} gated={counters['chunks_gated']} "
          f"offers={counters['offers_extracted']} stored={counters['offers_stored']} "
          f"needs_ocr_pdfs={counters['pdfs_needs_ocr']} errors={counters['errors']}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    rc = cmd_fetch(args)
    if rc != 0:
        return rc
    return cmd_ingest(args)


# ---------------------------------------------------------------------------
# boards (online job boards: Emploitic now, more adapters in boards.py)
# ---------------------------------------------------------------------------

def cmd_boards(args: argparse.Namespace) -> int:
    """Ingest structured offers from online boards (currently Emploitic).

    --harvest: mass mode, 20 structured offers per listing request
    (default). --max-offers: detail-page mode with full deadline data.
    """
    st = store.Store(DB_PATH)
    run_id = st.start_run("boards")
    counters: Dict[str, int] = {"offers_extracted": 0, "offers_stored": 0,
                                "errors": 0}
    if args.harvest:
        offers = boards.harvest_emploitic(max_pages=args.max_pages, verbose=True)
    else:
        offers = boards.fetch_emploitic(max_offers=args.max_offers,
                                        max_pages=args.max_pages)
    for offer in offers:
        # Laya's sector guess is advisory metadata only; the deterministic
        # board rule (private employers) sets the sector. Skipped in harvest
        # mode: hundreds of forward passes for a low-value advisory field.
        desc = offer.pop("full_text", None) or offer.get("snippet") or ""
        if desc and not args.harvest and laya_engine.available():
            try:
                cls = laya_engine.classify_offer(desc, lang="fr")
                values = cls.get("values") or {}
                conf = cls.get("confidence") or {}
                offer["laya_confidence"] = {
                    "sector_guess": values.get("sector"),
                    "sector_conf": round(float(conf.get("sector", 0.0)), 4)}
            except Exception:
                pass
        _, inserted = st.upsert_offer(offer)
        counters["offers_extracted"] += 1
        if inserted:
            counters["offers_stored"] += 1
        title = offer.get("job_title")
        org = offer.get("organization_or_company")
        print(f"  [{'new' if inserted else 'dup'}] {title} @ {org}")
    st.finish_run(**counters, run_id=run_id)
    print(f"\n{counters['offers_stored']} new / {counters['offers_extracted']} processed "
          f"from Emploitic")
    return 0


# ---------------------------------------------------------------------------
# ministries (WordPress REST adapters: Education, Santé, Intérieur, Justice)
# ---------------------------------------------------------------------------

def cmd_ministries(args: argparse.Namespace) -> int:
    """Ingest concours announcements from ministry WP REST APIs (rules only)."""
    st = store.Store(DB_PATH)
    run_id = st.start_run("ministries")
    counters: Dict[str, int] = {"offers_extracted": 0, "offers_stored": 0,
                                "errors": 0}
    result = ministries.harvest_all(args.source, verbose=True)
    for slug, offers in result.items():
        for o in offers:
            _, inserted = st.upsert_offer(o.to_json())
            counters["offers_extracted"] += 1
            if inserted:
                counters["offers_stored"] += 1
            title = o.job_title or o.organization_or_company or "?"
            print(f"  [{'new' if inserted else 'dup'}] [{slug}] {title[:70]}")
    st.finish_run(**counters, run_id=run_id)
    print(f"\n{counters['offers_stored']} new / {counters['offers_extracted']} processed "
          f"from ministries")
    return 0


# ---------------------------------------------------------------------------
# Telegram pipeline: token / digest / daily / bot
# ---------------------------------------------------------------------------

def _tg_ready() -> tuple[Optional[str], Store]:
    token = telegram_mod.load_token(DATA_DIR)
    if not token:
        print("no bot token — save it first:\n"
              f"  python -m layajobs token --set <TOKEN>   (stored in {telegram_mod.token_path(DATA_DIR)})")
        return None, store.Store(DB_PATH)
    return token, store.Store(DB_PATH)


def cmd_token(args: argparse.Namespace) -> int:
    if args.set:
        path = telegram_mod.save_token(DATA_DIR, args.set)
        bot = telegram_mod.Bot(args.set)
        try:
            me = bot.me()
            print(f"token saved to {path} — bot @{me.get('username')} is live")
        except telegram_mod.TelegramError as exc:
            print(f"token saved to {path} — WARNING, validation failed: {exc}")
        return 0
    tok = telegram_mod.load_token(DATA_DIR)
    print("token present" if tok else "no token saved")
    return 0 if tok else 1


def cmd_digest(args: argparse.Namespace) -> int:
    token, st = _tg_ready()
    if not token:
        return 1
    if not args.chat:
        print("--chat <TELEGRAM_CHAT_ID> required (message the bot once and read the id, "
              "or use `bot` mode which registers chats automatically)")
        return 2
    bot = telegram_mod.Bot(token)
    prefs_store = telegram_mod.PrefsStore(DB_PATH)
    prefs_store.set(args.chat, prefs_store.get(args.chat))  # register the chat
    rows = st.query(limit=5000)
    messages = digest_mod.build_digest(rows, prefs_store.get(args.chat))
    if args.dry:
        for m in messages:
            print(m + "\n" + "-" * 60)
        print(f"(dry-run: {len(messages)} message(s) NOT sent)")
        return 0
    for m in messages:
        bot.send(args.chat, m)
    print(f"{len(messages)} message(s) sent to chat {args.chat}")
    return 0


def cmd_daily(args: argparse.Namespace) -> int:
    """Full daily refresh: boards + ministries (+ newspapers with --with-newspapers),
    then a personalized digest to every registered Telegram chat."""
    st = store.Store(DB_PATH)
    run_id = st.start_run("daily")
    counters: Dict[str, int] = {"offers_stored": 0, "offers_extracted": 0, "errors": 0}

    print("[daily] refreshing Emploitic…")
    for offer in boards.harvest_emploitic(max_pages=args.pages):
        _, inserted = st.upsert_offer(offer)
        counters["offers_extracted"] += 1
        counters["offers_stored"] += 1 if inserted else 0
    print(f"        {counters['offers_extracted']} offers processed")

    print("[daily] refreshing ministries…")
    for _slug, offers in ministries.harvest_all(verbose=True).items():
        for o in offers:
            _, inserted = st.upsert_offer(o.to_json())
            counters["offers_extracted"] += 1
            counters["offers_stored"] += 1 if inserted else 0

    if args.with_newspapers:
        print("[daily] newspapers: fetch + ingest…")
        ns = argparse.Namespace(source=None, max_pdfs=1)
        cmd_fetch(ns)
        cmd_ingest(argparse.Namespace(source=None, dry_run=False))

    token = telegram_mod.load_token(DATA_DIR)
    if not token:
        print("no Telegram token — refresh done, digests skipped")
        st.finish_run(**counters, run_id=run_id)
        return 0
    prefs_store = telegram_mod.PrefsStore(DB_PATH)
    # Cloud bootstrap: on a fresh CI checkout the DB may have no registered
    # chats — register --chat args / TELEGRAM_CHAT_ID so the digest lands.
    bootstraps = list(args.chat or [])
    if os.environ.get("TELEGRAM_CHAT_ID"):
        bootstraps.append(os.environ["TELEGRAM_CHAT_ID"])
    for chat_id in bootstraps:
        if str(chat_id) not in prefs_store.all_chats():
            prefs_store.set(chat_id, prefs_store.get(chat_id))
            print(f"[daily] registered chat {chat_id}")
    chats = prefs_store.all_chats()
    if not chats:
        print("no registered chats — refresh done, digests skipped "
              "(message the bot once, or run `digest --chat <id>`)")
        st.finish_run(**counters, run_id=run_id)
        return 0
    rows = st.query(limit=5000)
    bot = telegram_mod.Bot(token)
    for chat_id in chats:
        try:
            messages = digest_mod.build_digest(rows, prefs_store.get(chat_id))
            for m in messages:
                bot.send(chat_id, m)
            print(f"[daily] digest sent to chat {chat_id} ({len(messages)} msg)")
        except Exception as exc:
            counters["errors"] += 1
            print(f"[daily] chat {chat_id} failed: {str(exc)[:100]}")
    st.finish_run(**counters, run_id=run_id)
    print(f"[daily] done — {counters['offers_stored']} new offers stored")
    return 0


def cmd_bot(args: argparse.Namespace) -> int:
    token, st = _tg_ready()
    if not token:
        return 1
    bot = telegram_mod.Bot(token)
    prefs_store = telegram_mod.PrefsStore(DB_PATH)
    wiz = wizard_mod.Wizard(prefs_store, st)
    if args.with_daily:
        # Docker/VPS mode: one process = listener + embedded 06:00 refresh
        telegram_mod.run_with_daily(pages=args.pages)
        return 0
    telegram_mod.poll_forever(bot, prefs_store, st, wizard=wiz)
    return 0


# ---------------------------------------------------------------------------
# export / stats
# ---------------------------------------------------------------------------

def cmd_export(args: argparse.Namespace) -> int:
    st = store.Store(DB_PATH)
    rows = st.query(source=args.source, sector=args.sector, limit=args.limit)
    if not rows:
        print("no offers stored yet")
        return 0
    stamp = _dt.date.today().isoformat()
    xlsx = export_mod.export_excel(rows, DATA_DIR / "reports" / f"offers-{stamp}.xlsx")
    js = export_mod.export_jsonl(rows, DATA_DIR / "reports" / f"offers-{stamp}.jsonl")
    print(f"{len(rows)} offers -> {xlsx}")
    print(f"           -> {js}")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    st = store.Store(DB_PATH)
    s = st.stats()
    print(f"total offers: {s['total']}")
    for label, key in (("by source", "by_source"), ("by sector", "by_sector"),
                       ("by language", "by_language")):
        print(f"\n{label}:")
        for row in s[key]:
            print(f"  {row.get('src') or row.get('sector') or row.get('language')}: {row['c']}")
    return 0


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="laya-jobs",
                                description="Algerian job-notice scraper (Laya-gated)")
    sub = p.add_subparsers(dest="command", required=True)

    def add_sources_arg(sp):
        sp.add_argument("--source", nargs="*", help="restrict to source slug(s)")

    sp = sub.add_parser("verify", help="probe every source and record status")
    add_sources_arg(sp)

    sp = sub.add_parser("fetch", help="discover + download e-paper PDFs")
    add_sources_arg(sp)
    sp.add_argument("--max-pdfs", type=int, default=2,
                    help="max PDFs per source per run (default 2)")

    sp = sub.add_parser("ingest", help="process PDFs already under data/raw/")
    add_sources_arg(sp)
    sp.add_argument("--dry-run", action="store_true",
                    help="gate + extract, print offers, do not write DB")

    sp = sub.add_parser("run", help="fetch then ingest")
    add_sources_arg(sp)
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--max-pdfs", type=int, default=2)

    sp = sub.add_parser("boards", help="ingest structured offers from online boards (Emploitic)")
    sp.add_argument("--harvest", action="store_true",
                    help="mass mode: 20 offers per listing request (fast)")
    sp.add_argument("--max-offers", type=int, default=12,
                    help="detail mode: max offers to fetch (default 12)")
    sp.add_argument("--max-pages", type=int, default=3,
                    help="max listing pages to scan (default 3)")

    sp = sub.add_parser("ministries", help="ingest concours posts from ministry APIs (rules only)")
    add_sources_arg(sp)

    sp = sub.add_parser("token", help="save/verify the Telegram bot token")
    sp.add_argument("--set", metavar="TOKEN", help="store the token in data/telegram_token.txt")

    sp = sub.add_parser("digest", help="send (or preview with --dry) a digest to one chat")
    sp.add_argument("--chat", help="Telegram chat id")
    sp.add_argument("--dry", action="store_true", help="print instead of sending")

    sp = sub.add_parser("daily", help="refresh all sources then send digests to registered chats")
    sp.add_argument("--pages", type=int, default=20,
                    help="Emploitic listing pages per run (default 20 = ~400 offers)")
    sp.add_argument("--with-newspapers", action="store_true",
                    help="also fetch+ingest e-paper PDFs (slower)")
    sp.add_argument("--chat", action="append",
                    help="register a chat id if unknown (repeatable); "
                         "TELEGRAM_CHAT_ID env also works (for CI)")

    sp = sub.add_parser("bot", help="run the interactive Telegram bot (Ctrl+C to stop)")
    sp.add_argument("--with-daily", action="store_true",
                    help="also run the daily 06:00 refresh thread (Docker mode)")
    sp.add_argument("--pages", type=int, default=20,
                    help="Emploitic pages per daily refresh (default 20)")

    sp = sub.add_parser("export", help="Excel + JSONL export from the DB")
    add_sources_arg(sp)
    sp.add_argument("--sector")
    sp.add_argument("--limit", type=int, default=200)

    sp = sub.add_parser("stats", help="database statistics")
    return p


def main(argv: List[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return {
        "verify": cmd_verify,
        "fetch": cmd_fetch,
        "ingest": cmd_ingest,
        "run": cmd_run,
        "boards": cmd_boards,
        "ministries": cmd_ministries,
        "token": cmd_token,
        "digest": cmd_digest,
        "daily": cmd_daily,
        "bot": cmd_bot,
        "export": cmd_export,
        "stats": cmd_stats,
    }[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
