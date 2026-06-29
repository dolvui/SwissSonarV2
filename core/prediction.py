"""
core/prediction.py — Prédiction de gain court-terme (7 jours).

Approche purement technique / statistique, PAS de ML.
L'objectif est d'être réaliste et de discriminer les tokens "actifs mais surachetés"
des tokens "actifs avec encore de la marge".

Métriques utilisées :
  - ATR (Average True Range, 14j)  → borne la prédiction sur la volatilité réelle
  - Distance au Bollinger Upper     → marge avant résistance
  - RSI(14)                         → pénalité si overbought, bonus si oversold
  - Slope + R²                      → direction et fiabilité de la tendance
  - Near-peak                       → pénalité forte si déjà au sommet récent
  - Volume surge                    → confirme ou infirme le signal

Output par token :
  {
    "expected_gain_pct" : float   # % de gain estimé sur 7j (peut être négatif)
    "confidence"        : str     # "🔴 Low" / "🟡 Medium" / "🟢 High"
    "target_price"      : float   # prix cible estimé
    "reasoning"         : str     # explication courte
    "horizon_days"      : int     # toujours 7 pour l'instant
  }
"""
import numpy as np
from core.token import Token


# ── ATR ────────────────────────────────────────────────────────────────────────

def _atr(prices: list[float], period: int = 14) -> float:
    """
    ATR simplifié sur série de closing prices (pas de high/low dispo via CoinGecko).
    On approxime True Range = |close[i] - close[i-1]|.
    Retourne l'ATR en % du prix actuel.
    """
    if len(prices) < period + 1:
        return 5.0   # valeur par défaut prudente
    diffs = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]
    atr_abs = np.mean(diffs[-period:])
    current = prices[-1]
    if current <= 0:
        return 5.0
    return float(atr_abs / current * 100)   # en %


# ── Bollinger distance ─────────────────────────────────────────────────────────

def _bollinger_headroom(prices: list[float], period: int = 20) -> float:
    """
    % de distance entre le prix actuel et la bande de Bollinger supérieure.
    Positif = marge disponible avant résistance.
    Négatif = prix déjà au-dessus de la bande (breakout ou retour probable).
    """
    if len(prices) < period:
        return 0.0
    window = prices[-period:]
    mid = np.mean(window)
    std = np.std(window)
    upper = mid + 2 * std
    current = prices[-1]
    if current <= 0:
        return 0.0
    return float((upper - current) / current * 100)


# ── Prédiction principale ──────────────────────────────────────────────────────

