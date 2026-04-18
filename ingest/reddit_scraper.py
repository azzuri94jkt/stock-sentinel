"""Scrape Reddit posts and comments via public JSON endpoints (no API key required)."""

import re
import os
import time
from collections import Counter
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

SUBREDDITS = [
    "wallstreetbets", "stocks", "investing",
    "options", "SecurityAnalysis",
]

POSTS_PER_SUB = 100
TOP_POSTS_FOR_COMMENTS = 10
_USER_AGENT = "Mozilla/5.0 (compatible; stock-sentinel/1.0)"
_REQUEST_DELAY = 1.5  # seconds between requests to respect rate limits

# Common false-positive words that look like tickers
STOPWORDS = {
    # Single / two-letter noise (moot for bare matches, but kept for $ matches)
    "A", "I", "AM", "AN", "AS", "AT", "BE", "BY", "DO", "GO", "HE", "IF",
    "IN", "IS", "IT", "ME", "MY", "NO", "OF", "OK", "ON", "OR", "SO", "TO",
    "UP", "US", "WE", "AI", "DD", "EV", "OP", "PE", "PM", "PR", "TV", "UK",
    # Three-letter common words
    "CEO", "CFO", "CTO", "IPO", "ETF", "GDP", "USD", "ALL", "FOR", "THE",
    "AND", "BUT", "NOT", "NOW", "GET", "GOT", "BUY", "SELL", "PUTS", "CALLS",
    "NEW", "OLD", "LOL", "IMO", "SEC", "FDA", "FED", "OTC", "ATH", "YOLO",
    "ITS", "TOP", "PUT", "ONE", "TWO", "BIG", "OWN", "FAR", "FEW", "HOW",
    "WHO", "WHY", "ANY", "HAD", "HAS", "DID", "AGO", "CAN", "PRE", "OUT",
    "WAY", "DTE", "TAX", "NET", "LOW", "LOT", "RUN", "HIT", "SAY", "MAN",
    "BIT", "SAW", "SET", "SIT", "LET", "TRY", "ADD", "END", "DAY", "MAX",
    "WIN", "MAP", "USE", "ACT", "AGE", "AIM", "AIR", "ARM", "ART", "ASK",
    "BAD", "BAG", "BAN", "BAR", "BED", "BOX", "CAR", "CAT", "CUT", "DOG",
    "DUE", "EAT", "EYE", "FIT", "FIX", "FLY", "FUN", "GAP", "GAS", "GUY",
    "HOT", "HUG", "JOB", "KEY", "LAW", "LAY", "LED", "LEG", "LIT", "MAD",
    "MIX", "MOB", "MOM", "MUD", "ODD", "PAY", "POP", "POT", "RAW", "RED",
    "ROW", "SIT", "SIX", "SKY", "SUM", "SUN", "TAB", "TAG", "TEN", "TIE",
    "TIP", "TON", "TOO", "TUB", "TUG", "TUX", "VAR", "VIA", "WAR", "WAS",
    "WEB", "WET", "YES", "YET",
    # Four-letter common words
    "YOU", "ARE", "HERE", "THAT", "WITH", "THIS", "THEY", "HAVE", "WILL",
    "BEEN", "ALSO", "INTO", "THAN", "MORE", "OVER", "SUCH", "REAL", "NEXT",
    "GOOD", "WELL", "PLAY", "MOVE", "LIVE", "CASH", "HOPE", "SEEM", "CARE",
    "BULL", "BEAR", "GAME", "PUMP", "DUMP", "SITE", "FUND", "FAST", "EASY",
    "HELP", "GROW", "GAIN", "COST", "EDIT", "OPEN", "POST", "LINE", "PLUS",
    "EVER", "LUCK", "TECH", "FACT", "HOLD", "LONG", "RISK", "CALL", "LOSS",
    "DROP", "RISE", "RATE", "TOOK", "FEEL", "SAID", "LOOK", "DOES", "JUST",
    "LIKE", "KNOW", "MAKE", "TAKE", "COME", "TIME", "YEAR", "WEEK", "SOME",
    "MOST", "MUCH", "EVEN", "BACK", "EACH", "LAST", "SAME", "GOES", "PUTS",
    "HIGH", "DOWN", "FROM", "WHEN", "WHAT", "THEN", "ONLY", "VERY", "BOTH",
    # Five-letter common words
    "COULD", "WOULD", "SHOULD", "THEIR", "ABOUT", "AFTER", "AGAIN", "BELOW",
    "EVERY", "FIRST", "GIVEN", "GOING", "GREAT", "MAYBE", "NEVER", "PRICE",
    "SINCE", "STILL", "STOCK", "THESE", "THINK", "TRADE", "UNDER", "UNTIL",
    "WHERE", "WHICH", "WHILE", "WORTH",
    # Common words that are also valid tickers — too noisy to use bare
    "AMP", "WWW", "ELSE", "LIFE", "BRO",
}


def _load_valid_tickers(data_dir: str = None) -> set[str]:
    if data_dir is None:
        data_dir = os.path.join(os.path.dirname(__file__), "..", "data", "tickers")

    tickers = set()
    for fname in ("nasdaq.csv", "nyse.csv"):
        path = os.path.join(data_dir, fname)
        if not os.path.exists(path):
            continue
        df = pd.read_csv(path)
        symbol_col = next(
            (c for c in df.columns if "symbol" in c.lower() or "act symbol" in c.lower()),
            None,
        )
        if symbol_col:
            tickers.update(df[symbol_col].dropna().str.strip().str.upper())
    return tickers


