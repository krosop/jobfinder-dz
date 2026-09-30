# laya-jobs

Algerian print-press **job-notice scraper** gated by **Laya**, the local
System-1 decision engine (`convaiinnovations/laya`, multilingual checkpoint).

Print newspapers in Algeria publish recruitment notices (*avis de
recrutement*, إعلان توظيف, concours) inside PDF e-papers and portals — never
as clean job boards. This pipeline fetches those PDFs, finds the few chunks
that actually contain notices, extracts structured fields with bilingual
deterministic rules, and stores deduplicated offers in SQLite with Excel/JSONL
export.

## Why Laya + rules (and not an LLM)?

Laya is **not** a text generator: it answers fixed-option questions (choice /
boolean / score) with calibrated probabilities in a single fast forward pass
on CPU. That makes it ideal for *gating* ("does this chunk contain a job
notice?") and *classifying* (`sector`, `contract_type`), while free-text
fields (titles, organizations, deadlines, contacts) come from transparent
FR/AR regex rules. Every unfound field stays `null` — nothing is hallucinated.

## Install / run

Requires Python 3.11+ with `requests`, `PyMuPDF`, `openpyxl`, `laya` (all
already present on this machine), plus `pytest` for tests.

```bash
cd laya-jobs

python -m layajobs verify            # probe all sources, write data/source_status.json
python -m layajobs fetch             # discover + download e-paper PDFs (cached)
python -m layajobs ingest            # gate + extract + store (Laya required)
python -m layajobs ingest --dry-run  # gate + extract, print, no DB writes
python -m layajobs run               # fetch + ingest
python -m layajobs boards            # ingest structured offers from Emploitic (web)
python -m layajobs export            # data/reports/offers-YYYY-MM-DD.xlsx + .jsonl
python -m layajobs stats             # DB statistics
```

## Telegram daily bot 🤖

The bot ([telegram.py](layajobs/telegram.py) + [digest.py](layajobs/digest.py)
+ [wizard.py](layajobs/wizard.py) + [i18n.py](layajobs/i18n.py)) sends every
morning a **personalized digest**: 🆕 NEW offers, 🔄 still-open offers
(deadlines passed are dropped automatically), filtered per chat by wilaya /
sector / contract / keywords (FR & AR).

**Conversational onboarding**: any message to the bot (or /start) opens a
chat-style wizard — language choice (🇫🇷 🇩🇿 🇬🇧), welcome explanation, then 4
tappable steps (wilayas multi-select on a full 58-wilaya keyboard, sector,
contract, keywords) with a confirmation screen and an instant digest. Free
text while the wizard is open is consumed as keywords; commands (/city,
/digest, …) still work at any time.

One-time setup:

```bash
# 1. create the bot with @BotFather and store the token
echo "<TOKEN>" > data/telegram_token.txt      # or:
python -m layajobs token --set <TOKEN>

# 2. in Telegram: open @<yourbot>, press START, say hi

# 3. run the interactive bot to set preferences (/city Alger, /sector …)
python -m layajobs bot

# 4. or push a digest straight to a chat id
python -m layajobs digest --chat <CHAT_ID>
```

Daily automation (Windows Task Scheduler, 07:00):

```bash
schtasks /Create /TN "laya-jobs daily" /SC DAILY /ST 07:00 /TR ^
  "cmd /c cd /d C:\path\to\laya-jobs && python -m layajobs daily"
```

`laya-jobs daily` = Emploitic harvest (20 pages) + ministries refresh +
digests to every registered chat. Add `--with-newspapers` to include the
e-paper PDF sweep. Preview without sending: `digest --chat <id> --dry`.

Restrict any command with `--source <slug> ...` (slugs in
[config/sources.toml](config/sources.toml)).

## Pipeline

```
fetch (polite HTTP, per-host 2s delay, cached data/raw/<slug>/)
  → PyMuPDF text layer (needs_ocr flag for scans; OCR out of scope for v1)
  → chunk ~800 words on paragraph boundaries
  → keyword pre-filter (FR/AR regex; 0 hits ⇒ never touches Laya)
  → LAYA GATE: is_job_notice? contains_classifieds? (multilingual checkpoint)
  → rule extractor: anchors split notices; titles, orgs, deadlines,
    qualifications, phones/emails/addresses pulled by bilingual heuristics
  → LAYA CLASSIFY: sector (Public/Private), contract_type (CDI/CDD/Statutaire)
  → normalize: dates (absolute + relative "15 يوما" anchored to issue date),
    58 wilayas, phones (+213 / 0…), Arabic-Indic digits
  → SQLite dedup (org+title+deadline+source hash; times_seen counts reprints)
  → Excel (one sheet per source) + JSONL
```

## Internet job sources (added 2026-09-30)

Web research + live probing identified 13 additional sources, now in
[sources.toml](config/sources.toml) with measured statuses:

| source | kind | status |
|---|---|---|
| **Emploitic** | board | **verified** — full adapter in [boards.py](layajobs/boards.py): Schema.org JobPosting JSON inside `__NEXT_DATA__`; title/org/deadline/contract/city recovered structured (`laya-jobs boards`) |
| **El Bilad** | epaper | **verified** — daily PDF at `/storage/pdf/<hash>-file.pdf`, embedded in `/pdf/latest` |
| **El Moudjahid** | epaper | **verified** — current issue PDF embedded in the homepage (`elmoudjahid.com/storage/magazine/`) |
| **El Khabar** | epaper | **cracked** — `GET /pdf?page=N` + `X-Requested-With: XMLHttpRequest` returns a JSON issue list (214 pages of history); PDFs at `/storage/pdf/<file>` (see [config/sources.toml](config/sources.toml)) |
| Emploipartner | board | reachable — offers open in a JS drawer; needs API reverse-engineering |
| Triemploi | board | reachable |
| JobsDZ (concours aggregator) | portal | reachable (WordPress, FR/AR) |
| PresseAlgérie | portal | moved to dza.net, classifieds portal now; PDF-kiosk feature retired |
| Portail national des concours | portal | reachable over http; announcements embedded in its JS |
| Ministère des Finances / Affaires Étrangères | portal | reachable |
| Ministère de la Justice | portal | reachable (`insecure_tls`) |
| Optioncarriere, Ouedkniss Emploi | board | spa — client-side rendered; needs JSON API work |
| Algeriejob | board | blocked (403) |
| Trabajo.org DZ | board | aggregator, unexplored |

Emploitic alone yields ~24 fresh offers per listing page, so `boards` is the
highest-volume source while print PDFs stay gated behind per-site quirks.

### Print-PDF reality check (2026-09-30)

Live test with real editions: El Moudjahid's 144-page jubilee magazine and
El Bilad's daily both downloaded and processed end-to-end (185 chunks).
Outcome validated the two-stage gate: 7 keyword hits on Moudjahid were all
editorial history, and **Laya rejected every one with 97–100% confidence** —
zero false positives stored. El Bilad's text layer is mojibake (legacy font
encoding) and is correctly flagged `needs_ocr` — OCR is the v2 unlock for
Arabic scanned papers.

