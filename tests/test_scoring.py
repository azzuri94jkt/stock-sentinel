"""Tests for scoring logic and report generation."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from reports.excel_generator import generate_report
from pathlib import Path
import tempfile


SAMPLE_ANALYSES = [
    {
        "ticker": "AAPL",
        "company_name": "Apple Inc.",
        "overall_score": 88,
        "recommendation": "BUY",
        "thesis": "Strong ecosystem lock-in with growing services revenue.",
        "bull_case": "Services margin expansion drives EPS upside.",
        "bear_case": "China revenue at risk from tariffs.",
        "key_risks": ["Regulatory risk", "China exposure"],
        "catalysts": ["New iPhone cycle", "Vision Pro adoption"],
        "price_target_rationale": "20x forward earnings implies $210 target.",
        "price_change_30d_pct": 4.2,
        "input_tokens": 800,
        "output_tokens": 300,
    },
    {
        "ticker": "NVDA",
        "company_name": "NVIDIA Corporation",
        "overall_score": 95,
        "recommendation": "STRONG BUY",
        "thesis": "AI infrastructure buildout drives multi-year demand.",
        "bull_case": "Data center revenue can 3x over 3 years.",
        "bear_case": "Valuation stretched at current multiples.",
        "key_risks": ["Supply constraints", "Competition from AMD"],
        "catalysts": ["Blackwell ramp", "Sovereign AI spending"],
        "price_target_rationale": "35x forward P/E on $30 EPS = $1050.",
        "price_change_30d_pct": 12.7,
        "input_tokens": 900,
        "output_tokens": 350,
    },
    {
        "ticker": "GME",
        "company_name": "GameStop Corp.",
        "overall_score": 22,
        "recommendation": "SELL",
        "thesis": "Declining brick-and-mortar with no viable pivot.",
        "bull_case": "Meme momentum could spike short-term.",
        "bear_case": "Revenues in secular decline.",
        "key_risks": ["Revenue decline", "Management uncertainty"],
        "catalysts": [],
        "price_target_rationale": "Book value provides $8 floor.",
        "price_change_30d_pct": -8.1,
        "input_tokens": 700,
        "output_tokens": 280,
    },
]


def test_report_creates_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir) / "test_report.xlsx"
        result = generate_report(SAMPLE_ANALYSES, output_path=out)
        assert result.exists()
        assert result.stat().st_size > 0


def test_report_top_n_respected():
    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir) / "test_report_top1.xlsx"
        result = generate_report(SAMPLE_ANALYSES, output_path=out, top_n=1)
        assert result.exists()


def test_sorted_by_score():
    scores = [a["overall_score"] for a in SAMPLE_ANALYSES]
    sorted_scores = sorted(scores, reverse=True)
    assert sorted_scores == [95, 88, 22]


def test_analyses_with_error_excluded():
    data = SAMPLE_ANALYSES + [{"ticker": "BAD", "error": "API timeout", "overall_score": 0}]
    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir) / "test_report_err.xlsx"
        result = generate_report(data, output_path=out)
        assert result.exists()


def test_empty_analyses():
    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir) / "test_report_empty.xlsx"
        result = generate_report([], output_path=out)
        assert result.exists()
