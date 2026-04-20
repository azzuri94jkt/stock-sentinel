"""SQLAlchemy-backed database layer."""

import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from dotenv import load_dotenv

load_dotenv()

_DB_URL = os.getenv("DATABASE_URL", "sqlite:///stock_sentinel.db")
_engine = create_engine(_DB_URL, echo=False, future=True)
_SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)


def init_db() -> None:
    """Create all tables from schema.sql if they don't exist."""
    schema_path = Path(__file__).parent / "schema.sql"
    ddl = schema_path.read_text()
    with _engine.connect() as conn:
        for statement in ddl.split(";"):
            stmt = statement.strip()
            if stmt:
                conn.execute(text(stmt))
        conn.commit()


@contextmanager
def get_session():
    session: Session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ── Run log ──────────────────────────────────────────────────────────────────

def create_run(run_date: str) -> int:
    with get_session() as s:
        result = s.execute(
            text("INSERT INTO run_log (run_date, status) VALUES (:d, 'running') RETURNING id"),
            {"d": run_date},
        )
        return result.scalar()


def complete_run(run_id: int) -> None:
    with get_session() as s:
        s.execute(
            text("UPDATE run_log SET status='complete' WHERE id=:id"),
            {"id": run_id},
        )


def fail_run(run_id: int, error: str) -> None:
    with get_session() as s:
        s.execute(
            text("UPDATE run_log SET status='error', error_msg=:e WHERE id=:id"),
            {"id": run_id, "e": error},
        )


# ── Research cache ────────────────────────────────────────────────────────────

def get_cache(ticker: str, data_type: str) -> Optional[dict]:
    """Return cached data for ticker+data_type if not expired, else None."""
    now = datetime.now(tz=timezone.utc).isoformat()
    with get_session() as s:
        row = s.execute(
            text(
                "SELECT data_json FROM research_cache "
                "WHERE ticker=:t AND data_type=:dt AND expires_at > :now"
            ),
            {"t": ticker.upper(), "dt": data_type, "now": now},
        ).fetchone()
    if row:
        return json.loads(row[0])
    return None


def set_cache(ticker: str, data_type: str, data: dict, ttl_seconds: int) -> None:
    """Upsert data into research_cache with the given TTL."""
    from datetime import timedelta
    now = datetime.now(tz=timezone.utc)
    expires = (now + timedelta(seconds=ttl_seconds)).isoformat()
    with get_session() as s:
        s.execute(
            text(
                "INSERT INTO research_cache (ticker, data_type, data_json, fetched_at, expires_at) "
                "VALUES (:t, :dt, :data, :fetched, :expires) "
                "ON CONFLICT(ticker, data_type) DO UPDATE SET "
                "data_json=excluded.data_json, fetched_at=excluded.fetched_at, expires_at=excluded.expires_at"
            ),
            {
                "t": ticker.upper(),
                "dt": data_type,
                "data": json.dumps(data, default=str),
                "fetched": now.isoformat(),
                "expires": expires,
            },
        )


# ── Reddit mentions ───────────────────────────────────────────────────────────

def save_reddit_mentions(run_date: str, mentions: list) -> None:
    with get_session() as s:
        for row in mentions:
            s.execute(
                text(
                    "INSERT INTO reddit_mentions (run_date, ticker, mention_count, sentiment_words) "
                    "VALUES (:rd, :t, :mc, :sw) "
                    "ON CONFLICT(run_date, ticker) DO UPDATE SET "
                    "mention_count=excluded.mention_count, sentiment_words=excluded.sentiment_words"
                ),
                {
                    "rd": run_date,
                    "t": row["ticker"],
                    "mc": row.get("mentions", row.get("mention_count", 0)),
                    "sw": json.dumps(row.get("sentiment_words", [])),
                },
            )


# ── Daily results ─────────────────────────────────────────────────────────────

