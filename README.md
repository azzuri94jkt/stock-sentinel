# Stock Sentinel 📈

An automated stock research pipeline that:
1. **Scrapes Reddit** (WSB, r/stocks, r/investing, etc.) for ticker mentions
2. **Pre-filters** candidates with Claude Haiku (fast, cheap)
3. **Deep-analyzes** top tickers with Claude Sonnet (fundamentals + news + price action)
4. **Stores results** in SQLite/PostgreSQL via SQLAlchemy
5. **Exports** a formatted Excel report
6. **Displays** results in a Streamlit dashboard with optional auth

---

## Architecture

```
Reddit → reddit_scraper.py
            ↓ (ticker mention counts)
         haiku_filter.py   ← Claude Haiku (fast pre-screen)
            ↓ (worth_researching=True tickers)
         financial_data.py ← yfinance + News API
            ↓ (fundamentals + price + headlines)
         claude_analyst.py ← Claude Sonnet (deep analysis, prompt-cached)
            ↓ (scored analyses)
         database.py       ← SQLite / PostgreSQL
         excel_generator.py ← .xlsx report
         Streamlit dashboard
```

---

## Local Setup

### 1. Clone and install

```bash
git clone <your-repo-url> stock-sentinel
cd stock-sentinel
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in:

| Variable | Where to get it |
|---|---|
| `REDDIT_CLIENT_ID` | https://www.reddit.com/prefs/apps → "create another app" |
| `REDDIT_CLIENT_SECRET` | Same page as above |
| `REDDIT_USER_AGENT` | Any string, e.g. `StockSentinel/1.0 by YourUsername` |
| `ANTHROPIC_API_KEY` | https://console.anthropic.com |
| `NEWS_API_KEY` | https://newsapi.org (free tier: 100 req/day) |

### 3. Initialize the database

```bash
python -c "from db.database import init_db; init_db()"
```

### 4. Run the pipeline manually

```python
# From project root
python -c "
from app.main import _run_pipeline
_run_pipeline()
"
```

### 5. Launch the dashboard

```bash
streamlit run app/main.py
```

Open http://localhost:8501

### 6. (Optional) Set up authentication

Create `auth_config.yaml` in the project root:

```yaml
credentials:
  usernames:
    admin:
      email: you@example.com
      name: Admin
      password: $2b$12$...   # bcrypt hash — generate with stauth.Hasher(['yourpassword']).generate()
cookie:
  expiry_days: 30
  key: some-secret-key-32-chars
  name: stock_sentinel_cookie
```

Generate a bcrypt hash:

```python
import streamlit_authenticator as stauth
print(stauth.Hasher(['yourpassword']).generate())
```

### 7. Run tests

```bash
pytest tests/ -v
```

---

## Scheduled Runs

To run the pipeline daily via cron (or a `schedule`-based process):

```python
# run_scheduler.py
import schedule
import time
from app.main import _run_pipeline

schedule.every().day.at("07:00").do(_run_pipeline)

while True:
    schedule.run_pending()
    time.sleep(60)
```

```bash
python run_scheduler.py &
```

---

## Deploying to Render

### Web Service (Streamlit dashboard)

1. Push your repo to GitHub.
2. In [Render](https://render.com), create a **New Web Service**.
3. Settings:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `streamlit run app/main.py --server.port $PORT --server.address 0.0.0.0`
   - **Environment:** Add all variables from `.env.example`
4. For persistent storage, add a **Render Disk** mounted at `/data` and set:
   ```
   DATABASE_URL=sqlite:////data/stock_sentinel.db
   ```

### Background Worker (pipeline scheduler)

Create a second Render service of type **Background Worker**:
- **Start Command:** `python run_scheduler.py`
- Same env vars as above.

### PostgreSQL on Render

1. Create a **Render PostgreSQL** instance.
2. Copy the **Internal Database URL** → set as `DATABASE_URL` in both services.
3. The schema uses standard SQL compatible with PostgreSQL (swap `AUTOINCREMENT` → `SERIAL` in `schema.sql` for Postgres).

---

## Deploying to Railway

### 1. Install Railway CLI

```bash
npm install -g @railway/cli
railway login
```

### 2. Initialize project

```bash
cd stock-sentinel
railway init
railway link   # link to existing project or create new
```

### 3. Add environment variables

```bash
railway variables set ANTHROPIC_API_KEY=sk-ant-...
railway variables set REDDIT_CLIENT_ID=...
railway variables set REDDIT_CLIENT_SECRET=...
railway variables set REDDIT_USER_AGENT="StockSentinel/1.0"
railway variables set NEWS_API_KEY=...
railway variables set MIN_MENTION_THRESHOLD=8
railway variables set MAX_TICKERS_TO_RESEARCH=20
railway variables set TOP_N_FINAL=5
```

### 4. Add a PostgreSQL plugin

In the Railway dashboard → your project → **New** → **Database** → **PostgreSQL**.
Railway automatically sets `DATABASE_URL` in your service environment.

### 5. Create `railway.toml`

```toml
[build]
builder = "nixpacks"

[deploy]
startCommand = "streamlit run app/main.py --server.port $PORT --server.address 0.0.0.0"
restartPolicyType = "on-failure"
restartPolicyMaxRetries = 3
```

### 6. Deploy

```bash
railway up
```

The dashboard URL appears in the Railway console under **Deployments**.

### 7. Add a cron job for the pipeline

In Railway → your project → **New** → **Cron Job**:
- **Schedule:** `0 7 * * 1-5` (weekdays at 7 AM UTC)
- **Command:** `python -c "from app.main import _run_pipeline; _run_pipeline()"`

---

## Project Structure

```
stock-sentinel/
├── ingest/
│   └── reddit_scraper.py      # PRAW-based scraper + ticker extractor
├── research/
│   ├── haiku_filter.py        # Claude Haiku fast pre-filter
│   ├── claude_analyst.py      # Claude Sonnet deep analysis (prompt-cached)
│   └── financial_data.py      # yfinance fundamentals + News API
├── reports/
│   └── excel_generator.py     # Styled .xlsx output
├── db/
│   ├── database.py            # SQLAlchemy session + CRUD helpers
│   └── schema.sql             # DDL for all tables
├── app/
│   ├── main.py                # Streamlit app + pipeline orchestrator
│   └── pages/
│       └── tracking.py        # Dashboard + tracking page components
├── cache/
│   └── cache_manager.py       # File-based TTL cache
├── tests/
│   ├── test_ticker_extractor.py
│   └── test_scoring.py
├── data/tickers/
│   ├── nasdaq.csv             # ~5,400 real NASDAQ tickers
│   └── nyse.csv               # ~2,900 real NYSE tickers
├── .env.example
├── requirements.txt
└── README.md
```

---

## Cost Estimates

| Step | Model | ~Cost per run |
|---|---|---|
| Haiku filter (50 tickers) | claude-haiku-4-5 | ~$0.003 |
| Sonnet analysis (20 tickers) | claude-sonnet-4-6 | ~$0.15 |
| **Total** | | **~$0.15/run** |

Prompt caching on the Sonnet system prompt reduces repeated costs by ~90% on subsequent runs.

---

## License

MIT