The gov portals (DGFP / ANEM / concours-fonction-publique) syndicate exactly
the public-sector concours that newspapers print, but serve content via
JavaScript — per-source API adapters are the natural v2 (see
[scripts/probe_annasr.py](scripts/probe_annasr.py) for the probe pattern).

You can always drop manually-downloaded PDFs into `data/raw/<slug>/` and run
`python -m layajobs ingest` — the pipeline never fakes data.

## Tests

```bash
python -m pytest -q                       # 55 unit tests (no network, no Laya load)
LAYA_JOBS_REAL=1 python -m pytest tests/test_laya_engine.py -q   # real checkpoint
```

Fixtures in [tests/fixtures/](tests/fixtures/) carry two FR and two AR
notices (one with a relative deadline) plus a negative sports sample.

## Layout

```
layajobs/
  fetchers.py     sources, polite HTTP, PDF discovery + cache, verify
  textlayer.py    PyMuPDF extraction, OCR detection, chunking
  gating.py       keyword pre-filter + Laya gate (keyword fallback mode)
  laya_engine.py  singleton agent, gate/offer decision schemas + confidence
  extractor.py    bilingual anchor splitting + field rules
  normalize.py    dates, relative deadlines, wilayas, phones, emails
  store.py        SQLite offers/runs, dedup upsert, queries
  boards.py       online board adapters (Emploitic listing JSON + detail pages)
  ministries.py   ministry WP REST adapters (Education, Santé, Intérieur, Justice)
  export.py       openpyxl workbook + JSONL
  cli.py          verify | fetch | ingest | run | export | stats
```
