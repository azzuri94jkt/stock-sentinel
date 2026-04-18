# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the full daily pipeline (scrape → filter → analyse → report)
python3 pipeline/run_pipeline.py

# Stop after Reddit scrape only
python3 pipeline/run_pipeline.py --dry-run

# Skip scrape, run analysis on specific tickers
python3 pipeline/run_pipeline.py --tickers NVDA TSLA AMD

# Launch the Streamlit dashboard
python3 -m streamlit run app/main.py

# Launch the test/debug UI
python3 -m streamlit run app/test_ui.py

# Run tests
python3 -m pytest tests/ -v

# Run a single test file
python3 -m pytest tests/test_ticker_extractor.py -v

# Initialise (or re-initialise) the database
python3 -c "from db.database import init_db; init_db()"

# Generate config.yaml with default users if missing
python3 setup_config.py

# Start the scheduler (fires pipeline weekdays at 21:00 UTC / 07:00 AEST)
python3 run_scheduler.py
```

## Pipeline architecture

The system runs as a sequential daily pipeline. The canonical entry point is `pipeline/run_pipeline.py`:

```
Reddit (public JSON API)
  └─ ingest/reddit_scraper.py       # scrapes last 24h posts + top-10 comments per sub
       └─ data/reddit_raw.json      # intermediate file output
       └─ DB: reddit_mentions

  ↓ list of {ticker, mentions, subreddits_seen}

research/haiku_filter.py            # concurrent asyncio calls to claude-haiku-4-5-20251001
  └─ data/haiku_filter_results.json # intermediate file output
  └─ fails open: API errors → pass=true (ticker is NOT silently dropped)

  ↓ passed_tickers only

research/financial_data.py          # yfinance fundamentals + NewsAPI headlines
  └─ DB: research_cache             # TTL cache — 23h fundamentals, 2h news, 20h analysis

research/claude_analyst.py          # claude-sonnet-4-6, 8-parameter scoring
  └─ DB: research_cache (analysis)
  └─ DB: daily_results

reports/excel_generator.py          # openpyxl workbook, 1 summary sheet + 1 per ticker
  └─ data/reports/YYYY-MM-DD_stock_sentinel.xlsx
```

## Caching layers

There are two distinct cache systems — do not confuse them:

1. **`research_cache` DB table** (primary): keyed on `(ticker, data_type)`. `data_type` is one of `fundamentals`, `news`, or `analysis`. TTLs enforced via `expires_at` column. Read/write via `db/database.py → get_cache()` / `set_cache()`.

2. **`cache/cache_manager.py`** (file-based): uses `/tmp/stock_sentinel_cache/`. This is a legacy module — the DB cache is preferred for all new code.

**Partial analysis refresh**: if `research_cache` already contains an `analysis` entry for a ticker from today, `claude_analyst.analyse_stock()` re-scores only `news_sentiment` (one cheap Haiku call) and reuses the other 7 cached scores.

## Claude API usage

- **Haiku** (`claude-haiku-4-5-20251001`): pre-filter only. `max_tokens=150`. Async via `anthropic.AsyncAnthropic`. One call per ticker, all concurrent.
- **Sonnet** (`claude-sonnet-4-6`): full 8-parameter analysis. `max_tokens=1200` (first attempt), `max_tokens=1400` on JSON parse retry. System prompt is `cache_control: ephemeral` for prompt cache savings. Composite score is always recomputed locally from sub-scores using hardcoded weights — never trust the model's own arithmetic.

Scoring weights (must sum to 1.0):
`buffett_value=0.20, news_sentiment=0.15, geopolitical_thesis=0.15, pnl_trend=0.15, self_critique=0.10, govt_contracts=0.10, politician_trades=0.10, competitor_analysis=0.05`

## Database

SQLite by default (`stock_sentinel.db` in project root). Override with `DATABASE_URL` env var for PostgreSQL on Render/Railway.

Schema is in `db/schema.sql`. Call `init_db()` to create all tables — it is idempotent. Key tables:

- `daily_results` — one row per `(run_date, ticker)`, has `full_analysis_json` TEXT column containing the complete Claude response
- `research_cache` — TTL cache for fundamentals, news, and analysis blobs
- `reddit_mentions` — daily mention counts; drives the Tracking dashboard charts
- `run_log` — pipeline run bookkeeping (status: `running` / `complete` / `error`)
- `ticker_mentions`, `ticker_analysis`, `final_picks` — legacy tables, kept for backwards-compatibility

## Ticker extraction rules

`ingest/reddit_scraper.py` applies these rules to avoid English-word false positives:
- 1–2 char symbols: **require `$` prefix** (e.g. `$T`, `$AI`)
- 3–5 char symbols: accepted bare if in NASDAQ/NYSE ticker lists AND not in `STOPWORDS`
- Valid tickers loaded from `data/tickers/nasdaq.csv` and `data/tickers/nyse.csv` (~8,300 real tickers total)

## Authentication

`streamlit-authenticator 0.4.2`. Config loaded from `config.yaml` (gitignored). `setup_config.py` generates a default `config.yaml` if missing — called automatically on app startup and during the Render build step. Default credentials: all 5 users share password `sentinel2026`.

To hash a new password:
```bash
python3 -c "import bcrypt; print(bcrypt.hashpw(b'newpassword', bcrypt.gensalt(12)).decode())"
```

## Deployment

- **Render** (web dashboard): `render.yaml` — build runs `pip install -r requirements.txt && python setup_config.py`; start command is `streamlit run app/main.py --server.port $PORT --server.address 0.0.0.0`
- **Railway** (pipeline cron): `railway.toml` — `cronSchedule = "0 20 * * 1-5"` runs `python pipeline/run_pipeline.py` weekdays at 20:00 UTC
- **Local scheduler**: `run_scheduler.py` using the `schedule` library, fires at 21:00 UTC

## Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | — | Haiku + Sonnet calls |
| `NEWS_API_KEY` | Yes | — | NewsAPI headlines (48h window) |
| `MIN_MENTION_THRESHOLD` | No | `8` | Min Reddit mentions to include a ticker |
| `MAX_TICKERS_TO_RESEARCH` | No | `20` | Cap on Sonnet calls per run |
| `TOP_N_FINAL` | No | `5` | Tickers shown in dashboard + Excel summary |
| `DATABASE_URL` | No | `sqlite:///stock_sentinel.db` | SQLAlchemy DB URL |

## Python version note

The codebase targets Python 3.9 (macOS system Python). Use `Optional[X]` not `X | None`, and `list` / `dict` not `list[X]` / `dict[X, Y]` in function signatures, as the `X | Y` union syntax requires 3.10+.
