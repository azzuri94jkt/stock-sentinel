"""Core research engine: 8-parameter stock analysis via Claude Sonnet."""

import json
import logging
import os
from datetime import date, datetime, timezone
from typing import Optional

import anthropic
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")

_MODEL      = "claude-sonnet-4-6"
_MAX_TOKENS = 1200

# Scoring weights — must sum to 1.0
_WEIGHTS = {
    "news_sentiment":      0.15,
    "buffett_value":       0.20,
    "geopolitical_thesis": 0.15,
    "self_critique":       0.10,
    "govt_contracts":      0.10,
    "pnl_trend":           0.15,
    "politician_trades":   0.10,
    "competitor_analysis": 0.05,
}

_SYSTEM = (
    "You are a critical, evidence-based financial analyst. You do not hype stocks.\n"
    "You must be skeptical and identify risks as readily as opportunities.\n"
    "Respond ONLY with valid JSON. No preamble, no explanation outside the JSON."
)

_USER_TMPL = """\
Analyse {ticker} across 8 parameters. Return ONLY this JSON structure:

Financial data: {financial_data_summary}
Recent news: {news_headlines}
Reddit context: {reddit_context}

Return:
{{
  "ticker": "{ticker}",
  "company_name": "",
  "scores": {{
    "news_sentiment": {{"score": 0, "reasoning": "2 sentences max"}},
    "buffett_value": {{"score": 0, "reasoning": "2 sentences max",
                      "pe_assessment": "", "pb_assessment": "",
                      "fcf_assessment": "", "debt_assessment": ""}},
    "geopolitical_thesis": {{"score": 0, "thesis": "3 sentences max"}},
    "self_critique": {{"score": 0, "critique": "2 sentences max"}},
    "govt_contracts": {{"score": 0, "reasoning": "1 sentence"}},
    "pnl_trend": {{"score": 0, "reasoning": "2 sentences max",
                  "revenue_trend": "growing/flat/declining",
                  "margin_trend": "expanding/flat/contracting"}},
    "politician_trades": {{"score": 0, "reasoning": "1 sentence"}},
    "competitor_analysis": {{"score": 0, "reasoning": "2 sentences max",
                             "main_competitors": []}}
  }},
  "composite_score": 0,
  "recommendation": "Buy/Hold/Avoid",
  "one_line_summary": "1 sentence"
}}"""

_RETRY_SUFFIX = (
    "\n\nYour previous response could not be parsed as JSON. "
    "Return ONLY the raw JSON object. No markdown fences, no commentary."
)

_client: Optional[anthropic.Anthropic] = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


# ── Prompt builders ───────────────────────────────────────────────────────────

def _summarise_financials(fd: dict) -> str:
    """Flatten financial_data dict into a compact string for the prompt."""
    def _fmt(v, prefix="", suffix=""):
        if v is None:
            return "N/A"
        try:
            f = float(v)
            if abs(f) >= 1e9:
                return f"{prefix}{f/1e9:.1f}B{suffix}"
            if abs(f) >= 1e6:
                return f"{prefix}{f/1e6:.1f}M{suffix}"
            return f"{prefix}{f:.2f}{suffix}"
        except (TypeError, ValueError):
            return str(v)

    parts = [
        f"Price={_fmt(fd.get('current_price'), '$')}",
        f"MarketCap={_fmt(fd.get('market_cap'), '$')}",
        f"PE={_fmt(fd.get('pe_ratio'))}",
        f"PB={_fmt(fd.get('pb_ratio'))}",
        f"D/E={_fmt(fd.get('debt_to_equity'))}",
        f"FCF={_fmt(fd.get('free_cash_flow'), '$')}",
        f"RevTTM={_fmt(fd.get('revenue_ttm'), '$')}",
        f"NetIncomeTTM={_fmt(fd.get('net_income_ttm'), '$')}",
        f"EPS_growth={_fmt(fd.get('earnings_growth_yoy'), suffix='%')}",
        f"52wHigh={_fmt(fd.get('week_52_high'), '$')}",
        f"52wLow={_fmt(fd.get('week_52_low'), '$')}",
        f"Analyst={fd.get('analyst_consensus', 'N/A')}",
        f"30dChange={_fmt(fd.get('price_change_30d_pct'), suffix='%')}",
        f"Sector={fd.get('sector', 'N/A')}",
    ]

    rev_q = fd.get("revenue_quarterly", [])
    if rev_q:
        rev_str = " | ".join(
            f"{r['period']}: {_fmt(r['value'], '$')}" for r in rev_q[:4]
        )
        parts.append(f"RevQuarterly=[{rev_str}]")

    ni_q = fd.get("net_income_quarterly", [])
    if ni_q:
        ni_str = " | ".join(
            f"{r['period']}: {_fmt(r['value'], '$')}" for r in ni_q[:4]
        )
        parts.append(f"NIQuarterly=[{ni_str}]")

    return "  ".join(parts)


