"""Tests for layajobs.gating prefilter + GateResult fallback behavior."""
from __future__ import annotations

from pathlib import Path

import pytest

from layajobs import gating, textlayer

FIXTURES = Path(__file__).parent / "fixtures"

FR = (FIXTURES / "fr_notice.txt").read_text(encoding="utf-8")
AR = (FIXTURES / "ar_notice.txt").read_text(encoding="utf-8")
NEG = (FIXTURES / "negative.txt").read_text(encoding="utf-8")


class TestPrefilter:
    def test_fr_hits(self):
        assert gating.prefilter(FR) >= 2

    def test_ar_hits(self):
        assert gating.prefilter(AR) >= 2

    def test_negative_misses(self):
        assert gating.prefilter(NEG) == 0


class TestGateChunk:
    def test_keyword_rejection_short_circuits(self):
        res = gating.gate_chunk(NEG)
        assert not res.passed
        assert res.gated_by == "keyword_rejected"

    def test_fallback_without_laya(self, monkeypatch):
        def boom(text, lang=None):
            raise RuntimeError("no checkpoint")
        monkeypatch.setattr(gating.laya_engine, "gate", boom)
        res = gating.gate_chunk(FR)
        assert res.passed
        assert res.gated_by == "keyword_fallback"

    def test_laya_positive(self, monkeypatch):
        monkeypatch.setattr(gating.laya_engine, "gate",
                            lambda text, lang=None: {
                                "values": {"is_job_notice": True,
                                           "contains_classifieds": True},
                                "confidence": {"is_job_notice": 0.97,
                                               "contains_classifieds": 0.9}})
        res = gating.gate_chunk(AR)
        assert res.passed
        assert res.gated_by == "laya"
        assert res.confidence["is_job_notice"] >= 0.5

    def test_laya_negative_rejects(self, monkeypatch):
        monkeypatch.setattr(gating.laya_engine, "gate",
                            lambda text, lang=None: {
                                "values": {"is_job_notice": False,
                                           "contains_classifieds": False},
                                "confidence": {"is_job_notice": 0.9,
                                               "contains_classifieds": 0.9}})
        res = gating.gate_chunk(FR)
        assert not res.passed


class TestChunking:
    def test_text_to_chunks_basic(self):
        chunks = textlayer.text_to_chunks(FR + "\n\n" + AR)
        assert len(chunks) >= 1
        assert all(c.word_count > 0 for c in chunks)

    def test_long_text_packed_under_limit(self):
        big = "\n\n".join(
            "Avis de recrutement: la société X recrute un ingénieur. " * 3
            for _ in range(120))
        chunks = textlayer.text_to_chunks(big)
        assert all(c.word_count <= textlayer.MAX_WORDS * 1.2 for c in chunks)
        assert len(chunks) >= 2
