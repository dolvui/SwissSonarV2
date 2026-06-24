"""
core/swissborg.py — Scrape the SwissBorg supported-assets page.

SwissBorg renders via JS, so we try:
  1. A lightweight requests + BS4 attempt (works if they serve SSR/static HTML).
  2. If that yields 0 tokens, fall back to a curated static list so the app
     is never completely broken (user sees a warning).

To make option 1 more reliable without Selenium, we send realistic browser
headers and parse whatever table/card content is present.
"""
import re
import time
import requests
from bs4 import BeautifulSoup
from core.token import Token

_URL = "https://swissborg.com/fr/supported-assets"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://swissborg.com/",
}

# Minimal static fallback — the most common SwissBorg tokens.
# Update this list manually when needed.
_STATIC_FALLBACK: list[dict] = [
    {"name": "Bitcoin",   "ticker": "BTC", "category": "Crypto"},
    {"name": "Ethereum",  "ticker": "ETH", "category": "Crypto"},
    {"name": "Solana",    "ticker": "SOL", "category": "Crypto"},
    {"name": "Cardano",   "ticker": "ADA", "category": "Crypto"},
    {"name": "Polkadot",  "ticker": "DOT", "category": "Crypto"},
    {"name": "Avalanche", "ticker": "AVAX","category": "Crypto"},
    {"name": "Chainlink", "ticker": "LINK","category": "Crypto"},
    {"name": "Uniswap",   "ticker": "UNI", "category": "DeFi"},
    {"name": "Aave",      "ticker": "AAVE","category": "DeFi"},
    {"name": "Polygon",   "ticker": "MATIC","category":"Crypto"},
    {"name": "Litecoin",  "ticker": "LTC", "category": "Crypto"},
    {"name": "Ripple",    "ticker": "XRP", "category": "Crypto"},
    {"name": "Dogecoin",  "ticker": "DOGE","category": "Meme"},
    {"name": "Shiba Inu","ticker": "SHIB", "category": "Meme"},
    {"name": "Near Protocol","ticker":"NEAR","category":"Crypto"},
    {"name": "Cosmos",    "ticker": "ATOM","category": "Crypto"},
    {"name": "Algorand",  "ticker": "ALGO","category": "Crypto"},
    {"name": "VeChain",   "ticker": "VET", "category": "Crypto"},
    {"name": "Internet Computer","ticker":"ICP","category":"Crypto"},
    {"name": "Stellar",   "ticker": "XLM", "category": "Crypto"},
]


def _clean_price(raw: str) -> float:
    """'$1 234.56' → 1234.56"""
    try:
        return float(re.sub(r"[^\d.]", "", raw.replace(",", ".")))
    except ValueError:
        return 0.0


def _clean_pct(raw: str) -> float:
    """'+3.45%' or '-1.2%' → ±float"""
    try:
        return float(re.sub(r"[^\d.+-]", "", raw))
    except ValueError:
        return 0.0


def fetch_swissborg_tokens() -> tuple[list[Token], bool]:
    """
    Returns (tokens, used_fallback).
    used_fallback=True means the static list was used because scraping failed.
    """
    tokens: list[Token] = []
    used_fallback = False

    try:
        resp = requests.get(_URL, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # --- Strategy A: find a <table> ---
        table = soup.find("table")
        if table:
            rows = table.find("tbody").find_all("tr") if table.find("tbody") else table.find_all("tr")
            for row in rows:
                cells = [p.get_text(strip=True) for p in row.find_all("p")]
                if len(cells) >= 5:
                    tokens.append(Token(
                        name=cells[0],
                        ticker=cells[1],
                        sb_price=_clean_price(cells[2]),
                        sb_variation_24h=_clean_pct(cells[3]),
                        category=cells[4],
                    ))

        # --- Strategy B: card layout ---
        if not tokens:
            cards = soup.find_all("div", class_=re.compile(r"assetCard|asset-card|AssetCard", re.I))
            for card in cards:
                ps = [p.get_text(strip=True) for p in card.find_all("p")]
                spans = [s.get_text(strip=True) for s in card.find_all("span")]
                all_text = ps + spans
                if len(all_text) >= 2:
                    tokens.append(Token(
                        name=all_text[0],
                        ticker=all_text[1] if len(all_text) > 1 else "",
                        sb_price=_clean_price(all_text[2]) if len(all_text) > 2 else None,
                        sb_variation_24h=_clean_pct(all_text[3]) if len(all_text) > 3 else None,
                        category=all_text[4] if len(all_text) > 4 else "Crypto",
                    ))

    except Exception as e:
        print(f"[SwissBorg] Scraping error: {e}")

    if not tokens:
        used_fallback = True
        tokens = [
            Token(name=d["name"], ticker=d["ticker"], category=d["category"])
            for d in _STATIC_FALLBACK
        ]

    return tokens, used_fallback
