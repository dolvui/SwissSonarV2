"""
app.py — Streamlit dashboard (lecture seule du cache).

Le pipeline lourd tourne en local via : python refresh.py
Le cache.json résultant est poussé sur le repo et lu ici.
"""
import time
import streamlit as st
import pandas as pd

st.set_page_config(
    page_title="Crypto Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

from core.token import Token
from utils.cache import is_cache_fresh, get_cached_tokens, get_last_run_time
from ui.token_detail import show_token_detail
from ui.pdf_export import build_pdf

# ── CSS ────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .stApp { background-color: #0f1117; }
    .block-container { padding-top: 1.5rem; }
    h1, h2, h3 { color: #00d4ff !important; }
    .stMetric label { color: #888 !important; font-size: 0.8rem !important; }
    .stMetric [data-testid="stMetricValue"] { color: #ffffff !important; font-size: 1.3rem !important; }
    div[data-testid="stDataFrame"] { border: 1px solid #1e2130; border-radius: 8px; }
</style>
""", unsafe_allow_html=True)


# ── Load cache ─────────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)   # re-lit le cache toutes les 5 min au cas où il aurait été mis à jour
def _load() -> list[dict]:
    return get_cached_tokens() or []


def _to_df(cached: list[dict]) -> tuple[list, pd.DataFrame]:
    tokens = [Token.from_dict(d) for d in cached]
    tokens.sort(key=lambda t: t.final_score, reverse=True)
    rows = []
    for t in tokens:
        rows.append({
            "gecko_id":       t.gecko_id,
            "name":           t.name,
            "ticker":         t.ticker,
            "category":       t.category,
            "price_usd":      t.current_price,
            "24h_%":          round(t.change_24h, 2) if t.change_24h is not None else None,
            "market_cap":     t.market_cap,
            "volume_24h":     t.volume_24h,
            "analytic_score": round(t.analytic_score, 2),
            "social_score":   round(t.social_score, 2),
            "final_score":    t.final_score,
            "is_new":         t.is_new,
        })
    return tokens, pd.DataFrame(rows)


# ── Session state ──────────────────────────────────────────────────────────────
if "show_analysis" not in st.session_state:
    st.session_state["show_analysis"] = None

# ── Header ─────────────────────────────────────────────────────────────────────
st.title("📊 Crypto Dashboard")
last_run = get_last_run_time()
if last_run:
    fresh = is_cache_fresh()
    freshness = "🟢 fresh" if fresh else "🟠 stale (>24h)"
    st.caption(f"Cache: {last_run[:19].replace('T', ' ')} UTC — {freshness}")
else:
    st.caption("⚠️ No cache found. Run `python refresh.py` locally and push `cache.json`.")

st.divider()

# ── Load data ──────────────────────────────────────────────────────────────────
cached = _load()

if not cached:
    st.warning("""
    **No data available.**

    Run the refresh script locally to populate the cache:
    ```bash
    python refresh.py --no-social   # fast (~2 min)
    python refresh.py               # full with social signals (~10 min)
    ```
    Then push `cache.json` to your repository.
    """)
    st.stop()

tokens, df = _to_df(cached)

# ── Actions ────────────────────────────────────────────────────────────────────
a1, a2, _sp = st.columns([2, 2, 6])

with a1:
    # Permet de forcer un rechargement du cache depuis le disque sans redémarrer l'app
    if st.button("🔃 Reload cache", help="Re-read cache.json from disk"):
        st.cache_data.clear()
        st.rerun()

with a2:
    if tokens:
        pdf_bytes = build_pdf(tokens, last_run=last_run)
        st.download_button(
            label="📄 Export PDF",
            data=pdf_bytes,
            file_name=f"crypto_report_{time.strftime('%Y%m%d_%H%M')}.pdf",
            mime="application/pdf",
        )

if not is_cache_fresh():
    st.warning("⚠️ Cache is older than 24h. Run `python refresh.py` locally and push `cache.json` to update.")

# ── KPIs ───────────────────────────────────────────────────────────────────────
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Total Tokens", len(df))

if not df.empty and df["final_score"].notna().any():
    top = df.loc[df["final_score"].idxmax()]
    m2.metric("🏆 Top Score", top["name"], f"{top['final_score']:.1f}/100")

    pos = df[df["24h_%"].notna() & (df["24h_%"] > 0)]
    if not pos.empty:
        best = df.loc[pos["24h_%"].idxmax()]
        m3.metric("📈 Best 24h", best["name"], f"+{best['24h_%']:.2f}%")

    neg = df[df["24h_%"].notna() & (df["24h_%"] < 0)]
    if not neg.empty:
        worst = df.loc[neg["24h_%"].idxmin()]
        m4.metric("📉 Worst 24h", worst["name"], f"{worst['24h_%']:.2f}%")

new_df = df[df["is_new"] == True]
m5.metric("🆕 New Tokens", len(new_df))
if not new_df.empty:
    st.info(f"🆕 **Newly listed on SwissBorg:** {', '.join(new_df['name'].tolist()[:6])}")

st.divider()

# ── Filters ────────────────────────────────────────────────────────────────────
st.subheader("Token List")

f1, f2, f3 = st.columns([3, 2, 2])
with f1:
    search = st.text_input("🔍 Name or ticker", placeholder="bitcoin, BTC…").strip().lower()
with f2:
    cats = ["All"] + sorted(df["category"].dropna().unique().tolist())
    cat_filter = st.selectbox("Category", cats)
with f3:
    min_score = st.slider("Min score", 0, 100, 0)

filtered = df.copy()
if search:
    mask = (
        filtered["name"].str.lower().str.contains(search, na=False) |
        filtered["ticker"].str.lower().str.contains(search, na=False)
    )
    filtered = filtered[mask]
if cat_filter != "All":
    filtered = filtered[filtered["category"] == cat_filter]
filtered = filtered[filtered["final_score"] >= min_score]

st.caption(f"Showing {len(filtered)} of {len(df)} tokens")

st.dataframe(
    filtered[[
        "name","ticker","category","price_usd","24h_%",
        "market_cap","volume_24h","analytic_score","social_score","final_score","is_new"
    ]].rename(columns={
        "name":"Name","ticker":"Ticker","category":"Category",
        "price_usd":"Price (USD)","24h_%":"24h %",
        "market_cap":"Market Cap","volume_24h":"Volume 24h",
        "analytic_score":"Analytic","social_score":"Social",
        "final_score":"Score ▼","is_new":"New?",
    }),
    use_container_width=True,
    hide_index=True,
    column_config={
        "Price (USD)": st.column_config.NumberColumn(format="$%.6f"),
        "Market Cap":  st.column_config.NumberColumn(format="$%.0f"),
        "Volume 24h":  st.column_config.NumberColumn(format="$%.0f"),
        "24h %":       st.column_config.NumberColumn(format="%.2f%%"),
        "Analytic":    st.column_config.NumberColumn(format="%.2f"),
        "Social":      st.column_config.NumberColumn(format="%.2f"),
        "Score ▼":     st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
        "New?":        st.column_config.CheckboxColumn(),
    },
    height=480,
)

st.divider()

# ── Deep analysis ──────────────────────────────────────────────────────────────
st.subheader("🔬 Deep Analysis")

options = {
    f"{row['name']} ({row['ticker']})": (row["gecko_id"], row["ticker"])
    for _, row in filtered.iterrows()
    if row.get("gecko_id")
}

if not options:
    st.warning("No tokens with resolved CoinGecko IDs in current filter.")
else:
    c1, c2, c3 = st.columns([4, 2, 1])
    with c1:
        selected = st.selectbox("Select token", list(options.keys()))
    with c2:
        days = st.select_slider("History (days)", [7, 14, 30, 60, 90, 180], value=90)
    with c3:
        st.write("")
        clicked = st.button("🔎 Analyse", type="primary")

    if clicked:
        gecko_id, ticker = options[selected]
        st.session_state["show_analysis"] = (selected.split(" (")[0], gecko_id, ticker, days)

    if st.session_state.get("show_analysis"):
        name, gid, tick, d = st.session_state["show_analysis"]
        # L'analyse individuelle est légère (1 seul appel CoinGecko) → OK dans l'UI
        show_token_detail(name, gid, tick, days=d)


# ── Predictions section (ajout en bas de app.py) ──────────────────────────────
st.divider()
st.subheader("📈 Prédictions 7 jours")

from core.prediction import predict_top_tokens
from core.market_data import fetch_token_history
from core.analysis import analyse_token as _analyse
from ui.prediction_panel import show_predictions

if st.button("🔮 Générer prédictions Top 15", help="Fetch l'historique des 15 premiers tokens et calcule les prédictions"):
    top_tokens = tokens[:15]
    reports = {}
    pred_bar = st.progress(0, text="Fetching histories…")
    for i, t in enumerate(top_tokens):
        if t.gecko_id:
            try:
                cg = fetch_token_history(t.gecko_id, days=60)
                reports[t.gecko_id] = _analyse(cg)
            except Exception:
                reports[t.gecko_id] = {}
        pred_bar.progress((i+1)/len(top_tokens), text=f"{t.name}…")
        import time as _t; _t.sleep(1.3)
    pred_bar.empty()
    preds = predict_top_tokens(top_tokens, reports, top_n=15)
    st.session_state["predictions"] = preds
    st.rerun()

if st.session_state.get("predictions"):
    show_predictions(st.session_state["predictions"])
