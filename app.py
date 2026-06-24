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
from core.market_data import resolve_gecko_ids, fetch_market_data
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
    .stApp { background-color: #2d3345; }
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

def _tokens_to_df(tokens: list[Token]) -> pd.DataFrame:
    rows = []
    for t in tokens:
        rows.append({
            "gecko_id":      t.gecko_id,
            "name":          t.name,
            "ticker":        t.ticker,
            "category":      t.category,
            "price_usd":     t.current_price,
            "24h_%":         round(t.change_24h, 2) if t.change_24h else None,
            "market_cap":    t.market_cap,
            "volume_24h":    t.volume_24h,
            "trend_score":   t.trend_score,
            "reddit":        t.reddit_mentions,
            "youtube":       t.youtube_mentions,
            "analytic_score":t.analytic_score,
            "social_score":  t.social_score,
            "final_score":   t.final_score,
            "is_new":        t.is_new,
        })
    return pd.DataFrame(rows)


def run_full_pipeline(skip_social: bool = False) -> list[Token]:
    """Fetch everything fresh and return a ranked list of Token objects."""

    known_ids = get_known_ids()

    # 1 — SwissBorg list
    with st.status("📡 Fetching SwissBorg token list…", expanded=True) as status:
        tokens, used_fallback = fetch_swissborg_tokens()
        if used_fallback:
            st.warning("⚠️ SwissBorg scraping failed — using static fallback list.")
        st.write(f"✅ {len(tokens)} tokens found.")

        # 2 — CoinGecko IDs
        status.update(label="🔍 Resolving CoinGecko IDs…")
        tokens = resolve_gecko_ids(tokens)
        resolved = sum(1 for t in tokens if t.gecko_id)
        st.write(f"✅ {resolved}/{len(tokens)} IDs resolved.")

        # Mark new tokens
        for t in tokens:
            if t.gecko_id and t.gecko_id not in known_ids:
                t.is_new = True

        # 3 — Market data
        status.update(label="💹 Fetching market data from CoinGecko…")
        tokens = fetch_market_data(tokens)
        st.write("✅ Market data fetched.")

        # 4 — Social trends (optional, slow)
        if not skip_social:
            status.update(label="📱 Collecting social signals (this takes ~1 min)…")
            progress = st.progress(0)
            def _cb(i, total, name):
                progress.progress(i / total, text=f"{name}…")
            tokens = enrich_social(tokens, progress_cb=_cb)
            progress.empty()
            st.write("✅ Social signals collected.")
        else:
            st.write("⏭️ Social signals skipped.")

        # 5 — Scores
        status.update(label="🧮 Computing scores…")
        tokens = rank_tokens(tokens)
        st.write("✅ Scores computed.")

        status.update(label="✅ Done!", state="complete", expanded=False)

    save_tokens(tokens)
    return tokens


def load_tokens() -> list[Token]:
    """Load from cache or trigger pipeline."""
    cached = get_cached_tokens()
    if cached:
        tokens = [Token.from_dict(d) for d in cached]
        # Re-sort in case cache is unordered
        tokens.sort(key=lambda t: t.final_score, reverse=True)
        return tokens
    return []


# ── Session state init ─────────────────────────────────────────────────────────

if "tokens" not in st.session_state:
    if is_cache_fresh():
        st.session_state["tokens"] = load_tokens()
    else:
        st.session_state["tokens"] = []

if "show_analysis" not in st.session_state:
    st.session_state["show_analysis"] = None   # (token_name, gecko_id, ticker)


# ── Header ─────────────────────────────────────────────────────────────────────
col_title, col_badge = st.columns([6, 1])
with col_title:
    st.title("📊 Crypto Dashboard")
    last_run = get_last_run_time()
    if last_run:
        st.caption(f"Last data fetch: {last_run[:19].replace('T', ' ')} UTC")
    else:
        st.caption("No data yet — click **Refresh** to fetch.")

st.divider()

# ── Action bar ─────────────────────────────────────────────────────────────────
a1, a2, a3, a4 = st.columns([2, 2, 2, 4])

with a1:
    if st.button("🔄 Full Refresh", help="Fetch SwissBorg list, market data AND social trends"):
        tokens = run_full_pipeline(skip_social=False)
        st.session_state["tokens"] = tokens
        st.rerun()

with a2:
    if st.button("⚡ Quick Refresh", help="Market data only — no social trends (much faster)"):
        tokens = run_full_pipeline(skip_social=True)
        st.session_state["tokens"] = tokens
        st.rerun()

with a3:
    tokens = st.session_state.get("tokens", [])
    if tokens:
        pdf_bytes = build_pdf(tokens, last_run=get_last_run_time())
        st.download_button(
            label="📄 Export PDF",
            data=pdf_bytes,
            file_name=f"crypto_report_{time.strftime('%Y%m%d_%H%M')}.pdf",
            mime="application/pdf",
        )
    else:
        st.button("📄 Export PDF", disabled=True)

# ── Main content ───────────────────────────────────────────────────────────────
tokens = st.session_state.get("tokens", [])

if not tokens:
    st.info("No data loaded. Click **Full Refresh** or **Quick Refresh** to start.")
    st.stop()

df = _tokens_to_df(tokens)

# ── KPI metrics ────────────────────────────────────────────────────────────────
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Total Tokens", len(df))

if not df.empty and df["final_score"].notna().any():
    top_row = df.loc[df["final_score"].idxmax()]
    m2.metric("🏆 Top Score", f"{top_row['name']} ({top_row['final_score']:.0f}/100)")

    gainers_mask = df["24h_%"] > 0
    if gainers_mask.any():
        best = df.loc[df.loc[gainers_mask, "24h_%"].idxmax()]
        m3.metric("📈 Best 24h", f"{best['name']}", f"+{best['24h_%']:.2f}%")

    losers_mask = df["24h_%"] < 0
    if losers_mask.any():
        worst = df.loc[df.loc[losers_mask, "24h_%"].idxmin()]
        m4.metric("📉 Worst 24h", f"{worst['name']}", f"{worst['24h_%']:.2f}%")

new_tokens = df[df["is_new"] == True]
m5.metric("🆕 New Tokens", len(new_tokens))

if not new_tokens.empty:
    names = ", ".join(new_tokens["name"].tolist()[:5])
    st.info(f"🆕 **Newly listed on SwissBorg:** {names}")

st.divider()

# ── Token table with filters ───────────────────────────────────────────────────
st.subheader("Token List")

f1, f2, f3 = st.columns([3, 2, 2])
with f1:
    search = st.text_input("🔍 Search by name or ticker", placeholder="bitcoin, BTC…").strip().lower()
with f2:
    categories = ["All"] + sorted(df["category"].dropna().unique().tolist())
    cat_filter = st.selectbox("Category", categories)
with f3:
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

# Display columns (human-friendly)
display_cols = ["name", "ticker", "category", "price_usd", "24h_%",
                "market_cap", "volume_24h", "trend_score", "reddit",
                "youtube", "analytic_score", "final_score", "is_new"]

st.dataframe(
    filtered[display_cols].rename(columns={
        "name": "Name", "ticker": "Ticker", "category": "Category",
        "price_usd": "Price (USD)", "24h_%": "24h %",
        "market_cap": "Market Cap", "volume_24h": "Volume 24h",
        "trend_score": "Trend", "reddit": "Reddit",
        "youtube": "YouTube", "analytic_score": "Analytic",
        "final_score": "Score ▼", "is_new": "New?",
    }),
    use_container_width=True,
    hide_index=True,
    column_config={
        "Price (USD)": st.column_config.NumberColumn(format="$%.6f"),
        "Market Cap":  st.column_config.NumberColumn(format="$%.0f"),
        "Volume 24h":  st.column_config.NumberColumn(format="$%.0f"),
        "24h %":       st.column_config.NumberColumn(format="%.2f%%"),
        "Score ▼":     st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
        "New?":        st.column_config.CheckboxColumn(),
    },
    height=460,
)

st.divider()

# ── Token deep analysis ────────────────────────────────────────────────────────
st.subheader("🔬 Deep Analysis")

display_options = {
    f"{row['name']} ({row['ticker']})": (row['gecko_id'], row['ticker'])
    for _, row in filtered.iterrows()
    if row.get("gecko_id")
}

if not display_options:
    st.warning("No tokens with resolved CoinGecko IDs in current filter.")
else:
    sel_col, days_col, btn_col = st.columns([4, 2, 1])

    with sel_col:
        selected_display = st.selectbox("Select token", list(display_options.keys()))

    with days_col:
        days = st.select_slider("History (days)", options=[7, 14, 30, 60, 90, 180], value=90)

    with btn_col:
        st.write("")   # vertical align
        analyse_clicked = st.button("🔎 Analyse", type="primary")

    if analyse_clicked and selected_display:
        gecko_id, ticker = display_options[selected_display]
        token_name = selected_display.split(" (")[0]
        st.session_state["show_analysis"] = (token_name, gecko_id, ticker, days)

    if st.session_state["show_analysis"]:
        t_name, g_id, tick, d = st.session_state["show_analysis"]
        show_token_detail(t_name, g_id, tick, days=d)
