"""Tracking dashboard — score history, price overlay, Reddit volume, alerts."""

import json
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

# ── Data loaders ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def _load_score_history() -> pd.DataFrame:
    """Return all daily_results rows as a DataFrame."""
    try:
        from db.database import get_session
        from sqlalchemy import text
        with get_session() as s:
            rows = s.execute(
                text(
                    "SELECT run_date, ticker, composite_score, recommendation, "
                    "score_news, score_buffett, score_thesis, score_critique, "
                    "score_contracts, score_pnl, score_politicians, score_competitors "
                    "FROM daily_results ORDER BY run_date ASC"
                )
            ).mappings().fetchall()
        return pd.DataFrame([dict(r) for r in rows])
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def _load_reddit_volume() -> pd.DataFrame:
    """Return reddit_mentions rows as a DataFrame."""
    try:
        from db.database import get_session
        from sqlalchemy import text
        with get_session() as s:
            rows = s.execute(
                text(
                    "SELECT run_date, ticker, mention_count "
                    "FROM reddit_mentions ORDER BY run_date ASC"
                )
            ).mappings().fetchall()
        return pd.DataFrame([dict(r) for r in rows])
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=600)
def _fetch_price_history(ticker: str, days: int) -> pd.DataFrame:
    """Fetch OHLCV from yfinance for the last N days."""
    try:
        import yfinance as yf
        end   = datetime.utcnow()
        start = end - timedelta(days=days)
        df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
        if df.empty:
            return pd.DataFrame()
        df.index = pd.to_datetime(df.index)
        df.index = df.index.tz_localize(None)
        close = df["Close"]
        if hasattr(close, "squeeze"):
            close = close.squeeze()
        return close.rename("price").reset_index().rename(columns={"Date": "date"})
    except Exception:
        return pd.DataFrame()


# ── Section renderers ─────────────────────────────────────────────────────────

def _section_score_history(df_history: pd.DataFrame, selected: list) -> None:
    st.subheader("Score history")
    if df_history.empty or not selected:
        st.info("No score history in the database yet.")
        return

    subset = df_history[df_history["ticker"].isin(selected)].copy()
    if subset.empty:
        st.info("No history for the selected tickers.")
        return

    subset["run_date"] = pd.to_datetime(subset["run_date"])
    pivot = subset.pivot(index="run_date", columns="ticker", values="composite_score")

    try:
        import plotly.express as px
        fig = px.line(
            pivot.reset_index().melt(id_vars="run_date", var_name="Ticker", value_name="Score"),
            x="run_date", y="Score", color="Ticker",
            labels={"run_date": "Date", "Score": "Composite Score"},
            markers=True,
        )
        fig.update_layout(
            yaxis=dict(range=[0, 10]),
            legend_title_text="Ticker",
            margin=dict(l=0, r=0, t=30, b=0),
        )
        st.plotly_chart(fig, use_container_width=True)
    except ImportError:
        st.line_chart(pivot)


def _section_price_score_overlay(df_history: pd.DataFrame, selected: list) -> None:
    st.subheader("Price vs score overlay")

    days_map = {"7 days": 7, "30 days": 30, "All time": 365}
    period   = st.radio("Date range", list(days_map.keys()), horizontal=True, key="overlay_range")
    days     = days_map[period]

    try:
        import plotly.graph_objects as go
    except ImportError:
        st.warning("Install plotly: `pip install plotly`")
        return

    if df_history.empty or not selected:
        st.info("No data to overlay.")
        return

    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

    for ticker in selected:
        score_df = df_history[
            (df_history["ticker"] == ticker) &
            (df_history["run_date"] >= cutoff)
        ].copy()
        score_df["run_date"] = pd.to_datetime(score_df["run_date"])

        price_df = _fetch_price_history(ticker, days)

        if score_df.empty and price_df.empty:
            st.caption(f"{ticker}: no data in range.")
            continue

        fig = go.Figure()

        if not score_df.empty:
            fig.add_trace(go.Scatter(
                x=score_df["run_date"],
                y=score_df["composite_score"],
                name="Composite Score",
                mode="lines+markers",
                line=dict(color="#1F4E79", width=2),
                yaxis="y1",
            ))

        if not price_df.empty:
            fig.add_trace(go.Scatter(
                x=price_df["date"],
                y=price_df["price"],
                name="Price ($)",
                mode="lines",
                line=dict(color="#E07B39", width=2, dash="dot"),
                yaxis="y2",
            ))

        fig.update_layout(
            title=f"{ticker} — Score vs Price",
            xaxis=dict(title="Date"),
            yaxis=dict(title="Composite Score", range=[0, 10], side="left"),
            yaxis2=dict(title="Price ($)", overlaying="y", side="right", showgrid=False),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            margin=dict(l=0, r=0, t=50, b=0),
            height=350,
        )
        st.plotly_chart(fig, use_container_width=True)


