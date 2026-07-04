"""
core/social_trends.py — Social signal collection.

Sources actives :
  - Reddit   (PRAW)          → mentions dans les 24h sur r/cryptocurrency
  - YouTube  (Data API v3)   → vidéos publiées dans les 24h

Google Trends désactivé par défaut :
  - Bloque l'IP après ~50-100 requêtes par session
  - urllib3 >= 2.0 incompatible avec pytrends (method_whitelist → allowed_methods)
  - Peu fiable sur les petits tokens (retourne souvent 0)
  - Activable via --with-trends dans refresh.py si vraiment voulu

Toutes les fonctions retournent -1 en cas d'erreur pour distinguer
"API down" d'un vrai score de zéro.
"""
import time
import random
import os
from googleapiclient.discovery import build
from datetime import datetime, timedelta
from core.token import Token


# ── Secrets (Streamlit ou env vars) ───────────────────────────────────────────

def _secrets() -> dict:
    try:
        import streamlit as st
        return {
            "client_id":     st.secrets["reddit"]["client_id"],
            "client_secret": st.secrets["reddit"]["client_secret"],
            "user_agent":    st.secrets["reddit"]["user_agent"],
            "google_key":    st.secrets["youtube"]["api_key"],
        }
    except Exception:
        return {
            "client_id":     os.getenv("REDDIT_CLIENT_ID", ""),
            "client_secret": os.getenv("REDDIT_CLIENT_SECRET", ""),
            "user_agent":    os.getenv("REDDIT_USER_AGENT", "crypto-dashboard/1.0"),
            "google_key":    os.getenv("GOOGLE_KEY", ""),
        }


# ── Singletons de module (pas de st.cache_resource — tourne hors Streamlit) ───

_reddit_instance  = None
_youtube_instance = None
_secrets_cache    = None


def _get_secrets() -> dict:
    global _secrets_cache
    if _secrets_cache is None:
        _secrets_cache = _secrets()
    return _secrets_cache


def _reddit():
    global _reddit_instance
    if _reddit_instance is None:
        import praw
        s = _get_secrets()
        cid = s.get("client_id", "").strip()
        if not cid:
            print("[Social] Reddit: no client_id configured — skipping")
            return None
        try:
            _reddit_instance = praw.Reddit(
                client_id=cid,
                client_secret=s["client_secret"],
                user_agent=s["user_agent"],
            )
        except Exception as e:
            print(f"[Social] Reddit init failed: {e}")
            _reddit_instance = None
    return _reddit_instance


def _youtube():
    global _youtube_instance
    if _youtube_instance is None:
        s = _get_secrets()
        key = s.get("google_key", "").strip()
        if not key:
            print("[Social] YouTube: no api_key configured — skipping")
            return None
        try:
            _youtube_instance = build("youtube", "v3", developerKey=key)
        except Exception as e:
            print(f"[Social] YouTube init failed: {e}")
            _youtube_instance = None
    return _youtube_instance


# ── Reddit ─────────────────────────────────────────────────────────────────────

def get_reddit_mentions(keyword: str, subreddit: str = "cryptocurrency", limit: int = 500) -> int:
    """Retourne le nombre de posts dans les 24h, ou -1 si erreur/non configuré."""
    client = _reddit()
    if client is None:
        return -1
    try:
        count  = 0
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
    """Retourne le nombre de vidéos publiées dans les 24h, ou -1 si erreur/non configuré."""
    client = _youtube()
    if client is None:
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
        return len(req.execute().get("items", []))
    except Exception as e:
        print(f"[YouTube] '{keyword}': {e}")
        return -1


# ── Google Trends (optionnel) ──────────────────────────────────────────────────

_GTRENDS_SLEEP_BASE   = 10.0
_GTRENDS_SLEEP_JITTER = 5.0
_GTRENDS_MAX_RETRIES  = 3
_GTRENDS_BACKOFF_BASE = 90
_pytrends = None


def _get_pytrends():
    global _pytrends
    if _pytrends is None:
        # Patch de compatibilité urllib3 >= 2.0
        # pytrends passe method_whitelist qui a été renommé allowed_methods
        try:
            import urllib3
            from urllib3.util.retry import Retry
            _orig_init = Retry.__init__

            def _patched_init(self, *args, **kwargs):
                if "method_whitelist" in kwargs:
                    kwargs["allowed_methods"] = kwargs.pop("method_whitelist")
                _orig_init(self, *args, **kwargs)

            Retry.__init__ = _patched_init
        except Exception:
            pass

        from pytrends.request import TrendReq
        _pytrends = TrendReq(hl="en-US", tz=360, timeout=(15, 30))
    return _pytrends


def get_google_trend(keyword: str) -> int:
    """
    Retourne le score Google Trends (0–100), ou -1 si erreur.
    À appeler seulement avec --with-trends (voir refresh.py).
    """
    global _pytrends
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
                wait = _GTRENDS_BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 15)
                print(f"[GoogleTrends] 429 '{keyword}' — waiting {wait:.0f}s (attempt {attempt+1}/{_GTRENDS_MAX_RETRIES})")
                time.sleep(wait)
                _pytrends = None
                pt = _get_pytrends()
            else:
                print(f"[GoogleTrends] '{keyword}': {e}")
                return -1

    print(f"[GoogleTrends] '{keyword}': gave up after {_GTRENDS_MAX_RETRIES} retries")
    return -1


# ── Batch enrichment ───────────────────────────────────────────────────────────

def enrich_social(tokens: list[Token], progress_cb=None, with_trends: bool = False) -> list[Token]:
    """
    Enrichit chaque token avec les signaux sociaux.

    with_trends=False (défaut) : Reddit + YouTube seulement (~2s/token)
    with_trends=True           : + Google Trends (~12s/token, risque de blocage IP)
    """
    total = len(tokens)

    for i, token in enumerate(tokens):
        if progress_cb:
            progress_cb(i, total, token.name)

        if with_trends:
            token.trend_score = get_google_trend(token.name)
            sleep_gt = _GTRENDS_SLEEP_BASE + random.uniform(0, _GTRENDS_SLEEP_JITTER)
            print(f"  ↳ GT={token.trend_score}  sleep {sleep_gt:.1f}s…")
            time.sleep(sleep_gt)
        else:
            token.trend_score = -1   # -1 = non collecté (pas pénalisé dans le score)

        token.reddit_mentions  = get_reddit_mentions(token.name)
        token.youtube_mentions = get_youtube_mentions(token.name)
        time.sleep(1.2)

    return tokens


# ── Score social ───────────────────────────────────────────────────────────────

def compute_social_score(token: Token) -> float:
    """
    Score social normalisé [0–10].
    Les sources à -1 (erreur ou non collectées) sont ignorées — pas pénalisées.
    """
    g, yt, rd = token.trend_score, token.youtube_mentions, token.reddit_mentions
    g_ok, yt_ok, rd_ok = g >= 0, yt >= 0, rd >= 0

    total_weight = 5 * g_ok + 2 * yt_ok + 3 * rd_ok
    if total_weight == 0:
        return 0.0

    score = (
        (5 * (g  / 100) if g_ok  else 0) +
        (2 * (yt / 50)  if yt_ok else 0) +
        (3 * (rd / 200) if rd_ok else 0)
    )
    return round((score / (total_weight / 10)) * 10, 3)
