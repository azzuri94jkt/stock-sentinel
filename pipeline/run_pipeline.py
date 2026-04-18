"""
Master daily pipeline — orchestrates the full Stock Sentinel run.

Steps
-----
1. Reddit scrape      → data/reddit_raw.json + reddit_mentions DB table
2. Haiku pre-filter   → data/haiku_filter_results.json
3. Financial data     → research_cache DB table (TTL-backed)
4. Claude analysis    → research_cache + daily_results DB tables
5. Excel report       → data/reports/YYYY-MM-DD_stock_sentinel.xlsx
6. Run log            → run_log DB table marked complete / error

Usage
-----
    python pipeline/run_pipeline.py                  # normal run
    python pipeline/run_pipeline.py --dry-run        # stop after Reddit scrape
    python pipeline/run_pipeline.py --tickers NVDA TSLA AMD  # override tickers
"""

import argparse
import logging
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

# Ensure project root is on path when run directly
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("pipeline")

# ── Step helpers ──────────────────────────────────────────────────────────────

def step_scrape(run_date: str) -> list:
    """Step 1 — Reddit scraper. Returns list of mention dicts."""
    log.info("STEP 1 ▶ Reddit scrape")
    t0 = time.time()

    from ingest.reddit_scraper import scrape_mentions, save_to_json
    df = scrape_mentions()
    mentions = df.to_dict(orient="records")

    raw_path = Path(__file__).parent.parent / "data" / "reddit_raw.json"
    save_to_json(df, str(raw_path))

    log.info("  %d ticker(s) above threshold — saved to %s  (%.1fs)", len(mentions), raw_path, time.time() - t0)
    return mentions


def step_save_reddit_mentions(run_date: str, mentions: list) -> None:
    """Persist mention counts to reddit_mentions DB table."""
    from db.database import save_reddit_mentions
    save_reddit_mentions(run_date, mentions)
    log.info("  Reddit mentions saved to DB (%d rows)", len(mentions))


def step_haiku_filter(mentions: list) -> tuple:
    """Step 2 — Haiku pre-filter. Returns (passed, filtered)."""
    log.info("STEP 2 ▶ Haiku pre-filter")
    t0 = time.time()

    from research.haiku_filter import filter_tickers
    passed, filtered = filter_tickers(mentions)

    log.info(
        "  %d passed / %d filtered  (%.1fs)",
        len(passed), len(filtered), time.time() - t0,
    )
    return passed, filtered


def step_analyse(passed: list, run_date: str) -> list:
    """Steps 3 & 4 — fetch financial data + Claude analysis."""
    log.info("STEP 3+4 ▶ Financial data fetch + Claude analysis")
    t0 = time.time()

    from research.claude_analyst import analyse_tickers
    analyses = analyse_tickers(passed)

    total_in  = sum(a.get("token_usage", {}).get("input_tokens", 0)  for a in analyses if not a.get("error"))
    total_out = sum(a.get("token_usage", {}).get("output_tokens", 0) for a in analyses if not a.get("error"))
    errors    = [a["ticker"] for a in analyses if a.get("error")]

    log.info(
        "  %d analysed  |  tokens in=%d out=%d  |  errors=%s  (%.1fs)",
        len(analyses), total_in, total_out, errors or "none", time.time() - t0,
    )
    return analyses


def step_save_daily_results(run_date: str, analyses: list, top_n: int) -> list:
    """Persist top-N analyses to daily_results and final_picks DB tables."""
    from db.database import save_daily_result, save_final_picks

    valid = sorted(
        [a for a in analyses if not a.get("error")],
        key=lambda x: float(x.get("composite_score") or 0),
        reverse=True,
    )
    picks = valid[:top_n]

    for a in valid:
        a_with_date = {**a, "run_date": run_date}
        save_daily_result(run_date, a_with_date)

    # Adapt to legacy final_picks schema
    picks_legacy = [
        {**p, "overall_score": int(float(p.get("composite_score") or 0) * 10)}
        for p in picks
    ]
    save_final_picks(0, picks_legacy)   # run_id=0 when called outside run_log context

    log.info("  %d results saved to daily_results  |  top %d saved to final_picks", len(valid), len(picks))
    return picks


