"""
core/analysis.py — Technical / mathematical analysis of price curves.

All functions are pure (no I/O, no Streamlit).
Input: raw CoinGecko history dict {"prices":[[ts,v],...], "total_volumes":[...], ...}
"""
import numpy as np
from scipy.stats import linregress
from core.token import Token


# ── Primitives ─────────────────────────────────────────────────────────────────

def _pct_change(series: list[float]) -> float:
    if len(series) < 2 or series[0] == 0:
        return 0.0
    return ((series[-1] - series[0]) / series[0]) * 100


def _volatility(series: list[float]) -> float:
    return float(np.std(series)) if len(series) > 1 else 0.0


def _correlation(a: list[float], b: list[float]) -> float:
    if len(a) < 2 or len(b) < 2:
        return 0.0
    try:
        return float(np.corrcoef(a, b)[0, 1])
    except Exception:
        return 0.0


def _linear_slope(series: list[float]) -> tuple[float, float]:
    """Returns (slope, r²)."""
    if len(series) < 2:
        return 0.0, 0.0
    x = np.arange(len(series), dtype=float)
    try:
        slope, _, r_value, _, _ = linregress(x, series)
        return float(slope), float(r_value ** 2)
    except Exception:
        return 0.0, 0.0


def _detect_near_peak(prices: list[float], tolerance: float = 0.02) -> bool:
    """True if current price is within `tolerance` of 50-period high."""
    if len(prices) < 10:
        return False
    lookback = prices[-50:]
    return prices[-1] >= max(lookback) * (1 - tolerance)


def _rsi(prices: list[float], period: int = 14) -> float | None:
    """Return RSI(period) of the price series. None if not enough data."""
    if len(prices) < period + 1:
        return None
    arr = np.array(prices)
    deltas = np.diff(arr)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 2)


def _bollinger(prices: list[float], period: int = 20) -> tuple[float, float, float]:
    """Returns (upper, mid, lower) bands based on last `period` prices."""
    if len(prices) < period:
        mid = prices[-1] if prices else 0
        return mid, mid, mid
    window = prices[-period:]
    mid = np.mean(window)
    std = np.std(window)
    return float(mid + 2 * std), float(mid), float(mid - 2 * std)


# ── Main analysis function ─────────────────────────────────────────────────────

def analyse_token(cg_data: dict) -> dict:
    """
    Compute a full technical analysis dict from CoinGecko history data.

    Returns a structured dict suitable for display and for computing final_score.
    """
    prices  = [p[1] for p in cg_data.get("prices", [])]
    volumes = [v[1] for v in cg_data.get("total_volumes", [])]

    if not prices:
        return _empty_report()

    delta_price   = _pct_change(prices)
    vol_vol       = _volatility(volumes)
    corr_pv       = _correlation(prices, volumes)
    slope, r2     = _linear_slope(prices)
    near_peak     = _detect_near_peak(prices)
    rsi_val       = _rsi(prices)
    bb_upper, bb_mid, bb_lower = _bollinger(prices)

    avg_vol       = np.mean(volumes) if volumes else 1.0
    rel_vol       = (vol_vol / avg_vol * 100) if avg_vol else 0.0

    # Core analytic score
    analytic_score = (
        0.30 * abs(delta_price) +
        0.50 * rel_vol +
        0.20 * abs(slope) * 100
    )
    if r2 < 0.15 and abs(corr_pv) < 0.2:
        analytic_score *= 0.5   # penalise noisy / unstructured data

    # Trend direction
    if slope > 0 and r2 > 0.5:
        trend = "📈 Clear uptrend"
    elif slope < 0 and r2 > 0.5:
        trend = "📉 Clear downtrend"
    elif rel_vol > 30 and abs(corr_pv) > 0.6:
        trend = "🚨 Volume spike + price correlation"
    else:
        trend = "🔍 No clear pattern"

    # Signal tier
    if analytic_score > 25:
        signal = "🚨 Exceptional"
    elif analytic_score > 15:
        signal = "🔺 Strong"
    elif analytic_score > 8:
        signal = "🔹 Medium"
    else:
        signal = "⚪ Weak"

    # RSI annotation
    rsi_note = ""
    if rsi_val is not None:
        if rsi_val > 70:
            rsi_note = "Overbought"
        elif rsi_val < 30:
            rsi_note = "Oversold"
        else:
            rsi_note = "Neutral"

    # Bollinger position
    current = prices[-1]
    if current > bb_upper:
        bb_note = "Above upper band (breakout)"
    elif current < bb_lower:
        bb_note = "Below lower band (oversold)"
    else:
        bb_note = "Within bands"

    return {
        "prices":         prices,
        "volumes":        volumes,
        "delta_price_pct": round(delta_price, 2),
        "vol_volatility":  round(vol_vol, 2),
        "corr_price_vol":  round(corr_pv, 3),
        "slope":           round(slope, 5),
        "r2":              round(r2, 3),
        "rel_volatility":  round(rel_vol, 2),
        "analytic_score":  round(analytic_score, 2),
        "rsi":             rsi_val,
        "rsi_note":        rsi_note,
        "bb_upper":        round(bb_upper, 6),
        "bb_mid":          round(bb_mid, 6),
        "bb_lower":        round(bb_lower, 6),
        "bb_note":         bb_note,
        "near_peak":       near_peak,
        "trend":           trend,
        "signal":          signal,
    }


def _empty_report() -> dict:
    return {
        "prices": [], "volumes": [],
        "delta_price_pct": 0, "vol_volatility": 0, "corr_price_vol": 0,
        "slope": 0, "r2": 0, "rel_volatility": 0,
        "analytic_score": 0, "rsi": None, "rsi_note": "",
        "bb_upper": 0, "bb_mid": 0, "bb_lower": 0, "bb_note": "",
        "near_peak": False, "trend": "N/A", "signal": "⚪ Weak",
    }


# ── Score propagation to Token ─────────────────────────────────────────────────

def apply_analytic_score(token: Token, cg_data: dict) -> dict:
    """Analyse token data and write analytic_score back to the Token. Returns the full report."""
    report = analyse_token(cg_data)
    token.analytic_score = report["analytic_score"]
    return report
