"""
refresh.py — Script local de mise à jour du cache.

Lance en dehors de Streamlit, sans timeout :
    python refresh.py              # full (market + analytic + social)
    python refresh.py --no-social  # market + analytic seulement (plus rapide)
    python refresh.py --no-analytic --no-social  # market data seul

Le résultat est écrit dans cache.json. Commite/pousse ce fichier
sur le repo pour que Streamlit Cloud le récupère.
"""
import argparse
import time
import sys
from pathlib import Path

# Ajouter le dossier racine au path
sys.path.insert(0, str(Path(__file__).parent))

from core.token import Token
from core.swissborg import fetch_swissborg_tokens
from core.market_data import resolve_gecko_ids, fetch_market_data, fetch_token_history
from core.social_trends import enrich_social
from core.analysis import apply_analytic_score
from core.scoring import rank_tokens
from utils.cache import get_known_ids, save_tokens, get_last_run_time


def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def run(skip_social: bool = False, skip_analytic: bool = False):
    log("═" * 60)
    log("  CRYPTO DASHBOARD — Local Refresh")
    log("═" * 60)

    raw_known = get_known_ids()
    first_run = len(raw_known) == 0
    if first_run:
        log("ℹ️  First run — no previous cache, 'is_new' flags disabled.")

    # ── 1. SwissBorg ──────────────────────────────────────────────────────────
    log("📡 Fetching SwissBorg token list…")
    tokens, used_fallback = fetch_swissborg_tokens()
    if used_fallback:
        log("⚠️  SwissBorg scraping failed → using static fallback list.")
    log(f"✅ {len(tokens)} tokens found.")

    # ── 2. CoinGecko IDs ──────────────────────────────────────────────────────
    log("🔍 Resolving CoinGecko IDs…")
    tokens = resolve_gecko_ids(tokens)
    resolved = [t for t in tokens if t.gecko_id]
    log(f"✅ {len(resolved)}/{len(tokens)} IDs resolved.")

    # Mark new tokens (skip on first run)
    if not first_run:
        for t in tokens:
            if t.gecko_id and t.gecko_id not in raw_known:
                t.is_new = True
        new_count = sum(1 for t in tokens if t.is_new)
        if new_count:
            new_names = [t.name for t in tokens if t.is_new]
            log(f"🆕 {new_count} new token(s): {', '.join(new_names)}")

    # ── 3. Market data ────────────────────────────────────────────────────────
    log("💹 Fetching market data (batched CoinGecko call)…")
    tokens = fetch_market_data(tokens)
    log("✅ Market data fetched.")

    # ── 4. Analytic scores ────────────────────────────────────────────────────
    if not skip_analytic:
        valid = [t for t in tokens if t.gecko_id]
        log(f"📈 Computing analytic scores for {len(valid)} tokens (≈{len(valid)*1.4:.0f}s)…")
        for i, t in enumerate(valid):
            try:
                cg_data = fetch_token_history(t.gecko_id, days=30)
                apply_analytic_score(t, cg_data)
                status = f"score={t.analytic_score:.2f}"
            except Exception as e:
                t.analytic_score = 0.0
                status = f"ERROR: {e}"
            print(f"  [{i+1:3d}/{len(valid)}] {t.name:<20} {status}", flush=True)
            time.sleep(1.3)   # CoinGecko free-tier rate limit
        log("✅ Analytic scores done.")
    else:
        log("⏭️  Analytic scores skipped.")

    # ── 5. Social signals ─────────────────────────────────────────────────────
    if not skip_social:
        log(f"📱 Collecting social signals for {len(tokens)} tokens (slow)…")
        def _cb(i, total, name):
            print(f"  [{i+1:3d}/{total}] Social: {name}", flush=True)
        tokens = enrich_social(tokens, progress_cb=_cb)
        log("✅ Social signals collected.")
    else:
        log("⏭️  Social signals skipped.")

    # ── 6. Score & rank ───────────────────────────────────────────────────────
    log("🧮 Computing final scores and ranking…")
    tokens = rank_tokens(tokens)

    log("─" * 60)
    log("🏆 Top 10 tokens:")
    for i, t in enumerate(tokens[:10], 1):
        new_flag = " 🆕" if t.is_new else ""
        log(f"  {i:2d}. {t.name:<20} score={t.final_score:.1f}  analytic={t.analytic_score:.2f}  24h={t.change_24h:+.2f}%{new_flag}" if t.change_24h else
            f"  {i:2d}. {t.name:<20} score={t.final_score:.1f}  analytic={t.analytic_score:.2f}{new_flag}")
    log("─" * 60)

    # ── 7. Save ───────────────────────────────────────────────────────────────
    log("💾 Saving to cache.json…")
    save_tokens(tokens)
    log(f"✅ {len(tokens)} tokens saved to cache.json")
    log("")
    log("👉 Next step: git add cache.json && git commit -m 'chore: refresh cache' && git push")
    log("═" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Crypto Dashboard — local cache refresh")
    parser.add_argument("--no-social",   action="store_true", help="Skip social signals (Reddit/YouTube/Trends)")
    parser.add_argument("--no-analytic", action="store_true", help="Skip analytic score computation")
    args = parser.parse_args()

    run(skip_social=args.no_social, skip_analytic=args.no_analytic)
