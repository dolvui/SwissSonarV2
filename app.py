"""
app.py — Main Streamlit entry point for the Crypto Dashboard.

Run with:   streamlit run app.py
"""
import time
import streamlit as st
import pandas as pd

# ── Page config — MUST be first Streamlit call ─────────────────────────────────
st.set_page_config(
    page_title="Crypto Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Internal imports ───────────────────────────────────────────────────────────
from core.token import Token
from core.swissborg import fetch_swissborg_tokens
from core.market_data import resolve_gecko_ids, fetch_market_data, fetch_token_history
from core.social_trends import enrich_social
from core.analysis import apply_analytic_score
from core.scoring import rank_tokens
from utils.cache import (
    is_cache_fresh, get_cached_tokens, get_known_ids,
    save_tokens, get_last_run_time,
)
from ui.token_detail import show_token_detail
from ui.pdf_export import build_pdf


# ── CSS theming ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .stApp { background-color: #fdfcfb; }
    .block-container { padding-top: 1.5rem; }
    h1, h2, h3 { color: #00d4ff !important; }
    .stMetric label { color: #888 !important; font-size: 0.8rem !important; }
    .stMetric [data-testid="stMetricValue"] { color: #ffffff !important; font-size: 1.3rem !important; }
    .new-badge { background:#00c853; color:#000; border-radius:4px;
                 padding:1px 6px; font-size:0.75rem; font-weight:700; }
    div[data-testid="stDataFrame"] { border: 1px solid #1e2130; border-radius: 8px; }
</style>
""", unsafe_allow_html=True)


# ── Data pipeline ──────────────────────────────────────────────────────────────

def _tokens_to_df(tokens: list) -> pd.DataFrame:
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
            "trend_score":    t.trend_score,
            "reddit":         t.reddit_mentions,
            "youtube":        t.youtube_mentions,
            "analytic_score": t.analytic_score,
            "social_score":   t.social_score,
            "final_score":    t.final_score,
            "is_new":         t.is_new,
        })
    return pd.DataFrame(rows)


def run_full_pipeline(skip_social: bool = False) -> list:
    """Fetch everything fresh and return a ranked list of Token objects."""

    # known_ids from previous cache run — used to detect NEW tokens
    # On first ever run the cache is empty so known_ids = {} → every token is "new".
    # We handle this by only flagging is_new when the cache already had *some* data.
    raw_known = get_known_ids()
    first_run = len(raw_known) == 0

    with st.status("📡 Fetching SwissBorg token list…", expanded=True) as status:

        # ── 1. SwissBorg list ──────────────────────────────────────────────────
        tokens, used_fallback = fetch_swissborg_tokens()
        if used_fallback:
            st.warning("⚠️ SwissBorg scraping failed — using static fallback list.")
        st.write(f"✅ {len(tokens)} tokens found.")

        # ── 2. CoinGecko IDs ──────────────────────────────────────────────────
        status.update(label="🔍 Resolving CoinGecko IDs…")
        tokens = resolve_gecko_ids(tokens)
        resolved = [t for t in tokens if t.gecko_id]
        st.write(f"✅ {len(resolved)}/{len(tokens)} IDs resolved.")

        # Mark new tokens — skip on first run (everything would be "new")
        if not first_run:
            for t in tokens:
                if t.gecko_id and t.gecko_id not in raw_known:
                    t.is_new = True
            new_count = sum(1 for t in tokens if t.is_new)
            if new_count:
                st.info(f"🆕 {new_count} newly listed token(s) detected.")

        # ── 3. Market data (single batched call) ──────────────────────────────
        status.update(label="💹 Fetching market data from CoinGecko…")
        tokens = fetch_market_data(tokens)
        st.write("✅ Market data fetched.")

        # ── 4. Analytic scores (per-token historical data) ────────────────────
        status.update(label="📈 Computing analytic scores from price history…")
        analytic_bar = st.progress(0, text="Starting…")
        valid = [t for t in tokens if t.gecko_id]
        for i, t in enumerate(valid):
            try:
                cg_data = fetch_token_history(t.gecko_id, days=30)
                apply_analytic_score(t, cg_data)
            except Exception as e:
                print(f"[Analytic] {t.name}: {e}")
                t.analytic_score = 0.0
            analytic_bar.progress(
                (i + 1) / max(len(valid), 1),
                text=f"Analysing {t.name} ({i+1}/{len(valid)})…"
            )
            time.sleep(1.3)   # stay under CoinGecko free-tier rate limit
        analytic_bar.empty()
        st.write(f"✅ Analytic scores computed for {len(valid)} tokens.")

        # ── 5. Social trends (optional — slow) ────────────────────────────────
        if not skip_social:
            status.update(label="📱 Collecting social signals (this takes ~2 min)…")
            soc_bar = st.progress(0)
            def _cb(i, total, name):
                soc_bar.progress(i / max(total, 1), text=f"Social: {name}…")
            tokens = enrich_social(tokens, progress_cb=_cb)
            soc_bar.empty()
            st.write("✅ Social signals collected.")
        else:
            st.write("⏭️ Social signals skipped (Quick Refresh).")

        # ── 6. Final score & ranking ───────────────────────────────────────────
        status.update(label="🧮 Computing final scores…")
        tokens = rank_tokens(tokens)
        st.write(f"✅ All {len(tokens)} tokens ranked.")

        status.update(label="✅ Done!", state="complete", expanded=False)

    save_tokens(tokens)
    return tokens


def load_tokens() -> list:
    """Load from cache (already validated fresh by caller)."""
    cached = get_cached_tokens()
    if not cached:
        return []
    tokens = [Token.from_dict(d) for d in cached]
    tokens.sort(key=lambda t: t.final_score, reverse=True)
    return tokens


# ── Session state init ─────────────────────────────────────────────────────────

if "tokens" not in st.session_state:
    if is_cache_fresh():
        st.session_state["tokens"] = load_tokens()
    else:
        st.session_state["tokens"] = []

if "show_analysis" not in st.session_state:
    st.session_state["show_analysis"] = None   # (name, gecko_id, ticker, days)


# ── Header ─────────────────────────────────────────────────────────────────────
st.title("📊 Crypto Dashboard")
last_run = get_last_run_time()
if last_run:
    st.caption(f"Last data fetch: {last_run[:19].replace('T', ' ')} UTC")
else:
    st.caption("No data yet — click **Full Refresh** or **Quick Refresh** to load data.")

st.divider()

# ── Action bar ─────────────────────────────────────────────────────────────────
a1, a2, a3, _spacer = st.columns([2, 2, 2, 4])

with a1:
    if st.button("🔄 Full Refresh", help="SwissBorg list + market data + analytic scores + social trends"):
        tokens = run_full_pipeline(skip_social=False)
        st.session_state["tokens"] = tokens
        st.session_state["show_analysis"] = None
        st.rerun()

with a2:
    if st.button("⚡ Quick Refresh", help="Market data + analytic scores only (no social API calls)"):
        tokens = run_full_pipeline(skip_social=True)
        st.session_state["tokens"] = tokens
        st.session_state["show_analysis"] = None
        st.rerun()

with a3:
    tokens_for_pdf = st.session_state.get("tokens", [])
    if tokens_for_pdf:
        pdf_bytes = build_pdf(tokens_for_pdf, last_run=get_last_run_time())
        st.download_button(
            label="📄 Export PDF",
            data=pdf_bytes,
            file_name=f"crypto_report_{time.strftime('%Y%m%d_%H%M')}.pdf",
            mime="application/pdf",
        )
    else:
        st.button("📄 Export PDF", disabled=True, help="Run a refresh first")

# ── Main content guard ─────────────────────────────────────────────────────────
tokens = st.session_state.get("tokens", [])

if not tokens:
    st.info("👆 No data loaded yet. Click **Full Refresh** to start (takes ~3 min) or **Quick Refresh** to skip social signals (~1 min).")
    st.stop()

df = _tokens_to_df(tokens)

# ── KPI metrics ────────────────────────────────────────────────────────────────
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Total Tokens", len(df))

valid_scores = df[df["final_score"].notna() & (df["final_score"] > 0)]
if not valid_scores.empty:
    top_row = df.loc[df["final_score"].idxmax()]
    m2.metric("🏆 Top Score", top_row["name"], f"{top_row['final_score']:.1f}/100")

    pos_mask = df["24h_%"].notna() & (df["24h_%"] > 0)
    if pos_mask.any():
        best = df.loc[df.loc[pos_mask, "24h_%"].idxmax()]
        m3.metric("📈 Best 24h", best["name"], f"+{best['24h_%']:.2f}%")

    neg_mask = df["24h_%"].notna() & (df["24h_%"] < 0)
    if neg_mask.any():
        worst = df.loc[df.loc[neg_mask, "24h_%"].idxmin()]
        m4.metric("📉 Worst 24h", worst["name"], f"{worst['24h_%']:.2f}%")

new_tokens_df = df[df["is_new"] == True]
m5.metric("🆕 New Tokens", len(new_tokens_df))
if not new_tokens_df.empty:
    names = ", ".join(new_tokens_df["name"].tolist()[:5])
    st.info(f"🆕 **Newly listed on SwissBorg:** {names}")

st.divider()

# ── Filters ────────────────────────────────────────────────────────────────────
st.subheader("Token List")

f1, f2, f3 = st.columns([3, 2, 2])
with f1:
    search = st.text_input("🔍 Search by name or ticker", placeholder="bitcoin, BTC…").strip().lower()
with f2:
    categories = ["All"] + sorted(df["category"].dropna().unique().tolist())
    cat_filter = st.selectbox("Category", categories)
with f3:
    # Default min_score to 0 so nothing is hidden on first load
    min_score = st.slider("Min final score", 0, 100, 0)

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

# ── Table ──────────────────────────────────────────────────────────────────────
display_cols = ["name", "ticker", "category", "price_usd", "24h_%",
                "market_cap", "volume_24h", "analytic_score", "social_score",
                "final_score", "is_new"]

st.dataframe(
    filtered[display_cols].rename(columns={
        "name": "Name", "ticker": "Ticker", "category": "Category",
        "price_usd": "Price (USD)", "24h_%": "24h %",
        "market_cap": "Market Cap", "volume_24h": "Volume 24h",
        "analytic_score": "Analytic", "social_score": "Social",
        "final_score": "Score ▼", "is_new": "New?",
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

# ── Deep analysis panel ────────────────────────────────────────────────────────
st.subheader("🔬 Deep Analysis")

display_options = {
    f"{row['name']} ({row['ticker']})": (row["gecko_id"], row["ticker"])
    for _, row in filtered.iterrows()
    if row.get("gecko_id")
}

if not display_options:
    st.warning("No tokens with resolved CoinGecko IDs in the current filter.")
else:
    sel_col, days_col, btn_col = st.columns([4, 2, 1])

    with sel_col:
        selected_display = st.selectbox("Select token", list(display_options.keys()))
    with days_col:
        days = st.select_slider("History (days)", options=[7, 14, 30, 60, 90, 180], value=90)
    with btn_col:
        st.write("")
        analyse_clicked = st.button("🔎 Analyse", type="primary")

    if analyse_clicked and selected_display:
        gecko_id, ticker = display_options[selected_display]
        token_name = selected_display.split(" (")[0]
        st.session_state["show_analysis"] = (token_name, gecko_id, ticker, days)

    if st.session_state.get("show_analysis"):
        t_name, g_id, tick, d = st.session_state["show_analysis"]
        show_token_detail(t_name, g_id, tick, days=d)