def predict_gain(token: Token, analysis_report: dict) -> dict:
    """
    Produit une prédiction de gain 7j pour un token.

    token           : objet Token (avec current_price, change_24h, etc.)
    analysis_report : dict retourné par core.analysis.analyse_token()
    """
    prices  = analysis_report.get("prices", [])
    volumes = analysis_report.get("volumes", [])

    current_price = token.current_price or (prices[-1] if prices else None)
    if not current_price or current_price <= 0 or len(prices) < 20:
        return _no_data(current_price)

    # ── Métriques de base ──────────────────────────────────────────────────────
    atr_pct        = _atr(prices)
    bb_headroom    = _bollinger_headroom(prices)
    rsi            = analysis_report.get("rsi")
    slope          = analysis_report.get("slope", 0.0)
    r2             = analysis_report.get("r2", 0.0)
    near_peak      = analysis_report.get("near_peak", False)
    rel_vol        = analysis_report.get("rel_volatility", 0.0)

    # ── Gain de base : ce que l'ATR permet en 7 jours ─────────────────────────
    # En 7j, un token peut raisonnablement faire ±(ATR * sqrt(7)) dans la direction de la tendance
    # C'est une approximation du mouvement brownien géométrique.
    max_move_7d = atr_pct * np.sqrt(7)

    # Direction de base = slope normalisée, bornée à ±1
    # On normalise slope par le prix pour avoir un % journalier
    slope_pct_per_day = (slope / current_price * 100) if current_price > 0 else 0
    direction = np.tanh(slope_pct_per_day * 10)   # [-1, 1], saturé rapidement

    # Gain brut = direction × amplitude possible
    raw_gain = direction * max_move_7d

    # ── Ajustements ───────────────────────────────────────────────────────────
    adjustments = []
    adj_total = 0.0

    # 1. Bollinger headroom : si le prix a de la marge avant la résistance, bonus
    if bb_headroom > 5:
        adj = min(bb_headroom * 0.3, 8.0)   # max +8%
        adj_total += adj
        adjustments.append(f"room to BB upper (+{adj:.1f}%)")
    elif bb_headroom < -2:
        adj = max(bb_headroom * 0.5, -6.0)  # max -6%
        adj_total += adj
        adjustments.append(f"above BB upper ({adj:.1f}%)")

    # 2. RSI
    if rsi is not None:
        if rsi > 75:
            adj = -min((rsi - 75) * 0.4, 8.0)
            adj_total += adj
            adjustments.append(f"RSI overbought {rsi:.0f} ({adj:.1f}%)")
        elif rsi > 65:
            adj = -min((rsi - 65) * 0.2, 3.0)
            adj_total += adj
            adjustments.append(f"RSI elevated {rsi:.0f} ({adj:.1f}%)")
        elif rsi < 35:
            adj = min((35 - rsi) * 0.3, 6.0)
            adj_total += adj
            adjustments.append(f"RSI oversold {rsi:.0f} (+{adj:.1f}%)")

    # 3. Near peak : déjà proche du sommet des 50 dernières bougies
    if near_peak:
        adj = -min(max_move_7d * 0.4, 10.0)
        adj_total += adj
        adjustments.append(f"near 50-period peak ({adj:.1f}%)")

    # 4. Trend fiability : si R² fort + slope positive → bonus de confiance
    if r2 > 0.6 and slope > 0:
        adj = min(r2 * 5, 4.0)
        adj_total += adj
        adjustments.append(f"strong uptrend R²={r2:.2f} (+{adj:.1f}%)")
    elif r2 > 0.6 and slope < 0:
        adj = -min(r2 * 5, 5.0)
        adj_total += adj
        adjustments.append(f"strong downtrend R²={r2:.2f} ({adj:.1f}%)")

    # 5. Volume surge confirme le mouvement
    if rel_vol > 50 and direction > 0:
        adj = min(rel_vol * 0.03, 4.0)
        adj_total += adj
        adjustments.append(f"volume surge confirms (+{adj:.1f}%)")
    elif rel_vol > 50 and direction < 0:
        adj = -min(rel_vol * 0.02, 3.0)
        adj_total += adj
        adjustments.append(f"volume surge on downtrend ({adj:.1f}%)")

    # ── Gain final ────────────────────────────────────────────────────────────
    final_gain = raw_gain + adj_total

    # Borne dure : pas plus de 2× l'ATR hebdo dans un sens ou dans l'autre
    cap = max_move_7d * 1.8
    final_gain = float(np.clip(final_gain, -cap, cap))

    # ── Prix cible ────────────────────────────────────────────────────────────
    target_price = current_price * (1 + final_gain / 100)

    # ── Confidence ────────────────────────────────────────────────────────────
    # Basée sur : R² (fiabilité de la tendance) + nombre d'ajustements concordants
    positive_adj = sum(1 for a in adjustments if "(+" in a)
    negative_adj = sum(1 for a in adjustments if "(-" in a or "(" in a and "+" not in a)
    concordant   = positive_adj if final_gain > 0 else negative_adj

    if r2 > 0.55 and concordant >= 2:
        confidence = "🟢 High"
    elif r2 > 0.3 or concordant >= 1:
        confidence = "🟡 Medium"
    else:
        confidence = "🔴 Low"

    # Basse confiance si near_peak + gain positif (signal contradictoire)
    if near_peak and final_gain > 5:
        confidence = "🟡 Medium"

    # ── Reasoning (ligne courte) ───────────────────────────────────────────────
    if adjustments:
        reasoning = " | ".join(adjustments[:3])   # max 3 facteurs affichés
    else:
        reasoning = "No strong signal — ATR-based estimate only"

    return {
        "expected_gain_pct": round(final_gain, 2),
        "target_price":      round(target_price, 6),
        "confidence":        confidence,
        "reasoning":         reasoning,
        "horizon_days":      7,
        "atr_pct":           round(atr_pct, 2),
        "bb_headroom_pct":   round(bb_headroom, 2),
    }


def _no_data(current_price) -> dict:
    return {
        "expected_gain_pct": 0.0,
        "target_price":      current_price or 0.0,
        "confidence":        "🔴 Low",
        "reasoning":         "Insufficient price history",
        "horizon_days":      7,
        "atr_pct":           0.0,
        "bb_headroom_pct":   0.0,
    }


# ── Batch predictions ──────────────────────────────────────────────────────────

def predict_top_tokens(
    tokens: list[Token],
    analysis_reports: dict[str, dict],
    top_n: int = 15,
) -> list[dict]:
    """
    Génère les prédictions pour les top_n tokens.

    tokens           : liste triée par final_score (top en premier)
    analysis_reports : {gecko_id: analyse_token() result}
    top_n            : combien de tokens à prédire

    Retourne une liste de dicts enrichis avec le token + sa prédiction.
    """
    results = []
    for token in tokens[:top_n]:
        report = analysis_reports.get(token.gecko_id, {})
        pred   = predict_gain(token, report)
        results.append({
            "name":               token.name,
            "ticker":             token.ticker,
            "gecko_id":           token.gecko_id,
            "current_price":      token.current_price,
            "final_score":        token.final_score,
            "analytic_score":     token.analytic_score,
            "change_24h":         token.change_24h,
            "is_new":             token.is_new,
            **pred,
        })
    return results
