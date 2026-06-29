"""
core/scoring.py — Score final [0–100] par token.

Problèmes corrigés v2 :
  1. Biais sources sociales manquantes : on pénalise moins les tokens
     dont Google Trends a timeout (on ne divise que par les sources dispo,
     mais on ne récompense pas les tokens avec toutes les sources).
  2. Score analytic trop peu discriminant : ajout d'un signal volume_surge
     (volume 24h vs moyenne 30j estimée via market_cap proxy).
  3. Momentum trop court (24h only) : on garde le 24h mais on le pondère moins.

Poids v2 :
  W_ANALYTIC   0.40  — analyse technique courbe de prix (slope, vol, R²)
  W_SOCIAL     0.30  — signaux sociaux (sources manquantes = score partiel, pas 0)
  W_MOMENTUM   0.20  — variation 24h prix
  W_VOL_SURGE  0.10  — volume 24h vs volume habituel (proxy spike)
  Bonus new token : +8% du headroom restant
"""
from core.token import Token
from core.social_trends import compute_social_score

# ── Poids ──────────────────────────────────────────────────────────────────────
W_ANALYTIC  = 0.40
W_SOCIAL    = 0.30
W_MOMENTUM  = 0.20
W_VOL_SURGE = 0.10
W_NEW_BONUS = 0.08


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(v)))


# ── Normalisation individuelle ─────────────────────────────────────────────────

def _norm_analytic(raw: float) -> float:
    """
    analytic_score est non borné (typiquement 0–80 en pratique).
    On mappe sur [0,100] avec une courbe douce qui discrimine bien
    dans la zone 0–40 sans saturer trop vite.
    """
    # tanh-like : score de 20 → ~63, score de 40 → ~86, score de 60 → ~95
    import math
    return _clamp(100 * (1 - math.exp(-raw / 25)), 0, 100)


def _norm_social(token: Token) -> float:
    """
    Score social normalisé, robuste aux sources manquantes.

    Principe : chaque source contribue indépendamment, normalisée sur
    sa plage typique. Les sources en erreur (-1) contribuent 0 MAIS
    ne pénalisent pas — elles sont simplement absentes.
    On retourne un score [0,100] basé uniquement sur ce qui est dispo.
    """
    contributions = []

    g  = token.trend_score
    rd = token.reddit_mentions
    yt = token.youtube_mentions

    # Google Trends [0–100] → contribution [0–100], poids 5
    if g >= 0:
        contributions.append((5, _clamp(g, 0, 100)))

    # Reddit [0–∞ en pratique 0–500] → normalise sur 300 comme "très actif"
    if rd >= 0:
        contributions.append((3, _clamp(rd / 3.0, 0, 100)))

    # YouTube [0–50 max via API] → normalise sur 50
    if yt >= 0:
        contributions.append((2, _clamp(yt / 0.5, 0, 100)))

    if not contributions:
        return 0.0

    total_w = sum(w for w, _ in contributions)
    weighted = sum(w * v for w, v in contributions)
    return _clamp(weighted / total_w)


def _norm_momentum(change_24h: float | None) -> float:
    """
    change_24h en % → [0, 100].
    +20% → 100, 0% → 50, -20% → 0.
    Symétrique autour de 50, saturé à ±20%.
    """
    if change_24h is None:
        return 50.0   # neutre si inconnu
    return _clamp(50.0 + change_24h * 2.5, 0, 100)


def _norm_vol_surge(token: Token) -> float:
    """
    Détecte un spike de volume inhabituel.

    On estime le volume "normal" via market_cap * 0.05 (rule of thumb :
    un token liquide tourne ~5% de sa market cap par jour).
    Un ratio volume_24h / volume_normal > 3 = score élevé.
    """
    v = token.volume_24h
    mc = token.market_cap

    if not v or not mc or mc <= 0:
        return 50.0   # neutre si données manquantes

    # Volume "normal" estimé
    expected_vol = mc * 0.05
    ratio = v / expected_vol   # 1.0 = normal, 3.0 = fort spike

    # Mapper ratio [0–5] → score [0–100]
    # ratio 0.5 → 25, ratio 1 → 40, ratio 3 → 85, ratio 5 → 100
    return _clamp(ratio / 5.0 * 100, 0, 100)


# ── Score final ────────────────────────────────────────────────────────────────

def compute_final_score(token: Token) -> float:
    """
    Calcule et assigne token.social_score + token.final_score.
    Retourne final_score.
    """
    social_norm = _norm_social(token)
    token.social_score = round(social_norm / 10, 3)  # stocker en [0,10] pour affichage

    analytic_norm = _norm_analytic(token.analytic_score)
    momentum_norm = _norm_momentum(token.change_24h)
    vol_norm      = _norm_vol_surge(token)

    score = (
        W_ANALYTIC  * analytic_norm +
        W_SOCIAL    * social_norm   +
        W_MOMENTUM  * momentum_norm +
        W_VOL_SURGE * vol_norm
    )
    # Pas besoin de diviser par la somme des poids car ils somment à 1.0

    # Bonus nouveau token
    if token.is_new:
        score = score + W_NEW_BONUS * (100 - score)

    token.final_score = round(_clamp(score), 2)
    return token.final_score


def rank_tokens(tokens: list[Token]) -> list[Token]:
    """Calcule les scores et trie par final_score décroissant."""
    for t in tokens:
        compute_final_score(t)
    tokens.sort(key=lambda t: t.final_score, reverse=True)
    return tokens