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
import random
import streamlit as st
import praw
from googleapiclient.discovery import build
from datetime import datetime, timedelta
from pytrends.request import TrendReq
from core.token import Token

# ── Timings Google Trends ──────────────────────────────────────────────────────
# Google Trends rate-limite agressivement (~10-15 req sans pause → 429).
# On garde une instance unique de TrendReq et on ajoute des sleeps importants.

_GTRENDS_SLEEP_BASE   = 8.0   # secondes entre chaque requête Google Trends
_GTRENDS_SLEEP_JITTER = 4.0   # jitter aléatoire ajouté pour éviter les patterns
_GTRENDS_MAX_RETRIES  = 4
_GTRENDS_BACKOFF_BASE = 60    # secondes d'attente initiale sur 429

# Instance unique réutilisée pour toute la session (évite les re-handshakes)
_pytrends: TrendReq | None = None

def _get_pytrends() -> TrendReq:
    global _pytrends
    if _pytrends is None:
        _pytrends = TrendReq(
            hl="en-US",
            tz=360,
            timeout=(15, 30),
            retries=1,
            backoff_factor=2,
        )
    return _pytrends


# ── Secret loading ─────────────────────────────────────────────────────────────

def _secrets() -> dict:
    try:
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


# ── Google Trends ──────────────────────────────────────────────────────────────

def get_google_trend(keyword: str) -> int:
    """
    Return latest Google Trends interest value (0–100).
    Returns -1 on unrecoverable error.

    Implements exponential backoff on 429 and a fixed sleep between
    every call to stay under the rate limit.
    """
    pt = _get_pytrends()

    for attempt in range(_GTRENDS_MAX_RETRIES):
        try:
            pt.build_payload([keyword], cat=0, timeframe="now 7-d", geo="", gprop="")
            df = pt.interest_over_time()

            if df.empty or keyword not in df.columns:
                return 0
            return int(df[keyword].iloc[-1])

        except Exception as e:
            err = str(e)
            if "429" in err or "Too Many Requests" in err or "response with code 429" in err:
                wait = _GTRENDS_BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 10)
                print(f"[GoogleTrends] 429 on '{keyword}' — waiting {wait:.0f}s (attempt {attempt+1}/{_GTRENDS_MAX_RETRIES})")
                time.sleep(wait)
                # Réinitialiser l'instance après un 429
                global _pytrends
                _pytrends = None
                pt = _get_pytrends()
            else:
                print(f"[GoogleTrends] '{keyword}': {e}")
                return -1

    print(f"[GoogleTrends] '{keyword}': gave up after {_GTRENDS_MAX_RETRIES} retries")
    return -1


# ── Reddit ─────────────────────────────────────────────────────────────────────

def get_reddit_mentions(keyword: str, subreddit: str = "cryptocurrency", limit: int = 500) -> int:
    """Return count of posts mentioning keyword in the last 24h. Returns -1 on error."""
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
        print(f"[Reddit] '{keyword}': {e}")
        return -1


# ── YouTube ────────────────────────────────────────────────────────────────────

def get_youtube_mentions(keyword: str, max_results: int = 50) -> int:
    """Return count of videos published in last 24h. Returns -1 on error."""
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
        print(f"[YouTube] '{keyword}': {e}")
        return -1


# ── Batch enrichment ───────────────────────────────────────────────────────────

def enrich_social(tokens: list[Token], progress_cb=None) -> list[Token]:
    """
    Fetch social signals for every token.

    Google Trends est le goulot d'étranglement : on dors _GTRENDS_SLEEP_BASE
    secondes entre chaque token (+ jitter), Reddit et YouTube sont plus permissifs.

    progress_cb: optional callable(i, total, token_name)
    """
    total = len(tokens)

    for i, token in enumerate(tokens):
        if progress_cb:
            progress_cb(i, total, token.name)

        # --- Google Trends (le plus sensible au rate limit) ---
        token.trend_score = get_google_trend(token.name)

        # Sleep systématique après chaque appel Google Trends,
        # même en cas d'erreur, pour ne pas enchaîner les requêtes.
        sleep_gt = _GTRENDS_SLEEP_BASE + random.uniform(0, _GTRENDS_SLEEP_JITTER)
        print(f"  ↳ trend={token.trend_score}  sleeping {sleep_gt:.1f}s before next token…")
        time.sleep(sleep_gt)

        # --- Reddit & YouTube (moins restrictifs) ---
        token.reddit_mentions  = get_reddit_mentions(token.name)
        token.youtube_mentions = get_youtube_mentions(token.name)

        # Petit sleep entre tokens pour Reddit/YouTube aussi
        time.sleep(1.5)

    return tokens


# ── Score social ───────────────────────────────────────────────────────────────

def compute_social_score(token: Token) -> float:
    """
    Score social normalisé [0–10].
    Les sources avec valeur -1 (erreur API) sont ignorées du calcul.
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
        (5 * (g  / 100) if g_ok  else 0) +
        (2 * (yt / 50)  if yt_ok else 0) +
        (3 * (rd / 200) if rd_ok else 0)
    )
    normalised = score / (total_weight / 10)
    return round(normalised * 10, 3)