def _section_reddit_volume(df_reddit: pd.DataFrame, selected: list) -> None:
    st.subheader("Reddit mention volume")
    if df_reddit.empty:
        st.info("No Reddit mention data in the database yet.")
        return

    subset = df_reddit[df_reddit["ticker"].isin(selected)].copy() if selected else df_reddit.copy()
    if subset.empty:
        st.info("No Reddit data for the selected tickers.")
        return

    subset["run_date"] = pd.to_datetime(subset["run_date"])

    try:
        import plotly.express as px
        fig = px.bar(
            subset,
            x="run_date", y="mention_count", color="ticker",
            barmode="group",
            labels={"run_date": "Date", "mention_count": "Mentions", "ticker": "Ticker"},
        )
        fig.update_layout(margin=dict(l=0, r=0, t=30, b=0), legend_title_text="Ticker")
        st.plotly_chart(fig, use_container_width=True)
    except ImportError:
        pivot = subset.pivot(index="run_date", columns="ticker", values="mention_count").fillna(0)
        st.bar_chart(pivot)


def _section_alerts(df_history: pd.DataFrame) -> None:
    st.subheader("Score change alerts  (±2 or more vs prior day)")

    if df_history.empty:
        st.info("No history data yet — alerts will appear once multiple days are recorded.")
        return

    df = df_history.copy()
    df["run_date"] = pd.to_datetime(df["run_date"])
    df = df.sort_values(["ticker", "run_date"])
    df["prev_score"] = df.groupby("ticker")["composite_score"].shift(1)
    df["prev_rec"]   = df.groupby("ticker")["recommendation"].shift(1)
    df["change"]     = (df["composite_score"] - df["prev_score"]).round(2)

    alerts = df[df["change"].abs() >= 2].dropna(subset=["change"])

    if alerts.empty:
        st.success("No significant score changes in recorded history.")
        return

    latest_date = df["run_date"].max()
    alerts = alerts[alerts["run_date"] == latest_date] if not alerts.empty else alerts

    if alerts.empty:
        st.success("No ±2 score changes in the most recent run.")
        return

    display = alerts[[
        "ticker", "prev_score", "composite_score", "change", "prev_rec", "recommendation"
    ]].rename(columns={
        "ticker":          "Ticker",
        "prev_score":      "Yesterday",
        "composite_score": "Today",
        "change":          "Change",
        "prev_rec":        "Prev Rec",
        "recommendation":  "New Rec",
    }).reset_index(drop=True)

    def _row_style(row):
        colour = "#C6EFCE" if row["Change"] >= 2 else "#FFC7CE"
        return [f"background-color: {colour}"] * len(row)

    st.dataframe(
        display.style.apply(_row_style, axis=1),
        use_container_width=True,
    )


# ── Public entry point ────────────────────────────────────────────────────────

def render_tracking() -> None:
    st.markdown("# Tracking")

    df_history = _load_score_history()
    df_reddit  = _load_reddit_volume()

    # Ticker selector
    all_tickers = sorted(df_history["ticker"].unique().tolist()) if not df_history.empty else []
    if not all_tickers:
        st.info("No analysis data yet. Run the pipeline to populate tracking data.")
        return

    selected = st.multiselect(
        "Select tickers to display",
        options=all_tickers,
        default=all_tickers[:5],
    )

    st.divider()
    _section_score_history(df_history, selected)

    st.divider()
    _section_price_score_overlay(df_history, selected)

    st.divider()
    _section_reddit_volume(df_reddit, selected)

    st.divider()
    _section_alerts(df_history)
