"""Stock Sentinel — main Streamlit application."""

import os
import sys
from datetime import date, datetime
from pathlib import Path

import streamlit as st
import yaml
from yaml.loader import SafeLoader

# Ensure project root on path when launched via `streamlit run app/main.py`
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

# ── Page config (must be first Streamlit call) ────────────────────────────────
st.set_page_config(
    page_title="Stock Sentinel",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Inline CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
.rec-badge {
    display: inline-block;
    padding: 3px 14px;
    border-radius: 12px;
    font-weight: 700;
    font-size: 0.85rem;
    letter-spacing: 0.04em;
}
.rec-buy    { background:#C6EFCE; color:#276221; }
.rec-hold   { background:#FFEB9C; color:#9C5700; }
.rec-avoid  { background:#FFC7CE; color:#9C0006; }

.pill {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 10px;
    font-size: 0.78rem;
    font-weight: 600;
    margin-right: 4px;
}
.pill-green  { background:#C6EFCE; color:#276221; }
.pill-yellow { background:#FFEB9C; color:#9C5700; }
.pill-red    { background:#FFC7CE; color:#9C0006; }

.card {
    border: 1px solid #E0E0E0;
    border-radius: 10px;
    padding: 18px 22px 12px;
    margin-bottom: 8px;
    background: #FAFAFA;
}
.ticker-heading { font-size: 1.5rem; font-weight: 800; }
.company-sub    { font-size: 0.95rem; color: #555; margin-top: -4px; }
</style>
""", unsafe_allow_html=True)

_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"

# ── Helper functions (defined before use) ────────────────────────────────────

def _pill(score) -> str:
    try:
        s = float(score)
    except (TypeError, ValueError):
        return '<span class="pill pill-yellow">?</span>'
    cls = "pill-green" if s >= 7 else ("pill-yellow" if s >= 4 else "pill-red")
    return f'<span class="pill {cls}">{s:.1f}</span>'


def _rec_badge(rec: str) -> str:
    rec = (rec or "").strip()
    cls = {"Buy": "rec-buy", "Hold": "rec-hold", "Avoid": "rec-avoid"}.get(rec, "rec-hold")
    return f'<span class="rec-badge {cls}">{rec}</span>'


def _score_bar(score) -> None:
    try:
        pct = min(max(float(score) / 10.0, 0), 1)
    except (TypeError, ValueError):
        pct = 0
    colour = "#276221" if pct >= 0.7 else ("#9C5700" if pct >= 0.4 else "#9C0006")
    st.markdown(
        f'<div style="background:#eee;border-radius:6px;height:10px;margin:4px 0 10px">'
        f'<div style="width:{pct*100:.0f}%;background:{colour};height:10px;border-radius:6px"></div>'
        f'</div>',
        unsafe_allow_html=True,
    )


_PARAM_LABELS = {
    "news_sentiment":      "News Sentiment",
    "buffett_value":       "Buffett Value",
    "geopolitical_thesis": "Geo Thesis",
    "self_critique":       "Self-Critique",
    "govt_contracts":      "Govt Contracts",
    "pnl_trend":           "P&L Trend",
    "politician_trades":   "Politician Trades",
    "competitor_analysis": "Competitors",
}

_REASONING_KEY = {
    "news_sentiment":      "reasoning",
    "geopolitical_thesis": "thesis",
    "self_critique":       "critique",
}


def _render_score_breakdown(scores: dict) -> None:
    for param, label in _PARAM_LABELS.items():
        sub   = scores.get(param, {})
        score = sub.get("score", "—")
        key   = _REASONING_KEY.get(param, "reasoning")
        text  = sub.get(key, "")
        st.markdown(f"{_pill(score)} **{label}**", unsafe_allow_html=True)
        if text:
            st.caption(text)


def _render_buffett(scores: dict, fd: dict) -> None:
    bv = scores.get("buffett_value", {})

    def _fmt(v, prefix="", suffix=""):
        if v is None:
            return "N/A"
        try:
            f = float(v)
            if abs(f) >= 1e12: return f"{prefix}{f/1e12:.2f}T{suffix}"
            if abs(f) >= 1e9:  return f"{prefix}{f/1e9:.2f}B{suffix}"
            if abs(f) >= 1e6:  return f"{prefix}{f/1e6:.2f}M{suffix}"
            return f"{prefix}{f:.2f}{suffix}"
        except (TypeError, ValueError):
            return str(v)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("P/E",  _fmt(fd.get("pe_ratio")))
    c2.metric("P/B",  _fmt(fd.get("pb_ratio")))
    c3.metric("D/E",  _fmt(fd.get("debt_to_equity")))
    c4.metric("FCF",  _fmt(fd.get("free_cash_flow"), "$"))

    for key, label in [
        ("pe_assessment",  "P/E"), ("pb_assessment",  "P/B"),
        ("fcf_assessment", "FCF"), ("debt_assessment", "Debt"),
    ]:
        text = bv.get(key)
        if text:
            st.markdown(f"**{label}:** {text}")


def _render_thesis_critique(scores: dict) -> None:
    col_t, col_c = st.columns(2)
    with col_t:
        st.markdown("**Investment Thesis**")
        gt = scores.get("geopolitical_thesis", {})
        st.info(gt.get("thesis", "—"))
    with col_c:
        st.markdown("**Counter-Thesis**")
        sc = scores.get("self_critique", {})
        st.warning(sc.get("critique", "—"))


def _load_today_analyses(today: str) -> list:
    try:
        from db.database import init_db, get_daily_results, get_session
        from sqlalchemy import text
        import json
        init_db()

        rows = get_daily_results(today)
        if rows:
            results = []
            for r in rows:
                raw = r.get("full_analysis_json")
                if raw:
                    try:
                        a = json.loads(raw) if isinstance(raw, str) else raw
                        results.append(a)
                    except Exception:
                        results.append(r)
                else:
                    results.append(r)
            return sorted(
                results,
                key=lambda x: float(x.get("composite_score") or 0),
                reverse=True,
            )[:5]

        # Fallback: pull from research_cache entries written today
        with get_session() as s:
            cache_rows = s.execute(
                text(
                    "SELECT data_json FROM research_cache "
                    "WHERE data_type='analysis' AND fetched_at LIKE :prefix "
                    "ORDER BY fetched_at DESC"
                ),
                {"prefix": f"{today}%"},
            ).fetchall()
        if cache_rows:
            results = [json.loads(r[0]) for r in cache_rows]
            return sorted(
                results,
                key=lambda x: float(x.get("composite_score") or 0),
                reverse=True,
            )[:5]
    except Exception as exc:
        st.warning(f"Could not load analyses: {exc}")
    return []


def _last_updated(report_file: Path) -> str:
    if report_file.exists():
        return datetime.fromtimestamp(report_file.stat().st_mtime).strftime("%H:%M")
    return "not yet generated"


def _show_download(report_file: Path) -> None:
    if report_file.exists():
        with open(report_file, "rb") as f:
            st.download_button(
                label="⬇ Download Excel Report",
                data=f.read(),
                file_name=report_file.name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
    else:
        st.caption("Excel report not yet available for today.")


def _render_stock_card(a: dict, rank: int) -> None:
    ticker  = a.get("ticker", "?")
    company = a.get("company_name", "")
    rec     = a.get("recommendation", "Hold")
    score   = a.get("composite_score", 0)
    summary = a.get("one_line_summary", "")
    scores  = a.get("scores", {})
    fd      = a.get("fundamentals", {})

    st.markdown(
        f'<div class="card">'
        f'<div class="ticker-heading">{rank}. {ticker} &nbsp; {_rec_badge(rec)}</div>'
        f'<div class="company-sub">{company}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    col_score, col_summary = st.columns([1, 4])
    with col_score:
        st.markdown(f"**Composite: {score}/10**")
        _score_bar(score)
    with col_summary:
        st.markdown(f"_{summary}_")

    exp1, exp2, exp3 = st.columns(3)
    with exp1:
        with st.expander("📊 Score breakdown"):
            _render_score_breakdown(scores)
    with exp2:
        with st.expander("💰 Buffett value"):
            _render_buffett(scores, fd)
    with exp3:
        with st.expander("⚖️ Thesis vs critique"):
            _render_thesis_critique(scores)

    st.divider()


def _render_report() -> None:
    today = date.today().isoformat()
    st.markdown(f"# Stock Sentinel — {today}")

    report_dir  = Path(__file__).parent.parent / "data" / "reports"
    report_file = report_dir / f"{today}_stock_sentinel.xlsx"
    analyses    = _load_today_analyses(today)

    if not analyses:
        st.info("Today's analysis is running — check back after 7am AEST.")
        _show_download(report_file)
        return

    st.caption(
        f"Showing top {len(analyses)} stock(s) · "
        f"Last updated: {_last_updated(report_file)}"
    )

    for rank, a in enumerate(analyses, start=1):
        _render_stock_card(a, rank)

    st.divider()
    _show_download(report_file)


# ── Pipeline orchestrator ─────────────────────────────────────────────────────
def _run_pipeline() -> None:
    from datetime import date as _date
    from db import database as db
    from ingest.reddit_scraper import scrape_mentions
    from research.haiku_filter import filter_tickers
    from research.claude_analyst import analyse_tickers
    from reports.excel_generator import generate_report

    db.init_db()
    run_id = db.create_run(_date.today().isoformat())
    try:
        mentions_df = scrape_mentions()
        mentions    = mentions_df.to_dict(orient="records")
        db.save_mentions(run_id, mentions)

        passed, _ = filter_tickers(mentions)
        analyses  = analyse_tickers(passed)
        db.save_analysis(run_id, analyses)

        top_n = int(os.getenv("TOP_N_FINAL", 5))
        picks = [a for a in analyses if not a.get("error")][:top_n]
        db.save_final_picks(run_id, picks)

        generate_report(analyses, reddit_rows=mentions)
        db.complete_run(run_id)
    except Exception as exc:
        db.fail_run(run_id, str(exc))
        raise


# ── Authentication ────────────────────────────────────────────────────────────
if not _CONFIG_PATH.exists():
    st.sidebar.warning("config.yaml not found — dev mode, no auth.")
    _display_name = "Dev User"
    _auth = None
else:
    import streamlit_authenticator as stauth

    with open(_CONFIG_PATH) as _f:
        _cfg = yaml.load(_f, Loader=SafeLoader)

    _auth = stauth.Authenticate(
        _cfg["credentials"],
        _cfg["cookie"]["name"],
        _cfg["cookie"]["key"],
        _cfg["cookie"]["expiry_days"],
    )
    _auth.login()
    _auth_status = st.session_state.get("authentication_status")

    if _auth_status is False:
        st.error("Incorrect username or password.")
        st.caption("Forgot your password? Contact your administrator to reset it.")
        st.stop()

    if _auth_status is None:
        st.markdown("### Stock Sentinel 📈")
        st.caption("Please log in to continue.")
        st.caption("Forgot your password? Contact your administrator.")
        st.stop()

    _display_name = st.session_state.get("name", "")

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📈 Stock Sentinel")
    st.caption(f"Logged in as **{_display_name}**")

    page = st.radio(
        "Navigate",
        ["Today's Report", "Tracking"],
        label_visibility="collapsed",
    )

    st.divider()
    if _auth is not None:
        _auth.logout()
    st.caption("Stock Sentinel v1.0")

# ── Route ─────────────────────────────────────────────────────────────────────
if page == "Today's Report":
    _render_report()
else:
    from app.pages.tracking import render_tracking
    render_tracking()
