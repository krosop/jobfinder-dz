"""Deep-probe An Nasr inner page PDFs (p2..p10).

The generic discovery only sees the linked front page; Algerian e-paper
readers expose inner pages by URL convention (p1.pdf..p12.pdf). Polite:
2s per-host delay, bounded page count, cached downloads.
"""
from __future__ import annotations

from layajobs.fetchers import download_pdf

BASE = "https://www.annasronline.com/wp-content/uploads/epaper/"


def main() -> int:
    saved = 0
    for n in range(2, 11):
        url = f"{BASE}p{n}.pdf"
        path = download_pdf(url, "data/raw", slug="an-nasr")
        if path:
            print(f"p{n}: saved -> {path.name}")
            saved += 1
        else:
            print(f"p{n}: not available")
    print(f"\n{saved} inner page(s) saved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
