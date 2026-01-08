import streamlit as st
import sqlite3
import pandas as pd
import time

# ==================================================
# PAGE CONFIG
# ==================================================
st.set_page_config(
    page_title="PolySentinel — Market Intelligence",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ==================================================
# STYLE — TRADING DESK / INSTITUTIONAL
# ==================================================
st.markdown("""
<style>
.stApp {
    background-color: #f5f7fa;
    color: #0f172a;
    font-family: Inter, system-ui, -apple-system, Segoe UI, sans-serif;
}

h1 {
    font-size: 36px;
    font-weight: 700;
    letter-spacing: -0.6px;
    margin-bottom: 4px;
}

.subtitle {
    color: #475569;
    margin-bottom: 28px;
}

.section-title {
    font-size: 18px;
    font-weight: 600;
    margin-bottom: 12px;
}

hr {
    border-top: 1px solid #e5e7eb;
    margin: 32px 0;
}

.card {
    background: white;
    border: 1px solid #e5e7eb;
    border-radius: 10px;
    padding: 18px;
}

.kpi {
    background: white;
    border: 1px solid #e5e7eb;
    border-radius: 10px;
    padding: 18px;
}

.kpi-label {
    font-size: 13px;
    color: #64748b;
}

.kpi-value {
    font-size: 26px;
    font-weight: 700;
}

table {
    width: 100%;
    border-collapse: collapse;
}

th {
    text-align: left;
    font-size: 13px;
    color: #64748b;
    font-weight: 600;
    border-bottom: 1px solid #e5e7eb;
    padding-bottom: 8px;
}

td {
    padding: 8px 4px;
    border-bottom: 1px solid #f1f5f9;
    font-size: 14px;
}

.rank {
    color: #94a3b8;
    width: 28px;
}

.right {
    text-align: right;
    font-weight: 600;
}
</style>
""", unsafe_allow_html=True)

# ==================================================
# AUTO REFRESH
# ==================================================
if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = time.time()

if time.time() - st.session_state.last_refresh > 30:
    st.session_state.last_refresh = time.time()
    st.rerun()

# ==================================================
# DATA
# ==================================================
def load_data():
    try:
        conn = sqlite3.connect("whale_watch.db")
        df = pd.read_sql_query("SELECT * FROM whales ORDER BY id DESC", conn)
        conn.close()
        return df
    except:
        return pd.DataFrame()

df = load_data()

# ==================================================
# HEADER
# ==================================================
st.markdown("<h1>PolySentinel</h1>", unsafe_allow_html=True)
st.markdown(
    "<div class='subtitle'>Real-time intelligence on high-impact prediction market activity</div>",
    unsafe_allow_html=True
)

if df.empty:
    st.info("Waiting for live data feed…")
    st.stop()

# ==================================================
# KPIs
# ==================================================
c1, c2, c3, c4 = st.columns(4)

with c1:
    st.markdown(f"""
    <div class="kpi">
        <div class="kpi-label">Whales Detected</div>
        <div class="kpi-value">{len(df)}</div>
    </div>
    """, unsafe_allow_html=True)

with c2:
    st.markdown(f"""
    <div class="kpi">
        <div class="kpi-label">Total Volume</div>
        <div class="kpi-value">${df['value_usd'].sum():,.0f}</div>
    </div>
    """, unsafe_allow_html=True)

with c3:
    st.markdown(f"""
    <div class="kpi">
        <div class="kpi-label">Largest Bet</div>
        <div class="kpi-value">${df['value_usd'].max():,.0f}</div>
    </div>
    """, unsafe_allow_html=True)

with c4:
    fresh = df["funding_source"].str.contains("Unknown", case=False, na=False).sum()
    st.markdown(f"""
    <div class="kpi">
        <div class="kpi-label">Fresh Wallets</div>
        <div class="kpi-value">{fresh}</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<hr>", unsafe_allow_html=True)

# ==================================================
# CORE INTEL
# ==================================================
left, right = st.columns(2)

# -------- TOP MARKETS (LEADERBOARD)
with left:
    st.markdown("<div class='card'><div class='section-title'>Top Markets</div>", unsafe_allow_html=True)

    top = df["question"].value_counts().head(8).reset_index()
    top.columns = ["Market", "Activity"]

    rows = []
    for i, r in top.iterrows():
        rows.append(f"""
        <tr>
            <td class="rank">{i+1}</td>
            <td>{r['Market']}</td>
            <td class="right">{r['Activity']}</td>
        </tr>
        """)

    st.markdown(f"""
    <table>
        <thead>
            <tr>
                <th></th>
                <th>Market</th>
                <th class="right">Activity</th>
            </tr>
        </thead>
        <tbody>
            {''.join(rows)}
        </tbody>
    </table>
    """, unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)

# -------- LARGEST BETS
with right:
    st.markdown("<div class='card'><div class='section-title'>Largest Bets</div>", unsafe_allow_html=True)

    big = df.sort_values("value_usd", ascending=False).head(8)

    rows = []
    for _, r in big.iterrows():
        rows.append(f"""
        <tr>
            <td>{r['question']}</td>
            <td class="right">${r['value_usd']:,.0f}</td>
        </tr>
        """)

    st.markdown(f"""
    <table>
        <thead>
            <tr>
                <th>Market</th>
                <th class="right">Bet Size</th>
            </tr>
        </thead>
        <tbody>
            {''.join(rows)}
        </tbody>
    </table>
    """, unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)

st.markdown("<hr>", unsafe_allow_html=True)

# ==================================================
# DISTRIBUTIONS (TEXTUAL, FAST)
# ==================================================
c1, c2 = st.columns(2)

# Bet Size Buckets
with c1:
    st.markdown("<div class='card'><div class='section-title'>Bet Size Distribution</div>", unsafe_allow_html=True)

    bins = {
        "$0–500": (0, 500),
        "$500–1k": (500, 1000),
        "$1k–2k": (1000, 2000),
        "$2k+": (2000, 10**9),
    }

    rows = []
    for label, (lo, hi) in bins.items():
        count = df[(df["value_usd"] >= lo) & (df["value_usd"] < hi)].shape[0]
        rows.append(f"<tr><td>{label}</td><td class='right'>{count}</td></tr>")

    st.markdown(f"""
    <table>
        <thead><tr><th>Range</th><th class="right">Count</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
    </table>
    """, unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)

# Funding Sources
with c2:
    st.markdown("<div class='card'><div class='section-title'>Funding Sources</div>", unsafe_allow_html=True)

    src = df["funding_source"].value_counts().head(6)

    rows = [f"<tr><td>{k}</td><td class='right'>{v}</td></tr>" for k, v in src.items()]

    st.markdown(f"""
    <table>
        <thead><tr><th>Source</th><th class="right">Count</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
    </table>
    """, unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)

st.markdown("<hr>", unsafe_allow_html=True)

# ==================================================
# LIVE TAPE
# ==================================================
st.markdown("<div class='section-title'>Live Activity</div>", unsafe_allow_html=True)

feed = df[
    ["human_time", "question", "position", "value_usd", "funding_source"]
].copy()

feed["value_usd"] = feed["value_usd"].apply(lambda x: f"${x:,.0f}")

st.dataframe(feed, use_container_width=True, height=420)
