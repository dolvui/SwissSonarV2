# 📊 Crypto Dashboard

A Streamlit dashboard for tracking SwissBorg-listed crypto tokens with social trend signals, 
technical analysis, and a ranked scoring system.

## Features

- **SwissBorg token list** — scraped automatically (with static fallback)
- **CoinGecko market data** — price, market cap, 24h volume & change, batched API calls
- **Social signals** — Google Trends, Reddit mentions, YouTube video count (last 24h)
- **Technical analysis** — RSI, Bollinger Bands, slope/R², price-volume correlation
- **Composite score [0–100]** — analytic (35%) + social (35%) + momentum (20%) + new-token bonus (10%)
- **New token detection** — flags tokens appearing on SwissBorg for the first time
- **PDF export** — cover page, Top 10 bar chart, full ranked token table
- **Local JSON cache** — data persists between sessions, TTL = 24h (no database needed)

## Setup

```bash
git clone <repo>
cd crypto_dashboard
pip install -r requirements.txt
```

### API Keys

Copy `.streamlit/secrets.toml.template` → `.streamlit/secrets.toml` and fill in:

| Key | Where to get it |
|-----|----------------|
| `reddit.client_id` + `reddit.client_secret` | https://www.reddit.com/prefs/apps → create a "script" app |
| `reddit.user_agent` | Any string, e.g. `crypto-dashboard/1.0 by u/yourname` |
| `youtube.api_key` | https://console.cloud.google.com → YouTube Data API v3 |

> Google Trends (pytrends) requires **no API key**.

## Run

```bash
streamlit run app.py
```

## Architecture

```
crypto_dashboard/
├── app.py                      # Streamlit entry point
├── requirements.txt
├── cache.json                  # Auto-generated local cache
│
├── core/
│   ├── token.py                # Token dataclass
│   ├── swissborg.py            # SwissBorg scraper (requests + BS4)
│   ├── market_data.py          # CoinGecko API wrapper
│   ├── social_trends.py        # Google Trends + Reddit + YouTube
│   ├── analysis.py             # Technical analysis (RSI, BB, slope…)
│   └── scoring.py              # Final score computation
│
├── ui/
│   ├── token_detail.py         # Deep-analysis panel (Plotly charts)
│   └── pdf_export.py           # PDF report builder (reportlab)
│
└── utils/
    └── cache.py                # JSON cache read/write/TTL
```

## Scores explained

| Component | Weight | What it measures |
|-----------|--------|-----------------|
| Analytic score | 35% | Price delta, volume volatility, slope fit |
| Social score | 35% | Google Trends + Reddit + YouTube signals |
| Momentum | 20% | 24h price change |
| New-token bonus | +10% | Token newly listed on SwissBorg |

## Buttons

| Button | Action |
|--------|--------|
| 🔄 Full Refresh | Fetch SwissBorg list + market data + social signals (slow, ~1–2 min) |
| ⚡ Quick Refresh | Market data only — no social API calls (fast, ~10 sec) |
| 📄 Export PDF | Download ranked report PDF |
| 🔎 Analyse | Deep-dive chart + indicators for the selected token |

## Notes

- CoinGecko free tier: ~30 req/min. The pipeline batches calls and sleeps between chunks.
- SwissBorg's page is JS-rendered; if BS4 yields 0 tokens, the static fallback list is used automatically.
- Cache TTL is 24h (`utils/cache.py → TTL_HOURS`). Change to suit your update frequency.
