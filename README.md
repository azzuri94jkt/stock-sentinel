# Stock Sentinel 📈

An automated daily stock research pipeline that scrapes Reddit for ticker mentions, filters and analyses them with Claude AI, and delivers scored reports via a Streamlit dashboard and Excel workbook.

## What it does

Every weekday the pipeline:
1. Scrapes 5 finance subreddits (no credentials — public JSON API) for ticker mentions in the last 24h
2. Pre-filters tickers with Claude Haiku (concurrent, fails open)
3. Fetches fundamentals via yfinance and headlines via NewsAPI (DB-cached)
4. Runs an 8-parameter deep analysis with Claude Sonnet
5. Scores each stock 0–10 and generates a colour-coded Excel report
6. Serves results on a password-protected Streamlit dashboard

## Scoring model

| Parameter | Weight |
|---|---|
| Buffett Value | 20% |
| News Sentiment | 15% |
| Geopolitical Thesis | 15% |
| P&L Trend | 15% |
| Self-Critique | 10% |
| Govt Contracts | 10% |
| Politician Trades | 10% |
| Competitor Analysis | 5% |

Score ≥ 7 → **Buy** · 4–6.9 → **Hold** · < 4 → **Avoid**

Composite score is always recomputed locally from sub-scores — model arithmetic is never trusted.

---

## Architecture

```
Reddit (public JSON API)
  └─ ingest/reddit_scraper.py       # scrapes last 24h posts + top-10 comments
       └─ data/reddit_raw.json

research/haiku_filter.py            # concurrent asyncio, claude-haiku-4-5-20251001
research/financial_data.py          # yfinance + NewsAPI, DB TTL cache
research/claude_analyst.py          # claude-sonnet-4-6, 8-parameter scoring
reports/excel_generator.py          # openpyxl workbook
app/main.py                         # Streamlit dashboard (auth + 2 pages)
```

Cache TTLs in `research_cache` DB table: **23h** fundamentals · **2h** news · **20h** analysis

---

## Local setup

```bash
# 1. Clone and install
git clone https://github.com/azzuri94jkt/stock-sentinel.git
cd stock-sentinel
pip install -r requirements.txt

# 2. Set environment variables
cp .env.example .env   # fill in ANTHROPIC_API_KEY and NEWS_API_KEY

# 3. Initialise the database
python3 -c "from db.database import init_db; init_db()"

# 4. Generate default auth config
python3 setup_config.py

# 5. Launch the dashboard
python3 -m streamlit run app/main.py
```

Open [http://localhost:8501](http://localhost:8501) — default password for all accounts: `sentinel2026`

To add or change a password:
```bash
python3 -c "import bcrypt; print(bcrypt.hashpw(b'newpassword', bcrypt.gensalt(12)).decode())"
```
Then update the hash in `config.yaml`.

---

## Running the pipeline

```bash
# Full run: scrape → filter → analyse → report
python3 pipeline/run_pipeline.py

# Dry run: Reddit scrape only, no AI calls
python3 pipeline/run_pipeline.py --dry-run

# Skip scrape, analyse specific tickers
python3 pipeline/run_pipeline.py --tickers NVDA TSLA AMD

# Run tests
python3 -m pytest tests/ -v
```

---

## Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | — | Haiku + Sonnet |
| `NEWS_API_KEY` | Yes | — | NewsAPI headlines |
| `MIN_MENTION_THRESHOLD` | No | `8` | Min Reddit mentions to include a ticker |
| `MAX_TICKERS_TO_RESEARCH` | No | `20` | Cap on Sonnet calls per run |
| `TOP_N_FINAL` | No | `5` | Tickers shown in dashboard |
| `DATABASE_URL` | No | `sqlite:///stock_sentinel.db` | Override for PostgreSQL |

---

## Deployment

### Render (dashboard + scheduler)

`render.yaml` is included. Connect the repo in Render and it auto-configures:
- **Web service** — Streamlit dashboard on `$PORT`
- **Worker** — `run_scheduler.py` fires the pipeline weekdays at 21:00 UTC

Add `ANTHROPIC_API_KEY` and `NEWS_API_KEY` as secret env vars in the Render dashboard.

### Railway (pipeline cron)

`railway.toml` is included. The pipeline runs as a cron job weekdays at **20:00 UTC** (`0 20 * * 1-5`).

```bash
railway up
```

---

## Cost estimates

| Step | Model | ~Cost per run |
|---|---|---|
| Haiku filter (50 tickers) | claude-haiku-4-5-20251001 | ~$0.003 |
| Sonnet analysis (20 tickers) | claude-sonnet-4-6 | ~$0.15 |
| **Total** | | **~$0.15 / run** |

Prompt caching on the Sonnet system prompt cuts repeat costs by ~90%.

---

## License

MIT
