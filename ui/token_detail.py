"""
ui/token_detail.py — Streamlit panel for in-depth token analysis.
Called from app.py when user clicks "Analyse".
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from core.market_data import fetch_token_history
from core.analysis import analyse_token


def _price_chart(report: dict, token_name: str) -> go.Figure:
    prices  = report["prices"]
    volumes = report["volumes"]

    if not prices:
        return go.Figure()

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        row_heights=[0.7, 0.3],
        vertical_spacing=0.05,
    )

    x = list(range(len(prices)))

    # Price line
    fig.add_trace(
        go.Scatter(x=x, y=prices, mode="lines", name="Price",
                   line=dict(color="#00d4ff", width=1.5)),
        row=1, col=1
    )

    # Bollinger bands
    period = 20
    if len(prices) >= period:
        mid = pd.Series(prices).rolling(period).mean()
        std = pd.Series(prices).rolling(period).std()
        upper = mid + 2 * std
        lower = mid - 2 * std
        fig.add_trace(go.Scatter(x=x, y=upper, mode="lines", name="BB Upper",
                                 line=dict(color="#ff9800", width=0.8, dash="dot")), row=1, col=1)
        fig.add_trace(go.Scatter(x=x, y=lower, mode="lines", name="BB Lower",
                                 line=dict(color="#ff9800", width=0.8, dash="dot"),
                                 fill="tonexty", fillcolor="rgba(255,152,0,0.05)"), row=1, col=1)
        fig.add_trace(go.Scatter(x=x, y=mid, mode="lines", name="BB Mid",
                                 line=dict(color="#888", width=0.6, dash="dash")), row=1, col=1)

    # Volume bars
    if volumes:
        bar_colors = ["#00c853" if i == 0 or volumes[i] >= volumes[i-1] else "#ff1744"
                      for i in range(len(volumes))]
        fig.add_trace(
            go.Bar(x=list(range(len(volumes))), y=volumes,
                   name="Volume", marker_color=bar_colors, opacity=0.7),
            row=2, col=1
        )

    fig.update_layout(
        title=f"{token_name} — Price & Volume",
        paper_bgcolor="#0f1117",
        plot_bgcolor="#0f1117",
        font=dict(color="#aaaaaa", size=11),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
        height=480,
        margin=dict(l=10, r=10, t=40, b=10),
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=True, gridcolor="#1e2130"),
        xaxis2=dict(showgrid=False),
        yaxis2=dict(showgrid=True, gridcolor="#1e2130"),
    )
    return fig


def show_token_detail(token_name: str, gecko_id: str, ticker: str, days: int = 90):
    """Render full analysis panel for one token."""
    st.subheader(f"🔬 Analysis — {token_name} ({ticker})")

    with st.spinner("Fetching historical data…"):
        cg_data = fetch_token_history(gecko_id, days=days)

    if not cg_data:
        st.error("Could not fetch historical data. CoinGecko may be rate-limiting — try again in a minute.")
        return

    report = analyse_token(cg_data)

    # ── Metric row ─────────────────────────────────────────────────────────────
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Signal", report["signal"])
    m2.metric("Δ Price (period)", f"{report['delta_price_pct']:+.2f}%")
    m3.metric("RSI (14)", f"{report['rsi']:.1f}" if report["rsi"] else "N/A")
    m4.metric("Slope R²", f"{report['r2']:.3f}")
    m5.metric("Near Peak?", "Yes 🏔️" if report["near_peak"] else "No")

    # ── Chart ──────────────────────────────────────────────────────────────────
    st.plotly_chart(_price_chart(report, token_name), use_container_width=True)

    # ── Detailed stats ─────────────────────────────────────────────────────────
    with st.expander("📋 Detailed statistics", expanded=False):
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**Trend analysis**")
            st.write(f"Trend: {report['trend']}")
            st.write(f"Price slope: `{report['slope']}`")
            st.write(f"R² (fit quality): `{report['r2']}`")
            st.write(f"Vol/price corr: `{report['corr_price_vol']}`")
            st.write(f"Relative volume volatility: `{report['rel_volatility']:.1f}%`")
        with col_b:
            st.markdown("**Indicators**")
            st.write(f"RSI(14): `{report['rsi']}` → {report['rsi_note']}")
            st.write(f"Bollinger: {report['bb_note']}")
            st.write(f"Upper band: `{report['bb_upper']}`")
            st.write(f"Lower band: `{report['bb_lower']}`")
            st.write(f"Analytic score: `{report['analytic_score']}`")
