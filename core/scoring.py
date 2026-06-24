"""
core/scoring.py — Combine analytic + social signals into a final [0–100] score.

Weights (configurable via constants):
  W_ANALYTIC   : pure maths on price/volume curves
  W_SOCIAL     : Google Trends + Reddit + YouTube heuristic
  W_MOMENTUM   : short-term price momentum (1h/4h delta)
  W_NEW_TOKEN  : bonus for newly listed tokens (FOMO signal)
"""
import numpy as np
from core.token import Token
from core.social_trends import compute_social_score

# ── Weight config ──────────────────────────────────────────────────────────────
W_ANALYTIC  = 0.35
W_SOCIAL    = 0.35
W_MOMENTUM  = 0.20
W_NEW_TOKEN = 0.10   # bonus weight; added on top when is_new=True

# ── Normalisation helpers ──────────────────────────────────────────────────────

def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _normalise_analytic(raw: float) -> float:
    """analytic_score is unbounded — sigmoid-ish cap at 100."""
    return _clamp(raw * 2, 0, 100)


def _normalise_social(raw: float) -> float:
    """social_score is [0–10] → scale to [0–100]."""
    return _clamp(raw * 10, 0, 100)


def _momentum_score(token: Token) -> float:
    """
    Simple momentum from 24h change + market cap proxy.
    Returns [0–100].
    """
    change = token.change_24h or 0.0          # percent
    # A +10% day → 100; -10% → 0; neutral → 50
    mom = _clamp(50 + change * 5, 0, 100)
    return mom


# ── Main scoring ───────────────────────────────────────────────────────────────

def compute_final_score(token: Token) -> float:
    """
    Compute and set token.social_score + token.final_score.
    Returns final_score.
    """
    social = compute_social_score(token)
    token.social_score = social

    norm_analytic = _normalise_analytic(token.analytic_score)
    norm_social   = _normalise_social(social)
    norm_momentum = _momentum_score(token)

    base_weights_sum = W_ANALYTIC + W_SOCIAL + W_MOMENTUM  # = 0.90

    score = (
        W_ANALYTIC  * norm_analytic +
        W_SOCIAL    * norm_social   +
        W_MOMENTUM  * norm_momentum
    ) / base_weights_sum  # normalise to [0,100]

    # New token bonus: bump score by 10% of remaining headroom
    if token.is_new:
        score = score + W_NEW_TOKEN * (100 - score)

    token.final_score = round(_clamp(score), 2)
    return token.final_score


def rank_tokens(tokens: list[Token]) -> list[Token]:
    """Sort tokens by final_score descending. Modifies list in place and returns it."""
    for t in tokens:
        compute_final_score(t)
    tokens.sort(key=lambda t: t.final_score, reverse=True)
    return tokens
