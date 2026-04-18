"""Test dashboard — visually verify scraper, financial data, and DB."""

import json
import sys
import os

# Ensure project root is on path when run via `streamlit run app/test_ui.py`
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="Stock Sentinel — Test UI", layout="wide")
st.title("🧪 Stock Sentinel — Test Dashboard")

# ─────────────────────────────────────────────────────────────────────────────
# Section 1 — Reddit Scraper
# ─────────────────────────────────────────────────────────────────────────────
st.header("1 · Reddit Scraper")

RAW_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "reddit_raw.json")
RAW_PATH = os.path.abspath(RAW_PATH)


def _load_raw() -> list[dict]:
    if os.path.exists(RAW_PATH):
        with open(RAW_PATH) as f:
            return json.load(f)
    return []


col_btn, col_ts = st.columns([2, 3])

with col_btn:
    run_scraper = st.button("▶ Run Reddit Scraper", type="primary")

if run_scraper:
    with st.spinner("Scraping Reddit (last 24 h)…"):
        try:
            from ingest.reddit_scraper import scrape_mentions, save_to_json
            df_raw = scrape_mentions()
            save_to_json(df_raw, RAW_PATH)
            st.success(f"Done — {len(df_raw)} ticker(s) above threshold.")
        except Exception as exc:
            st.error(f"Scraper error: {exc}")

raw_data = _load_raw()

with col_ts:
    if os.path.exists(RAW_PATH):
        mtime = os.path.getmtime(RAW_PATH)
        import datetime
        ts = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        st.caption(f"Last scrape: **{ts}**")

if raw_data:
    df_mentions = pd.DataFrame(raw_data)

    top10 = df_mentions.head(10)

    st.subheader("Top 10 tickers by mention count")
    st.bar_chart(top10.set_index("ticker")["mentions"])

    st.subheader("Full results table")
    show_cols = [c for c in ["ticker", "mentions", "subreddits_seen", "last_seen_utc"] if c in df_mentions.columns]
    st.dataframe(df_mentions[show_cols], width="stretch")
else:
    st.info("No scrape data yet — click **Run Reddit Scraper** above.")

st.divider()

# ─────────────────────────────────────────────────────────────────────────────
# Section 2 — Financial Data
# ─────────────────────────────────────────────────────────────────────────────
st.header("2 · Financial Data")

ticker_input = st.text_input("Enter a ticker", value="NVDA", max_chars=10).strip().upper()
fetch_btn    = st.button("▶ Fetch Financial Data", type="primary")

if fetch_btn and ticker_input:
    with st.spinner(f"Fetching data for {ticker_input}…"):
        try:
            from db.database import init_db
            init_db()
            from research.financial_data import fetch_financial_data
            data = fetch_financial_data(ticker_input)

            cache_status = data.get("cache_status", "unknown")
            if cache_status == "hit":
                st.success("✅ CACHE HIT — data served from database")
            elif cache_status == "miss":
                st.warning("🔄 CACHE MISS — fetched fresh from yfinance / NewsAPI")
            else:
                st.info(f"⚡ PARTIAL CACHE — {cache_status}")

            # ── Fundamentals card ────────────────────────────────────────────
            st.subheader(f"{data.get('company_name', ticker_input)} ({ticker_input})")

            def _fmt_large(val) -> str:
                if val is None:
                    return "—"
                val = float(val)
                if val >= 1e12:
                    return f"${val/1e12:.2f}T"
                if val >= 1e9:
                    return f"${val/1e9:.2f}B"
                if val >= 1e6:
                    return f"${val/1e6:.2f}M"
                return f"{val:,.2f}"

            def _fmt(val, prefix="", suffix="", decimals=2) -> str:
                if val is None:
                    return "—"
                return f"{prefix}{float(val):.{decimals}f}{suffix}"

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Price",       _fmt(data.get("current_price"), prefix="$"))
            c2.metric("Market Cap",  _fmt_large(data.get("market_cap")))
            c3.metric("P/E Ratio",   _fmt(data.get("pe_ratio")))
            c4.metric("P/B Ratio",   _fmt(data.get("pb_ratio")))

            c5, c6, c7, c8 = st.columns(4)
            c5.metric("Debt / Equity", _fmt(data.get("debt_to_equity")))
            c6.metric("Free Cash Flow", _fmt_large(data.get("free_cash_flow")))
            c7.metric("52w High",    _fmt(data.get("week_52_high"), prefix="$"))
            c8.metric("52w Low",     _fmt(data.get("week_52_low"),  prefix="$"))

            c9, c10, c11, c12 = st.columns(4)
            c9.metric("Revenue TTM",    _fmt_large(data.get("revenue_ttm")))
            c10.metric("Net Income TTM", _fmt_large(data.get("net_income_ttm")))
            c11.metric("30d Price Δ",   _fmt(data.get("price_change_30d_pct"), suffix="%"))
            c12.metric("Analyst",       str(data.get("analyst_consensus") or "—").replace("_", " ").title())

            # ── News headlines ───────────────────────────────────────────────
            news = data.get("news", [])
            st.subheader(f"Recent News ({len(news)} headlines)")
            if news:
                for article in news:
                    pub = article.get("published_at", "")[:10]
                    src = article.get("source") or "Unknown"
                    url = article.get("url", "#")
                    title = article.get("title", "No title")
                    st.markdown(f"- **[{title}]({url})** — *{src}* · {pub}")
            else:
                st.info("No news found (check NEWS_API_KEY in .env).")

        except Exception as exc:
            st.error(f"Error fetching {ticker_input}: {exc}")
            st.exception(exc)

st.divider()

# ─────────────────────────────────────────────────────────────────────────────
# Section 3 — Database
# ─────────────────────────────────────────────────────────────────────────────
st.header("3 · Database")

try:
    from db.database import init_db, get_session
    from sqlalchemy import text

    init_db()

    # ── Row counts ────────────────────────────────────────────────────────────
    TABLES = [
        "research_cache",
        "reddit_mentions",
        "daily_results",
        "run_log",
        "ticker_mentions",
        "ticker_analysis",
        "final_picks",
    ]

    st.subheader("Table row counts")
    count_cols = st.columns(len(TABLES))
    with get_session() as s:
        for col, tbl in zip(count_cols, TABLES):
            try:
                n = s.execute(text(f"SELECT COUNT(*) FROM {tbl}")).fetchone()[0]
                col.metric(tbl, n)
            except Exception:
                col.metric(tbl, "—")

    # ── Cache table ───────────────────────────────────────────────────────────
    st.subheader("research_cache contents")

    col_refresh, col_clear = st.columns([1, 1])
    with col_clear:
        if st.button("🗑 Clear Cache", type="secondary"):
            with get_session() as s:
                s.execute(text("DELETE FROM research_cache"))
            st.success("Cache cleared.")
            st.rerun()

    with get_session() as s:
        rows = s.execute(
            text("SELECT ticker, data_type, fetched_at, expires_at FROM research_cache ORDER BY fetched_at DESC")
        ).mappings().fetchall()

    if rows:
        st.dataframe(pd.DataFrame([dict(r) for r in rows]), width="stretch")
    else:
        st.info("Cache is empty.")

except Exception as exc:
    st.error(f"Database error: {exc}")
    st.exception(exc)
