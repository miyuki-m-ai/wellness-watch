"""
wellness-watch - みゆきさん用ダッシュボード
=============================================
両親の元気度を一目で確認できるダッシュボード
・会話内容は表示しない（プライバシー保護）
・数値とグラフのみ表示
"""

import os
import sqlite3
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, date, timedelta
from dotenv import load_dotenv

load_dotenv()

DB_PATH = "wellness.db"

PARENTS = {
    "parent_mom": "お母さん",
    "parent_dad": "お父さん",
}

DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", os.getenv("APP_PASSWORD", "hana1234"))

st.set_page_config(page_title="見守りダッシュボード", page_icon="🌸", layout="wide")

st.markdown("""
<style>
  #MainMenu {visibility: hidden;}
  header {visibility: hidden;}
  html, body, [class*="css"] {
    font-family: 'Hiragino Sans', 'Meiryo', sans-serif;
  }
  .title { font-size:2rem; color:#e75480; font-weight:bold; margin-bottom:2px; }
  div[data-testid="metric-container"] {
    background: #fdf6f9;
    border-radius: 10px;
    padding: 12px 16px;
    border: 1px solid #f5c6d8;
  }
</style>
""", unsafe_allow_html=True)


# =============================================
# パスワード認証
# =============================================
if "dash_auth" not in st.session_state:
    st.session_state.dash_auth = False

if not st.session_state.dash_auth:
    st.markdown('<div class="title">🌸 見守りダッシュボード</div>', unsafe_allow_html=True)
    st.divider()
    password = st.text_input("パスワード", type="password")
    if st.button("ログイン"):
        if password == DASHBOARD_PASSWORD:
            st.session_state.dash_auth = True
            st.rerun()
        else:
            st.error("パスワードが違います")
    st.stop()


# =============================================
# データ取得
# =============================================
def get_stats(user_id, days=7):
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute("""
            SELECT date, AVG(sentiment) as avg_sentiment,
                   SUM(input_tokens + output_tokens) as total_tokens,
                   SUM(turn_count) as total_turns
            FROM daily_log
            WHERE user_id = ? AND date >= ?
            GROUP BY date ORDER BY date ASC
        """, (user_id, (date.today() - timedelta(days=days)).isoformat())).fetchall()
        conn.close()
        return rows
    except:
        return []


def get_today_stats(user_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute("""
            SELECT AVG(sentiment), SUM(input_tokens + output_tokens), SUM(turn_count)
            FROM daily_log WHERE user_id = ? AND date = ?
        """, (user_id, date.today().isoformat())).fetchone()
        conn.close()
        return row
    except:
        return None


def make_sentiment_chart(df, color):
    """感情スコア折れ線グラフ（X軸を日付文字列で表示）"""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["日付"],
        y=df["感情スコア"],
        mode="lines+markers",
        line=dict(color=color, width=2),
        marker=dict(size=6),
        fill="none",
        hovertemplate="%{x}<br>感情スコア: %{y:.2f}<extra></extra>",
    ))
    fig.update_layout(
        margin=dict(l=0, r=0, t=10, b=0),
        height=160,
        xaxis=dict(
            tickvals=df["日付"].tolist(),
            ticktext=df["日付"].tolist(),
            tickangle=-45,
            tickfont=dict(size=11),
        ),
        yaxis=dict(range=[0, 1], tickfont=dict(size=11)),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
    )
    return fig


def make_turns_chart(df, color):
    """会話ターン数棒グラフ（X軸を日付文字列で表示）"""
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df["日付"],
        y=df["ターン数"],
        marker_color=color,
        hovertemplate="%{x}<br>ターン数: %{y}回<extra></extra>",
    ))
    fig.update_layout(
        margin=dict(l=0, r=0, t=10, b=0),
        height=160,
        xaxis=dict(
            tickvals=df["日付"].tolist(),
            ticktext=df["日付"].tolist(),
            tickangle=-45,
            tickfont=dict(size=11),
        ),
        yaxis=dict(tickfont=dict(size=11)),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
    )
    return fig


# =============================================
# UI描画
# =============================================
st.markdown('<div class="title">🌸 見守りダッシュボード</div>', unsafe_allow_html=True)
st.caption(f"最終更新：{datetime.now().strftime('%Y/%m/%d %H:%M')}")

# ── 今日の状況（父・母 横並び） ──────────────────
st.markdown("#### 今日の状況")
cols = st.columns(2)

parent_items = list(PARENTS.items())
for col, (user_id, parent_name) in zip(cols, parent_items):
    with col:
        today = get_today_stats(user_id)
        with st.container(border=True):
            st.markdown(f"**{parent_name}**")
            if today and today[0] is not None:
                sentiment = today[0]
                turns = today[2] or 0
                if sentiment >= 0.6:
                    mood = "😊 元気そうです"
                    badge = "🟢"
                elif sentiment >= 0.4:
                    mood = "😐 普通です"
                    badge = "🟡"
                else:
                    mood = "😔 少し心配です"
                    badge = "🔴"
                m1, m2, m3 = st.columns(3)
                m1.metric("状態", mood)
                m2.metric("感情スコア", f"{sentiment:.2f}")
                m3.metric("会話ターン", f"{turns}回")
            else:
                st.warning(f"⚠️ 今日まだ会話していません")

# ── 7日間トレンド（父・母 横並び） ─────────────────
st.markdown("#### 直近7日間のトレンド")
COLORS = {
    "parent_mom": ("#e75480", "#f4a4be"),
    "parent_dad": ("#4a90d9", "#a0c8f0"),
}

trend_cols = st.columns(2)
for col, (user_id, parent_name) in zip(trend_cols, parent_items):
    with col:
        stats = get_stats(user_id, days=7)
        with st.container(border=True):
            st.markdown(f"**{parent_name}**")
            if stats:
                df = pd.DataFrame(stats, columns=["日付", "感情スコア", "トークン数", "ターン数"])
                # 日付を「3/15」形式の文字列に変換（X軸問題の解決）
                df["日付"] = pd.to_datetime(df["日付"]).dt.strftime("%-m/%-d")

                line_color, bar_color = COLORS[user_id]
                c1, c2 = st.columns(2)
                with c1:
                    st.caption("感情スコア")
                    st.plotly_chart(make_sentiment_chart(df, line_color), use_container_width=True)
                with c2:
                    st.caption("会話ターン数")
                    st.plotly_chart(make_turns_chart(df, bar_color), use_container_width=True)

                # サマリー
                s1, s2, s3 = st.columns(3)
                s1.metric("平均スコア", f"{df['感情スコア'].mean():.2f}")
                s2.metric("会話日数", f"{len(df)}日 / 7日")
                s3.metric("平均ターン", f"{df['ターン数'].mean():.1f}回")
            else:
                st.info("データがありません")
