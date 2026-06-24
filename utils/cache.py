"""
utils/cache.py — JSON-based local cache (replaces MongoDB)

Structure on disk:
{
    "last_run": "<ISO timestamp>",
    "known_ids": ["bitcoin", "ethereum", ...],   # all gecko IDs ever seen
    "tokens": [ {token dict}, ... ]
}
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

CACHE_PATH = Path(__file__).parent.parent / "cache.json"
TTL_HOURS = 24  # cache is considered stale after this many hours


def _load_raw() -> dict:
    if CACHE_PATH.exists():
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"last_run": None, "known_ids": [], "tokens": []}


def _save_raw(data: dict) -> None:
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def is_cache_fresh() -> bool:
    """Return True if cache exists and is younger than TTL_HOURS."""
    raw = _load_raw()
    if not raw.get("last_run"):
        return False
    try:
        last = datetime.fromisoformat(raw["last_run"])
        # Make timezone-aware comparison
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - last).total_seconds() / 3600
        return age_hours < TTL_HOURS
    except (ValueError, TypeError):
        return False


def get_cached_tokens() -> Optional[list[dict]]:
    """Return cached token dicts if cache is fresh, else None."""
    raw = _load_raw()
    tokens = raw.get("tokens", [])
    return tokens if tokens else None


def get_known_ids() -> set[str]:
    """Return the set of gecko_ids seen in all previous runs."""
    raw = _load_raw()
    return set(raw.get("known_ids", []))


def save_tokens(tokens: list) -> None:
    """
    Persist token list to cache.
    tokens: list of Token objects (must have .to_dict() method)
    """
    raw = _load_raw()
    existing_ids = set(raw.get("known_ids", []))

    token_dicts = []
    new_ids = set()
    for t in tokens:
        d = t.to_dict()
        if d.get("gecko_id") and d["gecko_id"] not in existing_ids:
            new_ids.add(d["gecko_id"])
        token_dicts.append(d)

    all_ids = list(existing_ids | {d["gecko_id"] for d in token_dicts if d.get("gecko_id")})

    raw["last_run"] = datetime.now(timezone.utc).isoformat()
    raw["known_ids"] = all_ids
    raw["tokens"] = token_dicts
    _save_raw(raw)

    return new_ids  # caller can use this to flag new tokens


def get_last_run_time() -> Optional[str]:
    raw = _load_raw()
    return raw.get("last_run")