def save_daily_result(run_date: str, result: dict) -> None:
    with get_session() as s:
        s.execute(
            text(
                "INSERT INTO daily_results "
                "(run_date, ticker, composite_score, recommendation, score_news, score_buffett, "
                "score_thesis, score_critique, score_contracts, score_pnl, score_politicians, "
                "score_competitors, price_at_analysis, full_analysis_json) "
                "VALUES (:rd,:t,:cs,:rec,:sn,:sb,:st,:scr,:sco,:sp,:spol,:scomp,:price,:full) "
                "ON CONFLICT(run_date, ticker) DO UPDATE SET "
                "composite_score=excluded.composite_score, recommendation=excluded.recommendation, "
                "full_analysis_json=excluded.full_analysis_json"
            ),
            {
                "rd": run_date,
                "t": result.get("ticker"),
                "cs": result.get("composite_score"),
                "rec": result.get("recommendation"),
                "sn": result.get("score_news"),
                "sb": result.get("score_buffett"),
                "st": result.get("score_thesis"),
                "scr": result.get("score_critique"),
                "sco": result.get("score_contracts"),
                "sp": result.get("score_pnl"),
                "spol": result.get("score_politicians"),
                "scomp": result.get("score_competitors"),
                "price": result.get("price_at_analysis"),
                "full": json.dumps(result, default=str),
            },
        )


def get_daily_results(run_date: str) -> list:
    with get_session() as s:
        rows = s.execute(
            text("SELECT * FROM daily_results WHERE run_date=:rd ORDER BY composite_score DESC"),
            {"rd": run_date},
        ).mappings().fetchall()
    return [dict(r) for r in rows]


# ── Legacy helpers (kept for app/main.py compatibility) ──────────────────────

def save_mentions(run_id: int, mentions: list) -> None:
    with get_session() as s:
        for row in mentions:
            s.execute(
                text(
                    "INSERT INTO ticker_mentions (run_id, ticker, mentions, subreddits_seen, last_seen_utc) "
                    "VALUES (:run_id, :ticker, :mentions, :subs, :ts)"
                ),
                {
                    "run_id": run_id,
                    "ticker": row["ticker"],
                    "mentions": row["mentions"],
                    "subs": row.get("subreddits_seen"),
                    "ts": row.get("last_seen_utc"),
                },
            )


def save_analysis(run_id: int, analyses: list) -> None:
    with get_session() as s:
        for a in analyses:
            s.execute(
                text(
                    "INSERT INTO ticker_analysis "
                    "(run_id, ticker, company_name, overall_score, recommendation, thesis, "
                    "bull_case, bear_case, key_risks, catalysts, price_target_rationale, "
                    "price_change_30d_pct, input_tokens, output_tokens, error) "
                    "VALUES (:run_id,:ticker,:company,:score,:rec,:thesis,:bull,:bear,"
                    ":risks,:cats,:pt,:pct,:it,:ot,:err)"
                ),
                {
                    "run_id": run_id,
                    "ticker": a.get("ticker"),
                    "company": a.get("company_name"),
                    "score": a.get("overall_score"),
                    "rec": a.get("recommendation"),
                    "thesis": a.get("thesis"),
                    "bull": a.get("bull_case"),
                    "bear": a.get("bear_case"),
                    "risks": json.dumps(a.get("key_risks", [])),
                    "cats": json.dumps(a.get("catalysts", [])),
                    "pt": a.get("price_target_rationale"),
                    "pct": a.get("price_change_30d_pct"),
                    "it": a.get("input_tokens"),
                    "ot": a.get("output_tokens"),
                    "err": a.get("error"),
                },
            )


def save_final_picks(run_id: int, picks: list) -> None:
    with get_session() as s:
        for rank, pick in enumerate(picks, start=1):
            s.execute(
                text(
                    "INSERT INTO final_picks (run_id, ticker, rank, score) "
                    "VALUES (:run_id, :ticker, :rank, :score)"
                ),
                {"run_id": run_id, "ticker": pick["ticker"], "rank": rank, "score": pick.get("overall_score", 0)},
            )


def get_latest_analyses(limit: int = 100) -> list:
    with get_session() as s:
        rows = s.execute(
            text(
                "SELECT a.* FROM ticker_analysis a "
                "JOIN run_log r ON r.id = a.run_id "
                "WHERE r.status = 'complete' "
                "ORDER BY a.created_at DESC LIMIT :lim"
            ),
            {"lim": limit},
        ).mappings().fetchall()
    return [dict(r) for r in rows]


def get_run_history(limit: int = 20) -> list:
    with get_session() as s:
        rows = s.execute(
            text("SELECT * FROM run_log ORDER BY created_at DESC LIMIT :lim"),
            {"lim": limit},
        ).mappings().fetchall()
    return [dict(r) for r in rows]
