"""
core/market_data.py — CoinGecko market data fetching.

Uses the free public API (no key required).
Rate limit: ~10–30 req/min → we batch aggressively.
"""
import time
import requests
from core.token import Token

_BASE = "https://api.coingecko.com/api/v3"
_TIMEOUT = 20


def _get(url: str, params: dict = None, retries: int = 3) -> dict | list | None:
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=_TIMEOUT)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 60))
                print(f"[CoinGecko] Rate limited — waiting {wait}s")
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            print(f"[CoinGecko] Attempt {attempt + 1} failed: {e}")
            time.sleep(5 * (attempt + 1))
    return None


# ── Symbol → CoinGecko ID mapping ─────────────────────────────────────────────

_symbol_map_cache: dict[str, str] = {}


def _get_symbol_map() -> dict[str, str]:
    global _symbol_map_cache
    if _symbol_map_cache:
        return _symbol_map_cache
    data = _get(f"{_BASE}/coins/list")
    if data:
        # When multiple coins share a symbol, CoinGecko order puts the main one first.
        # We keep the FIRST occurrence per symbol (highest market relevance).
        m: dict[str, str] = {}
        for coin in data:
            sym = coin["symbol"].lower()
            if sym not in m:
                m[sym] = coin["id"]
        _symbol_map_cache = m
    return _symbol_map_cache


def resolve_gecko_ids(tokens: list[Token]) -> list[Token]:
    """
    Fill token.gecko_id for each token using the CoinGecko symbol map.
    Tokens whose symbol cannot be resolved are kept but gecko_id stays None.
    """
    sym_map = _get_symbol_map()
    for token in tokens:
        gid = sym_map.get(token.ticker.lower())
        if gid:
            token.gecko_id = gid
        else:
            print(f"[CoinGecko] Cannot resolve gecko_id for {token.ticker}")
    return tokens


# ── Batch market data ──────────────────────────────────────────────────────────

def fetch_market_data(tokens: list[Token]) -> list[Token]:
    """
    Fetch current_price, market_cap, volume_24h, change_24h for all tokens.
    Uses a single batched /simple/price call (max ~250 ids per call).
    """
    gecko_ids = [t.gecko_id for t in tokens if t.gecko_id]
    if not gecko_ids:
        return tokens

    # Split into chunks of 200 to stay safe
    CHUNK = 200
    price_data: dict = {}
    for i in range(0, len(gecko_ids), CHUNK):
        chunk = gecko_ids[i: i + CHUNK]
        result = _get(
            f"{_BASE}/simple/price",
            params={
                "ids": ",".join(chunk),
                "vs_currencies": "usd",
                "include_market_cap": "true",
                "include_24hr_vol": "true",
                "include_24hr_change": "true",
            },
        )
        if result:
            price_data.update(result)
        if i + CHUNK < len(gecko_ids):
            time.sleep(1.5)  # stay under rate limit

    for token in tokens:
        if not token.gecko_id:
            continue
        d = price_data.get(token.gecko_id, {})
        token.current_price = d.get("usd")
        token.market_cap = d.get("usd_market_cap")
        token.volume_24h = d.get("usd_24h_vol")
        token.change_24h = d.get("usd_24h_change")

    return tokens


# ── Historical price / volume / market-cap ────────────────────────────────────

def fetch_token_history(gecko_id: str, days: int = 90) -> dict:
    """
    Returns {"prices": [[ts,v],...], "total_volumes": [...], "market_caps": [...]}.
    Returns empty dict on failure.
    """
    data = _get(
        f"{_BASE}/coins/{gecko_id}/market_chart",
        params={"vs_currency": "usd", "days": days, "precision": "5"},
    )
    return data or {}
