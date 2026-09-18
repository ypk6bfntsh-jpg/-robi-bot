import random
import time
from datetime import datetime
import pandas as pd
import streamlit as st

st.set_page_config(page_title="ROBI BOT - Paper Trading", layout="wide")

if "balance" not in st.session_state:
    st.session_state.balance = 40.0
if "start_balance" not in st.session_state:
    st.session_state.start_balance = 40.0
if "trades" not in st.session_state:
    st.session_state.trades = []
if "history" not in st.session_state:
    st.session_state.history = [{"time": datetime.now().strftime("%H:%M:%S"), "balance": 40.0}]
if "running" not in st.session_state:
    st.session_state.running = False

st.title("🤖 ROBI BOT — Paper Trading")
st.caption("نسخة تجريبية: لا ترسل أي معاملة حقيقية ولا تستخدم أموالًا حقيقية.")

c1, c2, c3, c4 = st.columns(4)
pnl = st.session_state.balance - st.session_state.start_balance
wins = sum(1 for x in st.session_state.trades if x["pnl"] > 0)
total = len(st.session_state.trades)
win_rate = (wins / total * 100) if total else 0

c1.metric("BALANCE", f"${st.session_state.balance:,.2f}")
c2.metric("TOTAL P&L", f"${pnl:,.2f}", f"{pnl:+.2f}")
c3.metric("WIN RATE", f"{win_rate:.0f}%")
c4.metric("TASKS", str(total))

st.divider()

left, right = st.columns([1, 1])

with left:
    st.subheader("AI AGENTS")
    agents = [
        ("SCOUT", "يرصد العملات والـvolume والسيولة"),
        ("RISK", "يفحص السيولة والتذبذب وحجم المركز"),
        ("EXEC", "ينفذ صفقة وهمية وفق القواعد"),
    ]
    for name, desc in agents:
        st.write(f"**{name}** — {desc}")

    st.subheader("CONTROL")
    risk = st.slider("Risk per trade (%)", 1.0, 20.0, 5.0, 0.5)
    min_score = st.slider("Minimum signal score", 0, 100, 70)

    if st.button("▶ تشغيل دورة محاكاة"):
        # Random market signal; intentionally simulated.
        score = random.randint(40, 98)
        volume = random.uniform(1000, 50000)
        change = random.uniform(-12, 25)

        if score >= min_score and change > 0:
            size = st.session_state.balance * (risk / 100)
            # Simple educational simulation, not a market model.
            trade_pnl = size * random.uniform(-0.20, 0.45)
            st.session_state.balance += trade_pnl
            st.session_state.trades.append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "signal": score,
                "change": round(change, 2),
                "volume": round(volume, 2),
                "size": round(size, 2),
                "pnl": round(trade_pnl, 2),
            })
            action = f"BUY → simulated P&L ${trade_pnl:+.2f}"
        else:
            action = "SKIP → signal did not pass filters"

        st.session_state.history.append({
            "time": datetime.now().strftime("%H:%M:%S"),
            "balance": round(st.session_state.balance, 2)
        })
        st.success(action)

    if st.button("↺ إعادة المحاكاة إلى $40"):
        st.session_state.balance = 40.0
        st.session_state.trades = []
        st.session_state.history = [{"time": datetime.now().strftime("%H:%M:%S"), "balance": 40.0}]
        st.rerun()

with right:
    st.subheader("BALANCE HISTORY")
    chart = pd.DataFrame(st.session_state.history)
    if len(chart) > 1:
        chart["time"] = range(len(chart))
        st.line_chart(chart.set_index("time")["balance"])
    else:
        st.info("شغّل عدة دورات لرؤية الرسم.")

st.divider()
st.subheader("ACTIVITY LOG")
if st.session_state.trades:
    df = pd.DataFrame(st.session_state.trades).iloc[::-1]
    st.dataframe(df, use_container_width=True, hide_index=True)
else:
    st.info("لا توجد عمليات بعد.")

st.caption("هذه المحاكاة تعليمية وليست نموذجًا للتنبؤ بالربح أو توصية استثمارية.")
