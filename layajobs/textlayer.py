"""PDF text layer: page extraction, OCR detection, and chunking.

Uses PyMuPDF. Scanned pages without a text layer are flagged `needs_ocr`
(OCR itself is out of scope for v1 — no Tesseract dependency). Chunks are
packed around ~MAX_WORDS words on paragraph boundaries so downstream Laya
decisions see coherent blocks, not arbitrary 500-char slices.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, List, Optional

try:  # PyMuPDF >= 1.26 exposes the canonical `pymupdf` name
    import pymupdf as fitz
except ImportError:  # older wheels
    import fitz

# A page with fewer characters than this (but with image content) is treated
# as a scan needing OCR.
NEEDS_OCR_MIN_CHARS = 40

# Chunk size in words. Laya handles the state fine at this size; smaller
# chunks waste forward passes, bigger ones dilute per-block classification.
MAX_WORDS = 800
MIN_CHUNK_WORDS = 30  # fragments below this are merged forward


@dataclass
class Chunk:
    """A coherent slice of one PDF page (or raw text)."""

    text: str
    page: int                 # 1-based page number, 0 for non-PDF text
    index: int                # chunk index within the document
    needs_ocr: bool = False
    word_count: int = 0

    def __post_init__(self) -> None:
        if not self.word_count:
            self.word_count = len(self.text.split())


@dataclass
class PageText:
    page: int
    text: str
    char_count: int = 0
    needs_ocr: bool = False


_PARA_SPLIT = re.compile(r"\n\s*\n+")


def _page_texts(pdf_path: Path) -> List[PageText]:
    pages: List[PageText] = []
    with fitz.open(pdf_path) as doc:
        for i, page in enumerate(doc, start=1):
            text = page.get_text("text", sort=True) or ""
            text = text.replace("\u00ad", "")  # soft hyphens
            n_images = 0
            try:
                n_images = len(page.get_images(full=True))
            except Exception:
                pass
            needs_ocr = len(text.strip()) < NEEDS_OCR_MIN_CHARS and n_images > 0
            pages.append(PageText(page=i, text=text, char_count=len(text),
                                  needs_ocr=needs_ocr))
    return pages


def _pack_paragraphs(paragraphs: List[str], max_words: int = MAX_WORDS) -> List[str]:
    """Pack paragraphs into chunks near `max_words` without splitting mid-paragraph."""
    chunks: List[str] = []
    buf: List[str] = []
    buf_words = 0

    def flush() -> None:
        nonlocal buf, buf_words
        if buf:
            chunks.append("\n\n".join(buf).strip())
            buf, buf_words = [], 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        words = para.split()
        # Pathological single paragraph longer than the budget: hard-split it.
        if len(words) > max_words:
            flush()
            for i in range(0, len(words), max_words):
                piece = " ".join(words[i:i + max_words])
                if i + max_words < len(words):
                    chunks.append(piece)
                else:
                    buf, buf_words = [piece], len(words) - i
            continue
        if buf_words + len(words) > max_words and buf:
            flush()
        buf.append(para)
        buf_words += len(words)
    flush()
    return chunks


def pdf_to_chunks(pdf_path: str | Path) -> List[Chunk]:
    """Extract text from a PDF and return packed chunks (page-aware)."""
    pdf_path = Path(pdf_path)
    out: List[Chunk] = []
    idx = 0
    for pt in _page_texts(pdf_path):
        if not pt.text.strip():
            continue
        paras = _PARA_SPLIT.split(pt.text)
        packed = _pack_paragraphs(paras)
        for c_text in packed:
            if not c_text:
                continue
            out.append(Chunk(text=c_text, page=pt.page, index=idx,
                             needs_ocr=pt.needs_ocr))
            idx += 1
    # Merge trailing fragments into their predecessor to avoid micro-chunks.
    merged: List[Chunk] = []
    for c in out:
        if merged and c.word_count < MIN_CHUNK_WORDS:
            prev = merged[-1]
            if prev.page == c.page and prev.word_count + c.word_count <= MAX_WORDS * 1.2:
                prev.text = prev.text + "\n\n" + c.text
                prev.word_count += c.word_count
                continue
        merged.append(c)
    return merged


def text_to_chunks(text: str, *, page: int = 0) -> List[Chunk]:
    """Chunk raw text (HTML-derived, clipboard, fixtures) the same way as PDFs."""
    paras = _PARA_SPLIT.split(text or "")
    out: List[Chunk] = []
    for i, c_text in enumerate(_pack_paragraphs(paras)):
        if c_text:
            out.append(Chunk(text=c_text, page=page, index=i))
    return out


def needs_ocr_pages(pdf_path: str | Path) -> List[int]:
    """Page numbers that look like image-only scans (no usable text layer)."""
    return [pt.page for pt in _page_texts(Path(pdf_path)) if pt.needs_ocr]
