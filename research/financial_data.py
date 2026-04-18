"""Fetch fundamental and price data via yfinance and News API, with DB-backed caching."""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
import yfinance as yf
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")

_FUNDAMENTALS_TTL = 23 * 3600   # 23 hours
_NEWS_TTL         =  2 * 3600   #  2 hours


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _cache_get(ticker: str, data_type: str) -> Optional[dict]:
    from db.database import get_cache
    return get_cache(ticker, data_type)


def _cache_set(ticker: str, data_type: str, data: dict, ttl: int) -> None:
    from db.database import set_cache
    set_cache(ticker, data_type, data, ttl)


# ── yfinance helpers ──────────────────────────────────────────────────────────

def _safe(info: dict, key: str):
    """Return info[key] or None — never raises."""
    try:
        val = info.get(key)
        return None if val in (None, "N/A", float("inf"), float("-inf")) else val
    except Exception:
        return None


def _quarterly_series(series, n: int = 4) -> list:
    """Convert a yfinance quarterly Series to a plain list of (date, value) pairs."""
    try:
        if series is None or series.empty:
            return []
        trimmed = series.dropna().head(n)
        return [
            {"period": str(idx)[:10], "value": float(val)}
            for idx, val in trimmed.items()
        ]
    except Exception:
        return []


def _fetch_fundamentals(ticker: str) -> dict:
    """Fetch fundamentals from yfinance. Every field handled gracefully."""
    t = yf.Ticker(ticker)
    info = {}
    try:
        info = t.info or {}
    except Exception as exc:
        log.warning("yfinance info failed for %s: %s", ticker, exc)

    # Quarterly revenue / net income
    rev_q, ni_q = [], []
    try:
        qf = t.quarterly_financials
        if qf is not None and not qf.empty:
            if "Total Revenue" in qf.index:
                rev_q = _quarterly_series(qf.loc["Total Revenue"])
            if "Net Income" in qf.index:
                ni_q = _quarterly_series(qf.loc["Net Income"])
    except Exception as exc:
        log.warning("yfinance quarterly_financials failed for %s: %s", ticker, exc)

    return {
        "company_name":       _safe(info, "shortName"),
        "sector":             _safe(info, "sector"),
        "industry":           _safe(info, "industry"),
        "current_price":      _safe(info, "currentPrice"),
        "market_cap":         _safe(info, "marketCap"),
        "pe_ratio":           _safe(info, "trailingPE"),
        "forward_pe":         _safe(info, "forwardPE"),
        "pb_ratio":           _safe(info, "priceToBook"),
        "debt_to_equity":     _safe(info, "debtToEquity"),
        "free_cash_flow":     _safe(info, "freeCashflow"),
        "revenue_ttm":        _safe(info, "totalRevenue"),
        "net_income_ttm":     _safe(info, "netIncomeToCommon"),
        "earnings_growth_yoy":_safe(info, "earningsGrowth"),
        "revenue_growth_yoy": _safe(info, "revenueGrowth"),
        "gross_margins":      _safe(info, "grossMargins"),
        "operating_margins":  _safe(info, "operatingMargins"),
        "return_on_equity":   _safe(info, "returnOnEquity"),
        "week_52_high":       _safe(info, "fiftyTwoWeekHigh"),
        "week_52_low":        _safe(info, "fiftyTwoWeekLow"),
        "average_volume":     _safe(info, "averageVolume"),
        "beta":               _safe(info, "beta"),
        "short_ratio":        _safe(info, "shortRatio"),
        "analyst_consensus":  _safe(info, "recommendationKey"),
        "revenue_quarterly":  rev_q,
        "net_income_quarterly": ni_q,
    }


def get_fundamentals(ticker: str) -> dict:
    """Return fundamentals, using DB cache when valid (TTL 23 h)."""
    cached = _cache_get(ticker, "fundamentals")
    if cached is not None:
        log.info("CACHE HIT  fundamentals  %s", ticker)
        return cached

    log.info("CACHE MISS fundamentals  %s — fetching from yfinance", ticker)
    data = _fetch_fundamentals(ticker)
    _cache_set(ticker, "fundamentals", data, _FUNDAMENTALS_TTL)
    return data


# ── News API helper ───────────────────────────────────────────────────────────

