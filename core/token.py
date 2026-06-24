"""
core/token.py — Token data model
"""
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Token:
    # --- Identity ---
    name: str
    ticker: str
    category: str
    gecko_id: Optional[str] = None

    # --- SwissBorg data ---
    sb_price: Optional[float] = None          # price scraped from SwissBorg (string "$…" cleaned)
    sb_variation_24h: Optional[float] = None  # variation scraped

    # --- CoinGecko market data ---
    current_price: Optional[float] = None
    market_cap: Optional[float] = None
    volume_24h: Optional[float] = None
    change_24h: Optional[float] = None

    # --- Status flags ---
    is_new: bool = False          # True if token wasn't in previous cache run

    # --- Social / trend data ---
    trend_score: float = 0.0     # Google Trends score (0–100)
    reddit_mentions: int = 0
    youtube_mentions: int = 0

    # --- Computed scores ---
    analytic_score: float = 0.0  # pure math score on price/volume curves
    social_score: float = 0.0    # heuristic on social signals
    final_score: float = 0.0     # combined final ranking score

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Token":
        # Keep only known fields to avoid dataclass errors on old cache keys
        known = {f.name for f in Token.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        clean = {k: v for k, v in d.items() if k in known}
        return Token(**clean)

    def __repr__(self) -> str:
        return f"Token({self.name} / {self.ticker} | score={self.final_score:.2f})"
