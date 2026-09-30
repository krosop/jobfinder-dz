"""Integration test against the real Laya multilingual checkpoint.

Runs only when LAYA_JOBS_REAL=1 is set (downloads/loads the checkpoint and
runs torch forward passes — too slow/flaky for default unit runs).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from layajobs import laya_engine

FIXTURES = Path(__file__).parent / "fixtures"
FR = (FIXTURES / "fr_notice.txt").read_text(encoding="utf-8")
AR = (FIXTURES / "ar_notice.txt").read_text(encoding="utf-8")
NEG = (FIXTURES / "negative.txt").read_text(encoding="utf-8")

pytestmark = pytest.mark.skipif(
    os.environ.get("LAYA_JOBS_REAL") != "1",
    reason="set LAYA_JOBS_REAL=1 to run real-Laya integration tests")


def test_agent_loads():
    assert laya_engine.available()


def test_gate_positive_fr():
    res = laya_engine.gate(FR, lang="fr")
    assert res["values"]["is_job_notice"] is True


def test_gate_negative():
    res = laya_engine.gate(NEG, lang="fr")
    assert res["values"]["is_job_notice"] is False or \
        res["confidence"]["is_job_notice"] < 0.5


def test_classify_ar_offer():
    res = laya_engine.classify_offer(AR, lang="ar")
    v = res["values"]
    assert v["sector"] in ("Public", "Private", "Unknown")
    assert v["contract_type"] in ("CDI", "CDD", "Statutaire", "Non spécifié")
    assert v["language"] in ("fr", "ar", "mixed")
