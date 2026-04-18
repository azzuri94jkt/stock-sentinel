"""Pre-filter tickers with Claude Haiku before expensive Sonnet research.

All Haiku calls run concurrently via asyncio. Fails open — if a call errors,
the ticker is passed through so it isn't silently dropped.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import anthropic
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")

_MODEL      = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 150
_SYSTEM     = "You are a strict financial data viability checker. Respond only in valid JSON."

_USER_TMPL = """\
Ticker: {ticker}
Assess this ticker on 3 criteria and return JSON only, no other text:
{{
  "is_real_company": true/false,
  "has_sufficient_data": true/false,
  "is_meme_or_pump": true/false,
  "pass": true/false,
  "reason": "one sentence"
}}"""


def _make_client() -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


async def _check_ticker(
    client: anthropic.AsyncAnthropic,
    ticker: str,
) -> dict:
    """Run one Haiku call for a single ticker. Fails open on any error."""
    try:
        response = await client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": _USER_TMPL.format(ticker=ticker),
                }
            ],
        )
        raw = response.content[0].text.strip()
        # Strip markdown fences if model adds them despite the instruction
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw)
        result["ticker"] = ticker
        return result
    except Exception as exc:
        log.warning("Haiku call failed for %s (%s) — defaulting to pass=true", ticker, exc)
        return {
            "ticker":             ticker,
            "is_real_company":    None,
            "has_sufficient_data": None,
            "is_meme_or_pump":    None,
            "pass":               True,
            "reason":             f"Haiku call failed: {exc}",
        }


async def _run_all(tickers: list[str]) -> list[dict]:
    client = _make_client()
    tasks  = [_check_ticker(client, t) for t in tickers]
    return await asyncio.gather(*tasks)


def filter_tickers(
    tickers_with_counts: list[dict],
    save_path: Optional[str] = None,
) -> tuple:
    """Run Haiku pre-filter concurrently over all tickers.

    Args:
        tickers_with_counts: rows from reddit_scraper — each must have 'ticker'.
        save_path: optional override for results JSON path.

    Returns:
        (passed_tickers, filtered_tickers) — lists of original dicts, enriched
        with Haiku assessment fields.
    """
    tickers = [r["ticker"] for r in tickers_with_counts]
    if not tickers:
        return [], []

    log.info("Running Haiku filter on %d ticker(s) concurrently…", len(tickers))

    results = asyncio.run(_run_all(tickers))

    # Map ticker → assessment for merge
    assessment_map = {r["ticker"]: r for r in results}

    passed_tickers   = []
    filtered_tickers = []

    for row in tickers_with_counts:
        t = row["ticker"]
        assessment = assessment_map.get(t, {"pass": True, "reason": "no assessment"})
        enriched = {**row, **assessment}

        if assessment.get("pass", True):
            passed_tickers.append(enriched)
        else:
            filtered_tickers.append(enriched)
            log.info(
                "FILTERED  %s — %s (meme=%s, real=%s, data=%s)",
                t,
                assessment.get("reason", ""),
                assessment.get("is_meme_or_pump"),
                assessment.get("is_real_company"),
                assessment.get("has_sufficient_data"),
            )

    log.info(
        "Haiku filter complete: %d passed, %d filtered out",
        len(passed_tickers),
        len(filtered_tickers),
    )

    _save_results(passed_tickers, filtered_tickers, save_path)
    return passed_tickers, filtered_tickers


def _save_results(
    passed: list[dict],
    filtered: list[dict],
    path: Optional[str],
) -> None:
    if path is None:
        path = os.path.join(
            os.path.dirname(__file__), "..", "data", "haiku_filter_results.json"
        )
    path = os.path.abspath(path)
    Path(path).parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "generated_at":   datetime.now(tz=timezone.utc).isoformat(),
        "passed_count":   len(passed),
        "filtered_count": len(filtered),
        "passed_tickers":   passed,
        "filtered_tickers": filtered,
    }
    Path(path).write_text(json.dumps(payload, indent=2, default=str))
    log.info("Filter results saved → %s", path)


if __name__ == "__main__":
    # Quick smoke-test against the reddit_raw.json produced by the scraper
    _data_path = os.path.join(os.path.dirname(__file__), "..", "data", "reddit_raw.json")
    with open(_data_path) as f:
        mentions = json.load(f)

    passed, filtered = filter_tickers(mentions)

    print(f"\n{'='*50}")
    print(f"PASSED  ({len(passed)})")
    print(f"{'='*50}")
    for t in passed:
        print(f"  {t['ticker']:<8}  mentions={t.get('mentions','-'):<4}  {t.get('reason','')}")

    print(f"\n{'='*50}")
    print(f"FILTERED OUT  ({len(filtered)})")
    print(f"{'='*50}")
    for t in filtered:
        print(f"  {t['ticker']:<8}  {t.get('reason','')}")
