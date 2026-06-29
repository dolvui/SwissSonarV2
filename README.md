# 📊 Crypto Dashboard

Dashboard Streamlit pour tracker les tokens SwissBorg avec signaux sociaux,
analyse technique et scoring composite.

## Architecture du workflow

```
Machine locale                      Git / Streamlit Cloud
──────────────────────────────      ─────────────────────
python refresh.py          ──→      git push cache.json
  ↓ pas de timeout                    ↓ app lit le cache
  ↓ tourne en fond                    ↓ affichage immédiat
  └─ écrit cache.json
```

L'app Streamlit ne fait **jamais** tourner le pipeline lourd.
Elle lit uniquement `cache.json` et affiche.

## Installation

```bash
git clone <repo>
cd crypto_dashboard
pip install -r requirements.txt
```

### Clés API — `.streamlit/secrets.toml`

Copier `.streamlit/secrets.toml.template` → `.streamlit/secrets.toml` :

```toml
[reddit]
client_id     = "..."   # reddit.com/prefs/apps → créer une app "script"
client_secret = "..."
user_agent    = "crypto-dashboard/1.0 by u/ton_pseudo"

[youtube]
api_key = "..."         # console.cloud.google.com → YouTube Data API v3
```

> Google Trends (pytrends) ne nécessite **aucune clé**.

## Mise à jour du cache (local)

```bash
# Rapide (~2 min) — market data + analytic scores, sans social
python refresh.py --no-social

# Complet (~10 min) — tout inclus
python refresh.py

# Market data seulement (~30 sec)
python refresh.py --no-social --no-analytic

# Puis pousser le cache
git add cache.json
git commit -m "chore: refresh cache $(date +%Y-%m-%d)"
git push
```

Streamlit Cloud récupère automatiquement le nouveau `cache.json`
au prochain chargement de page (ou via le bouton **Reload cache**).

## Lancer l'app

```bash
streamlit run app.py
```

## Structure des fichiers

```
crypto_dashboard/
├── app.py                      # Streamlit (lecture cache uniquement)
├── refresh.py                  # Script local de mise à jour
├── requirements.txt
├── cache.json                  # Généré par refresh.py — à commiter
│
├── core/
│   ├── token.py                # Dataclass Token
│   ├── swissborg.py            # Scraper SwissBorg (requests + BS4)
│   ├── market_data.py          # CoinGecko API
│   ├── social_trends.py        # Google Trends + Reddit + YouTube
│   ├── analysis.py             # Analyse technique (RSI, BB, slope…)
│   └── scoring.py              # Score final [0–100]
│
├── ui/
│   ├── token_detail.py         # Panel analyse détaillée (Plotly)
│   └── pdf_export.py           # Export PDF (reportlab)
│
└── utils/
    └── cache.py                # Lecture/écriture cache JSON (TTL 24h)
```

## Scores

| Composante | Poids | Ce que ça mesure |
|------------|-------|-----------------|
| Analytic   | 35%   | Delta prix, volatilité volume, slope, R² |
| Social     | 35%   | Google Trends + Reddit + YouTube |
| Momentum   | 20%   | Variation 24h |
| Bonus new  | +10%  | Token nouvellement listé sur SwissBorg |

## Automatisation (optionnel)

Pour éviter de lancer `refresh.py` manuellement, tu peux créer
un **GitHub Action** qui tourne toutes les 24h :

```yaml
# .github/workflows/refresh.yml
name: Refresh cache
on:
  schedule:
    - cron: '0 6 * * *'   # tous les jours à 6h UTC
  workflow_dispatch:

jobs:
  refresh:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install -r requirements.txt
      - run: python refresh.py --no-social
        env:
          REDDIT_CLIENT_ID:     ${{ secrets.REDDIT_CLIENT_ID }}
          REDDIT_CLIENT_SECRET: ${{ secrets.REDDIT_CLIENT_SECRET }}
          REDDIT_USER_AGENT:    "crypto-dashboard/1.0"
          GOOGLE_KEY:           ${{ secrets.GOOGLE_KEY }}
      - uses: stefanzweifel/git-auto-commit-action@v5
        with:
          commit_message: "chore: auto-refresh cache"
          file_pattern: cache.json
```