def _fetch_news(ticker: str, company_name: str = None, page_size: int = 10) -> list:
    """Fetch last 10 headlines from NewsAPI, articles from the past 48 hours."""
    api_key = os.getenv("NEWS_API_KEY")
    if not api_key:
        log.warning("NEWS_API_KEY not set — skipping news fetch for %s", ticker)
        return []

    query = ticker if not company_name else f"{ticker} OR \"{company_name}\""
    from_dt = (datetime.now(tz=timezone.utc) - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")

    params = {
        "q":        query,
        "from":     from_dt,
        "sortBy":   "publishedAt",
        "pageSize": page_size,
        "language": "en",
        "apiKey":   api_key,
    }
    try:
        resp = requests.get("https://newsapi.org/v2/everything", params=params, timeout=10)
        resp.raise_for_status()
        articles = resp.json().get("articles", [])
    except Exception as exc:
        log.warning("NewsAPI request failed for %s: %s", ticker, exc)
        return []

    return [
        {
            "title":        a.get("title"),
            "source":       a.get("source", {}).get("name"),
            "published_at": a.get("publishedAt"),
            "url":          a.get("url"),
        }
        for a in articles
        if a.get("title") and "[Removed]" not in a.get("title", "")
    ]


def get_news(ticker: str, company_name: str = None) -> list:
    """Return news headlines, using DB cache when valid (TTL 2 h)."""
    cached = _cache_get(ticker, "news")
    if cached is not None:
        log.info("CACHE HIT  news          %s", ticker)
        return cached

    log.info("CACHE MISS news          %s — fetching from NewsAPI", ticker)
    data = _fetch_news(ticker, company_name=company_name)
    _cache_set(ticker, "news", data, _NEWS_TTL)
    return data


# ── Price history (not cached — fast and cheap) ───────────────────────────────

def get_price_history(ticker: str, days: int = 30) -> pd.DataFrame:
    """Return OHLCV data for the past N days."""
    end   = datetime.now(tz=timezone.utc)
    start = end - timedelta(days=days)
    try:
        df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
        df.index = pd.to_datetime(df.index)
        return df
    except Exception as exc:
        log.warning("Price history failed for %s: %s", ticker, exc)
        return pd.DataFrame()


def _price_change(df: pd.DataFrame) -> Optional[float]:
    """Compute 30-day price change % from OHLCV DataFrame."""
    try:
        if df.empty or "Close" not in df.columns:
            return None
        closes = df["Close"].dropna()
        if len(closes) < 2:
            return None
        first = float(closes.iloc[0].iloc[0] if hasattr(closes.iloc[0], "iloc") else closes.iloc[0])
        last  = float(closes.iloc[-1].iloc[0] if hasattr(closes.iloc[-1], "iloc") else closes.iloc[-1])
        return round(((last - first) / first) * 100, 2)
    except Exception:
        return None


# ── Unified payload builder ───────────────────────────────────────────────────

def fetch_financial_data(ticker: str) -> dict:
    """Return a flat dict of all financial data for a ticker.

    Includes a 'cache_status' key: 'hit' if both fundamentals and news came
    from cache, 'miss' if either required a live fetch, 'partial' if one did.
    """
    ticker = ticker.upper()

    fundamentals_cached = _cache_get(ticker, "fundamentals") is not None
    news_cached         = _cache_get(ticker, "news") is not None

    fundamentals = get_fundamentals(ticker)
    news         = get_news(ticker, company_name=fundamentals.get("company_name"))
    price_change = _price_change(get_price_history(ticker, days=30))

    if fundamentals_cached and news_cached:
        cache_status = "hit"
    elif not fundamentals_cached and not news_cached:
        cache_status = "miss"
    else:
        cache_status = "partial"

    return {
        **fundamentals,
        "ticker":               ticker,
        "price_change_30d_pct": price_change,
        "news":                 news,
        "cache_status":         cache_status,
    }


def build_research_payload(ticker: str) -> dict:
    """Aggregate all data for a single ticker into one dict for Claude.

    Reads fundamentals and news from cache when available; falls back to live
    API calls on cache miss and stores the result for subsequent callers.
    """
    fundamentals = get_fundamentals(ticker)
    news = get_news(ticker, company_name=fundamentals.get("company_name"))
    price_change_30d = _price_change(get_price_history(ticker, days=30))

    return {
        "ticker":             ticker,
        "fundamentals":       fundamentals,
        "price_change_30d_pct": price_change_30d,
        "recent_news":        news,
    }
