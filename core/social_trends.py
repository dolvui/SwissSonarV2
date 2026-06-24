"""
core/social_trends.py — Social signal collection.

Sources:
  - Google Trends  (pytrends, no API key needed)
  - Reddit         (PRAW — needs client_id / client_secret / user_agent)
  - YouTube Data v3 (needs GOOGLE_KEY)

All functions return -1 on failure so callers can distinguish
"API down" from a real zero count.
"""
import time
import streamlit as st
import praw
from googleapiclient.discovery import build
from datetime import datetime, timedelta
from pytrends.request import TrendReq
from core.token import Token

# ── Secret loading ─────────────────────────────────────────────────────────────

def _secrets() -> dict:
    """Return a flat dict of secrets regardless of source."""
    try:
        # Streamlit secrets (preferred)
        return {
            "client_id":     st.secrets["reddit"]["client_id"],
            "client_secret": st.secrets["reddit"]["client_secret"],
            "user_agent":    st.secrets["reddit"]["user_agent"],
            "google_key":    st.secrets["youtube"]["api_key"],
        }
    except Exception:
        import os
        return {
            "client_id":     os.getenv("REDDIT_CLIENT_ID", ""),
            "client_secret": os.getenv("REDDIT_CLIENT_SECRET", ""),
            "user_agent":    os.getenv("REDDIT_USER_AGENT", "crypto-dashboard/1.0"),
            "google_key":    os.getenv("GOOGLE_KEY", ""),
        }


@st.cache_resource
def _reddit_client():
    s = _secrets()
    if not s["client_id"]:
        return None
    return praw.Reddit(
        client_id=s["client_id"],
        client_secret=s["client_secret"],
        user_agent=s["user_agent"],
    )


@st.cache_resource
def _youtube_client():
    s = _secrets()
    if not s["google_key"]:
        return None
    return build("youtube", "v3", developerKey=s["google_key"])


# ── Individual fetchers ────────────────────────────────────────────────────────

def get_google_trend(keyword: str) -> int:
    """Return latest interest value (0–100). Returns -1 on error."""
    try:
        pt = TrendReq(hl="en-US", tz=360, timeout=(10, 25))
        pt.build_payload([keyword], cat=0, timeframe="now 7-d", geo="", gprop="")
        df = pt.interest_over_time()
        if df.empty or keyword not in df.columns:
            return 0
        return int(df[keyword].iloc[-1])
    except Exception as e:
        print(f"[GoogleTrends] {keyword}: {e}")
        return -1


def get_reddit_mentions(keyword: str, subreddit: str = "cryptocurrency", limit: int = 500) -> int:
    """Return count of posts mentioning keyword in the last 24 h. Returns -1 on error."""
    client = _reddit_client()
    if not client:
        return -1
    try:
        count = 0
        cutoff = datetime.utcnow() - timedelta(hours=24)
        for post in client.subreddit(subreddit).search(keyword, sort="new", limit=limit):
            if datetime.utcfromtimestamp(post.created_utc) >= cutoff:
                count += 1
        return count
    except Exception as e:
        print(f"[Reddit] {keyword}: {e}")
        return -1


def get_youtube_mentions(keyword: str, max_results: int = 50) -> int:
    """Return count of videos published in last 24 h. Returns -1 on error."""
    client = _youtube_client()
    if not client:
        return -1
    try:
        published_after = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        req = client.search().list(
            part="snippet",
            q=keyword,
            type="video",
            maxResults=min(max_results, 50),
            publishedAfter=published_after,
        )
        resp = req.execute()
        return len(resp.get("items", []))
    except Exception as e:
        print(f"[YouTube] {keyword}: {e}")
        return -1


# ── Batch enrichment ───────────────────────────────────────────────────────────

def enrich_social(tokens: list[Token], progress_cb=None) -> list[Token]:
    """
    Fetch social signals for every token.
    progress_cb: optional callable(i, total, token_name) for UI updates.
    """
    total = len(tokens)
    for i, token in enumerate(tokens):
        if progress_cb:
            progress_cb(i, total, token.name)

        token.trend_score    = get_google_trend(token.name)
        token.reddit_mentions = get_reddit_mentions(token.name)
        token.youtube_mentions = get_youtube_mentions(token.name)

        # Gentle rate-limiting between tokens
        time.sleep(2)

    return tokens


# ── Heuristic score ────────────────────────────────────────────────────────────

def compute_social_score(token: Token) -> float:
    """
    Produce a normalised social heuristic [0–∞, higher = more buzz].

    Each source contributes only if data is available (≥0).
    Weights: Google 5pts base, YouTube 2pts base, Reddit 3pts base.
    Delta bonus/malus from previous run is not tracked anymore
    (no MongoDB) — we use raw absolute values instead.
    """
    g  = token.trend_score
    yt = token.youtube_mentions
    rd = token.reddit_mentions

    g_ok  = g  >= 0
    yt_ok = yt >= 0
    rd_ok = rd >= 0

    total_weight = 5 * g_ok + 2 * yt_ok + 3 * rd_ok
    if total_weight == 0:
        return 0.0

    score = (
        (5 * (g  / 100)          if g_ok  else 0) +
        (2 * (yt / 50)           if yt_ok else 0) +
        (3 * (rd / 200)          if rd_ok else 0)
    )
    # Normalise by max possible weight so result is in [0, 1]
    normalised = score / (total_weight / 10)
    return round(normalised * 10, 3)   # scale to [0, 10]
