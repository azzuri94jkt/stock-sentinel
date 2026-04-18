"""Tests for ticker extraction logic in reddit_scraper."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingest.reddit_scraper import _extract_tickers, STOPWORDS


FAKE_VALID = {"AAPL", "TSLA", "NVDA", "GME", "AMC", "MSFT", "GOOG", "META"}


def test_dollar_sign_extraction():
    text = "I just bought $AAPL and $TSLA calls today"
    result = _extract_tickers(text, FAKE_VALID)
    assert "AAPL" in result
    assert "TSLA" in result


def test_bare_caps_extraction():
    text = "NVDA is going to moon, forget GME"
    result = _extract_tickers(text, FAKE_VALID)
    assert "NVDA" in result
    assert "GME" in result


def test_stopwords_excluded():
    text = "I AM SO BULLISH ON THE FED AND IPO season"
    result = _extract_tickers(text, FAKE_VALID)
    for word in ["I", "AM", "SO", "ON", "THE", "FED", "IPO", "AND"]:
        assert word not in result


def test_invalid_ticker_excluded():
    text = "XYZZY and QQQQQ are not real tickers"
    result = _extract_tickers(text, FAKE_VALID)
    assert "XYZZY" not in result
    assert "QQQQQ" not in result


def test_mixed_case_text():
    text = "aapl is cheap but MSFT is better"
    result = _extract_tickers(text, FAKE_VALID)
    # lowercase words won't match bare-caps pattern but $aapl wouldn't either
    # MSFT should match
    assert "MSFT" in result


def test_empty_text():
    assert _extract_tickers("", FAKE_VALID) == []


def test_no_false_positives_from_common_words():
    text = "BE careful, DO your DD, NO YOLO"
    result = _extract_tickers(text, FAKE_VALID)
    for sw in STOPWORDS:
        assert sw not in result