def step_excel(analyses: list, mentions: list, run_date: str) -> Path:
    """Step 5 — generate Excel workbook."""
    log.info("STEP 5 ▶ Excel report")
    t0 = time.time()

    from reports.excel_generator import generate_report
    path = generate_report(analyses, reddit_rows=mentions, report_date=run_date)

    log.info("  Report saved to %s  (%.1fs)", path, time.time() - t0)
    return path


# ── Main orchestrator ─────────────────────────────────────────────────────────

def run(dry_run: bool = False, override_tickers: list = None) -> dict:
    """Execute the full pipeline. Returns a summary dict."""
    run_date = date.today().isoformat()
    top_n    = int(os.getenv("TOP_N_FINAL", 5))
    pipeline_start = time.time()

    log.info("=" * 60)
    log.info("Stock Sentinel pipeline starting — %s", run_date)
    log.info("=" * 60)

    # Init DB and create run record
    from db.database import init_db, create_run, complete_run, fail_run, save_mentions
    init_db()
    run_id = create_run(run_date)
    log.info("Run ID: %d", run_id)

    summary = {
        "run_id":     run_id,
        "run_date":   run_date,
        "status":     "error",
        "mentions":   0,
        "passed":     0,
        "analysed":   0,
        "report":     None,
        "errors":     [],
    }

    try:
        # ── Step 1: Reddit scrape ─────────────────────────────────────────────
        if override_tickers:
            log.info("STEP 1 ▶ Skipped — using override tickers: %s", override_tickers)
            mentions = [{"ticker": t, "mentions": 0, "subreddits_seen": "manual"} for t in override_tickers]
        else:
            mentions = step_scrape(run_date)

        summary["mentions"] = len(mentions)
        step_save_reddit_mentions(run_date, mentions)

        # Legacy ticker_mentions table
        save_mentions(run_id, [
            {**m, "subreddits_seen": m.get("subreddits_seen", ""), "last_seen_utc": ""}
            for m in mentions
        ])

        if dry_run:
            log.info("Dry run — stopping after scrape.")
            complete_run(run_id)
            summary["status"] = "dry_run"
            return summary

        # ── Step 2: Haiku filter ──────────────────────────────────────────────
        passed, filtered = step_haiku_filter(mentions)
        summary["passed"] = len(passed)

        if not passed:
            log.warning("No tickers passed the Haiku filter — aborting.")
            complete_run(run_id)
            summary["status"] = "no_tickers"
            return summary

        # ── Steps 3+4: Financial data + Claude analysis ───────────────────────
        analyses = step_analyse(passed, run_date)
        summary["analysed"] = len([a for a in analyses if not a.get("error")])
        summary["errors"]   = [a["ticker"] for a in analyses if a.get("error")]

        # ── Save to DB ────────────────────────────────────────────────────────
        step_save_daily_results(run_date, analyses, top_n)

        # ── Step 5: Excel report ──────────────────────────────────────────────
        report_path = step_excel(analyses, mentions, run_date)
        summary["report"] = str(report_path)

        complete_run(run_id)
        summary["status"] = "complete"

        elapsed = time.time() - pipeline_start
        log.info("=" * 60)
        log.info(
            "Pipeline complete in %.1fs  |  %d analysed  |  report: %s",
            elapsed, summary["analysed"], report_path.name,
        )
        log.info("=" * 60)

    except Exception as exc:
        log.exception("Pipeline failed: %s", exc)
        fail_run(run_id, str(exc))
        summary["errors"].append(str(exc))

    return summary


# ── CLI entry point ───────────────────────────────────────────────────────────

def _parse_args():
    p = argparse.ArgumentParser(description="Stock Sentinel daily pipeline")
    p.add_argument("--dry-run",  action="store_true", help="Stop after Reddit scrape")
    p.add_argument("--tickers",  nargs="+", metavar="TICKER", help="Override tickers (skip scrape)")
    return p.parse_args()


if __name__ == "__main__":
    args   = _parse_args()
    result = run(dry_run=args.dry_run, override_tickers=args.tickers)

    print("\nPipeline summary:")
    for k, v in result.items():
        print(f"  {k:<12} {v}")

    sys.exit(0 if result["status"] in ("complete", "dry_run") else 1)