def _extract_tickers(text: str, valid: set[str]) -> list[str]:
    """Return valid ticker mentions from text.

    Rules:
    - 1–2 char tickers: only accepted with explicit $ prefix (e.g. $T, $AI)
    - 3–5 char tickers: accepted bare (ALL-CAPS word) or with $ prefix,
      provided the symbol is in the valid set and not in STOPWORDS
    """
    # Capture dollar-prefixed ($TICKER) and bare ALL-CAPS words separately
    dollar_hits = re.findall(r'\$([A-Z]{1,5})\b', text.upper())
    bare_hits = re.findall(r'(?<!\$)\b([A-Z]{3,5})\b', text.upper())

    found = []
    for symbol in dollar_hits:
        if symbol not in STOPWORDS and symbol in valid:
            found.append(symbol)

    for symbol in bare_hits:
        if symbol not in STOPWORDS and symbol in valid:
            found.append(symbol)

    return found


def _get(url: str, params: dict = None) -> Optional[dict]:
    """GET a Reddit JSON endpoint, returning parsed JSON or None on failure."""
    headers = {"User-Agent": _USER_AGENT}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def _fetch_posts(subreddit: str, limit: int = POSTS_PER_SUB) -> list[dict]:
    """Fetch up to `limit` new posts from a subreddit, filtered to last 24 hours."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=24)
    posts = []
    after = None

    while len(posts) < limit:
        params = {"limit": min(100, limit - len(posts))}
        if after:
            params["after"] = after

        url = f"https://www.reddit.com/r/{subreddit}/new.json"
        data = _get(url, params)
        if not data:
            break

        children = data.get("data", {}).get("children", [])
        if not children:
            break

        for child in children:
            post = child.get("data", {})
            ts = datetime.fromtimestamp(post.get("created_utc", 0), tz=timezone.utc)
            if ts < cutoff:
                # Posts are newest-first; once we go past 24h we can stop
                return posts
            posts.append(post)

        after = data.get("data", {}).get("after")
        if not after:
            break

        time.sleep(_REQUEST_DELAY)

    return posts


def _fetch_comments(subreddit: str, post_id: str) -> list[str]:
    """Return flat list of comment body strings for a post."""
    url = f"https://www.reddit.com/r/{subreddit}/comments/{post_id}.json"
    data = _get(url)
    if not data or not isinstance(data, list) or len(data) < 2:
        return []

    comments = []
    def _walk(node):
        if isinstance(node, dict):
            kind = node.get("kind")
            if kind == "t1":
                body = node.get("data", {}).get("body", "")
                if body:
                    comments.append(body)
            replies = node.get("data", {}).get("replies")
            if isinstance(replies, dict):
                for child in replies.get("data", {}).get("children", []):
                    _walk(child)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    for child in data[1].get("data", {}).get("children", []):
        _walk(child)

    return comments


def scrape_mentions(
    subreddits: list[str] = None,
    posts_per_sub: int = POSTS_PER_SUB,
    min_threshold: int = None,
) -> pd.DataFrame:
    """Scrape Reddit and return a DataFrame of ticker mention counts.

    Columns: ticker, mentions, subreddits_seen, last_seen_utc
    """
    if subreddits is None:
        subreddits = SUBREDDITS
    if min_threshold is None:
        min_threshold = int(os.getenv("MIN_MENTION_THRESHOLD", 8))

    valid_tickers = _load_valid_tickers()

    mention_counter: Counter = Counter()
    subreddit_map: dict[str, set] = {}
    last_seen: dict[str, datetime] = {}

    def _record(tickers: list[str], sub_name: str, ts: datetime) -> None:
        for t in tickers:
            mention_counter[t] += 1
            subreddit_map.setdefault(t, set()).add(sub_name)
            if t not in last_seen or ts > last_seen[t]:
                last_seen[t] = ts

    for sub_name in subreddits:
        posts = _fetch_posts(sub_name, limit=posts_per_sub)

        for i, post in enumerate(posts):
            ts = datetime.fromtimestamp(post.get("created_utc", 0), tz=timezone.utc)
            text = f"{post.get('title', '')} {post.get('selftext', '')}"
            _record(_extract_tickers(text, valid_tickers), sub_name, ts)

            # Fetch comments for the top N posts by score
            if i < TOP_POSTS_FOR_COMMENTS:
                post_id = post.get("id", "")
                if post_id:
                    time.sleep(_REQUEST_DELAY)
                    for body in _fetch_comments(sub_name, post_id):
                        _record(_extract_tickers(body, valid_tickers), sub_name, ts)

        time.sleep(_REQUEST_DELAY)

    rows = []
    for ticker, count in mention_counter.items():
        if count >= min_threshold:
            rows.append(
                {
                    "ticker": ticker,
                    "mentions": count,
                    "subreddits_seen": ",".join(sorted(subreddit_map[ticker])),
                    "last_seen_utc": last_seen[ticker].isoformat(),
                }
            )

    df = pd.DataFrame(rows).sort_values("mentions", ascending=False).reset_index(drop=True)
    return df


def save_to_json(df: pd.DataFrame, path: str = None) -> str:
    """Persist mention DataFrame to JSON and return the file path."""
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "..", "data", "reddit_raw.json")
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_json(path, orient="records", indent=2)
    return path


if __name__ == "__main__":
    print("Scraping Reddit for ticker mentions (last 24 h)…\n")
    results = scrape_mentions()
    out_path = save_to_json(results)

    top = results.head(15)
    print(f"{'Rank':<5} {'Ticker':<8} {'Mentions':<10} {'Subreddits'}")
    print("-" * 65)
    for rank, row in enumerate(top.itertuples(), start=1):
        subs = ", ".join(row.subreddits_seen.split(","))
        print(f"{rank:<5} {row.ticker:<8} {row.mentions:<10} {subs}")

    print(f"\n{len(results)} ticker(s) above threshold  |  saved → {out_path}")