def _summarise_news(news: list) -> str:
    if not news:
        return "No recent news available."
    lines = []
    for a in news[:10]:
        pub  = (a.get("published_at") or "")[:10]
        src  = a.get("source") or "?"
        title = a.get("title") or ""
        lines.append(f"[{pub}] {src}: {title}")
    return "\n".join(lines)


def _build_user_prompt(
    ticker: str,
    financial_data: dict,
    reddit_context: dict,
    retry: bool = False,
) -> str:
    fd_summary = _summarise_financials(financial_data)
    news_summary = _summarise_news(financial_data.get("news", []))

    mentions   = reddit_context.get("mentions", 0)
    subreddits = reddit_context.get("subreddits_seen", "N/A")
    reddit_str = f"Reddit mentions (24h): {mentions} across [{subreddits}]"

    prompt = _USER_TMPL.format(
        ticker=ticker,
        financial_data_summary=fd_summary,
        news_headlines=news_summary,
        reddit_context=reddit_str,
    )
    return prompt + _RETRY_SUFFIX if retry else prompt


# ── JSON parsing ──────────────────────────────────────────────────────────────

def _parse_json(raw: str) -> dict:
    """Strip optional markdown fences and parse JSON."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # drop opening fence (```json or ```) and closing fence
        inner = "\n".join(
            l for l in lines[1:]
            if not l.strip().startswith("```")
        )
        text = inner.strip()
    return json.loads(text)


# ── Composite score calculation ───────────────────────────────────────────────

def _compute_composite(scores: dict) -> float:
    """Recompute composite from raw sub-scores using defined weights."""
    total = 0.0
    for key, weight in _WEIGHTS.items():
        sub = scores.get(key, {})
        total += float(sub.get("score", 0)) * weight
    return round(total, 2)


# ── Core API call ─────────────────────────────────────────────────────────────

def _call_claude(user_prompt: str, max_tokens: int = _MAX_TOKENS) -> tuple:
    """Send one request to Claude. Returns (parsed_dict, usage)."""
    client = _get_client()
    response = client.messages.create(
        model=_MODEL,
        max_tokens=max_tokens,
        system=[
            {
                "type": "text",
                "text": _SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_prompt}],
    )
    raw = response.content[0].text
    usage = {
        "input_tokens":        response.usage.input_tokens,
        "output_tokens":       response.usage.output_tokens,
        "cache_read_tokens":   getattr(response.usage, "cache_read_input_tokens", 0),
        "cache_write_tokens":  getattr(response.usage, "cache_creation_input_tokens", 0),
    }
    return _parse_json(raw), usage


# ── Public API ────────────────────────────────────────────────────────────────

def analyse_stock(
    ticker: str,
    financial_data: dict,
    reddit_context: dict,
    cached_analysis: Optional[dict] = None,
) -> dict:
    """Run 8-parameter analysis for one ticker.

    Caching logic:
    - If cached_analysis exists and was generated today, only re-score
      news_sentiment (param 1) using the fresh headlines; return cached
      scores for params 2–8.
    - Otherwise run the full prompt.

    Returns the analysis dict enriched with token usage and generated_at.
    """
    ticker = ticker.upper()
    today  = date.today().isoformat()

    # ── Partial cache path: today's analysis already exists ──────────────────
    if cached_analysis and cached_analysis.get("generated_at", "")[:10] == today:
        log.info("PARTIAL CACHE  %s — refreshing news_sentiment only", ticker)
        news_prompt = (
            f"Score ONLY the news_sentiment parameter (0-10) for {ticker}.\n"
            f"Recent headlines:\n{_summarise_news(financial_data.get('news', []))}\n\n"
            "Return ONLY: {\"score\": <int>, \"reasoning\": \"<2 sentences>\"}"
        )
        client = _get_client()
        try:
            resp = client.messages.create(
                model=_MODEL,
                max_tokens=150,
                system=_SYSTEM,
                messages=[{"role": "user", "content": news_prompt}],
            )
            news_score = _parse_json(resp.content[0].text)
            result = dict(cached_analysis)
            result["scores"]["news_sentiment"] = news_score
            result["composite_score"] = _compute_composite(result["scores"])
            result["generated_at"]    = datetime.now(tz=timezone.utc).isoformat()
            result["cache_path"]      = "partial_refresh"
            usage = {
                "input_tokens":  resp.usage.input_tokens,
                "output_tokens": resp.usage.output_tokens,
            }
            log.info(
                "Token usage  %s  in=%d  out=%d  (partial refresh)",
                ticker, usage["input_tokens"], usage["output_tokens"],
            )
            result["token_usage"] = usage
            return result
        except Exception as exc:
            log.warning("Partial refresh failed for %s (%s) — falling through to full call", ticker, exc)

    # ── Full analysis path ────────────────────────────────────────────────────
    log.info("FULL ANALYSIS  %s", ticker)
    user_prompt = _build_user_prompt(ticker, financial_data, reddit_context)

    try:
        result, usage = _call_claude(user_prompt)
    except (json.JSONDecodeError, ValueError) as exc:
        log.warning("JSON parse failed for %s (%s) — retrying with strict prompt + max_tokens=1400", ticker, exc)
        retry_prompt = _build_user_prompt(ticker, financial_data, reddit_context, retry=True)
        result, usage = _call_claude(retry_prompt, max_tokens=1400)

    # Recompute composite from sub-scores using our weights (don't trust model's arithmetic)
    if "scores" in result:
        result["composite_score"] = _compute_composite(result["scores"])

    result["generated_at"] = datetime.now(tz=timezone.utc).isoformat()
    result["cache_path"]   = "full"

    log.info(
        "Token usage  %s  in=%d  out=%d  cache_read=%d  cache_write=%d",
        ticker,
        usage["input_tokens"],
        usage["output_tokens"],
        usage.get("cache_read_tokens", 0),
        usage.get("cache_write_tokens", 0),
    )
    result["token_usage"] = usage
    return result


def analyse_tickers(
    tickers_with_context: list,
    max_tickers: Optional[int] = None,
) -> list:
    """Analyse a list of tickers sequentially.

    Each item in tickers_with_context must have at minimum a 'ticker' key.
    Financial data is fetched (with caching) inside this function.
    Returns list of analysis dicts sorted by composite_score descending.
    """
    from research.financial_data import fetch_financial_data
    from db.database import get_cache

    if max_tickers is None:
        max_tickers = int(os.getenv("MAX_TICKERS_TO_RESEARCH", 20))

    results = []
    for row in tickers_with_context[:max_tickers]:
        ticker = row["ticker"]
        try:
            financial_data  = fetch_financial_data(ticker)
            reddit_context  = {
                "mentions":        row.get("mentions", 0),
                "subreddits_seen": row.get("subreddits_seen", ""),
            }
            # Check DB for a prior full analysis to enable partial caching
            cached_raw = get_cache(ticker, "analysis")

            analysis = analyse_stock(
                ticker=ticker,
                financial_data=financial_data,
                reddit_context=reddit_context,
                cached_analysis=cached_raw,
            )

            # Persist analysis to DB cache (TTL: rest of today = 20h)
            from db.database import set_cache
            set_cache(ticker, "analysis", analysis, ttl_seconds=20 * 3600)

            results.append(analysis)
        except Exception as exc:
            log.error("Analysis failed for %s: %s", ticker, exc)
            results.append({
                "ticker": ticker,
                "error":  str(exc),
                "composite_score": 0,
                "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            })

    return sorted(results, key=lambda x: x.get("composite_score", 0), reverse=True)
