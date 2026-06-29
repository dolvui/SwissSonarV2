"""
ui/prediction_panel.py — Affichage des prédictions 7j pour le Top 15.
"""
import streamlit as st
import plotly.graph_objects as go
import pandas as pd


def _gain_color(pct: float) -> str:
    if pct >= 10:  return "#00c853"
    if pct >= 3:   return "#69f0ae"
    if pct >= 0:   return "#b9f6ca"
    if pct >= -5:  return "#ff8a65"
    return "#ff1744"


def _confidence_order(c: str) -> int:
    return {"🟢 High": 0, "🟡 Medium": 1, "🔴 Low": 2}.get(c, 3)


def show_predictions(predictions: list[dict]):
    """
    Affiche le tableau de prédictions + graphique bulle score vs gain.
    predictions : liste retournée par core.prediction.predict_top_tokens()
    """
    if not predictions:
        st.info("Pas encore de prédictions — lance une analyse.")
        return

    st.subheader("📈 Prédictions 7 jours — Top tokens")
    st.caption(
        "Estimation technique basée sur ATR, Bollinger Bands, RSI et slope. "
        "**Pas un conseil financier.** Crypto = risque élevé."
    )

    # ── Tableau principal ──────────────────────────────────────────────────────
    rows = []
    for p in predictions:
        gain = p["expected_gain_pct"]
        arrow = "▲" if gain > 0 else "▼"
        rows.append({
            "Token":        f"{p['name']} ({p['ticker']})",
            "Score":        p["final_score"],
            "Prix actuel":  p["current_price"],
            "Gain estimé":  gain,
            "Prix cible":   p["target_price"],
            "Confiance":    p["confidence"],
            "ATR 14j (%)":  p.get("atr_pct", 0),
            "BB headroom":  p.get("bb_headroom_pct", 0),
            "Raison":       p["reasoning"],
            "Nouveau?":     "🆕" if p.get("is_new") else "",
        })

    df = pd.DataFrame(rows)

    # Highlight via column_config
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Score":       st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.1f"),
            "Prix actuel": st.column_config.NumberColumn("Prix actuel", format="$%.6f"),
            "Gain estimé": st.column_config.NumberColumn("Gain estimé 7j", format="%.2f%%"),
            "Prix cible":  st.column_config.NumberColumn("Prix cible", format="$%.6f"),
            "ATR 14j (%)": st.column_config.NumberColumn("ATR 14j", format="%.2f%%"),
            "BB headroom": st.column_config.NumberColumn("BB headroom", format="%.2f%%"),
        },
        height=min(60 + len(predictions) * 38, 580),
    )

    # ── Graphique : Score vs Gain estimé ──────────────────────────────────────
    st.markdown("**Score de confiance vs Gain estimé** — les tokens intéressants sont en haut à droite")

    fig = go.Figure()

    for p in predictions:
        gain   = p["expected_gain_pct"]
        score  = p["final_score"]
        color  = _gain_color(gain)
        conf   = p["confidence"]
        # Taille de la bulle = ATR (volatilité)
        size   = max(p.get("atr_pct", 2) * 6, 12)

        hover = (
            f"<b>{p['name']} ({p['ticker']})</b><br>"
            f"Score: {score:.1f}/100<br>"
            f"Gain estimé: {gain:+.2f}%<br>"
            f"Prix cible: ${p['target_price']:.6f}<br>"
            f"Confiance: {conf}<br>"
            f"ATR: {p.get('atr_pct', 0):.2f}%<br>"
            f"<i>{p['reasoning'][:80]}</i>"
        )

        fig.add_trace(go.Scatter(
            x=[score],
            y=[gain],
            mode="markers+text",
            marker=dict(size=size, color=color, opacity=0.85,
                        line=dict(color="#ffffff", width=1)),
            text=[p["ticker"]],
            textposition="top center",
            textfont=dict(size=9, color="#cccccc"),
            hovertemplate=hover + "<extra></extra>",
            name=p["name"],
            showlegend=False,
        ))

    # Quadrants
    fig.add_hline(y=0,  line=dict(color="#444", width=1, dash="dot"))
    fig.add_vline(x=50, line=dict(color="#444", width=1, dash="dot"))

    # Annotations de quadrant
    fig.add_annotation(x=85, y=max(p["expected_gain_pct"] for p in predictions) * 0.85,
                       text="✅ Fort score + gain", showarrow=False,
                       font=dict(color="#00c853", size=9))
    fig.add_annotation(x=85, y=min(p["expected_gain_pct"] for p in predictions) * 0.85,
                       text="⚠️ Fort score, surachet é", showarrow=False,
                       font=dict(color="#ff8a65", size=9))

    fig.update_layout(
        paper_bgcolor="#0f1117",
        plot_bgcolor="#0f1117",
        font=dict(color="#aaaaaa"),
        xaxis=dict(title="Score final (/100)", showgrid=True, gridcolor="#1e2130", range=[0, 105]),
        yaxis=dict(title="Gain estimé 7j (%)", showgrid=True, gridcolor="#1e2130",
                   zeroline=True, zerolinecolor="#555"),
        height=420,
        margin=dict(l=10, r=10, t=20, b=40),
    )

    st.plotly_chart(fig, use_container_width=True)
    st.caption("💡 Taille des bulles = volatilité ATR 14j. Plus la bulle est grande, plus le token est volatile.")
