"""
wellness-watch - みゆきさん用ダッシュボード
=============================================
両親の元気度を一目で確認できるダッシュボード
・会話内容は表示しない（プライバシー保護）
・数値とグラフのみ表示
"""

import os
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, date, timedelta
from collections import defaultdict
from dotenv import load_dotenv
from azure.data.tables import TableServiceClient

load_dotenv()

CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
TABLE_NAME        = "WellnessLog"

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
    """過去N日分を日付ごとに集計。データがない日も0で補完する。"""
    cutoff = (date.today() - timedelta(days=days - 1)).isoformat()

    raw_entities = []
    error_msg = None

    try:
        service      = TableServiceClient.from_connection_string(CONNECTION_STRING)
        table_client = service.get_table_client(TABLE_NAME)
        entities     = table_client.query_entities(
            query_filter=f"PartitionKey eq '{user_id}' and date ge '{cutoff}'"
        )
        raw_entities = list(entities)
    except Exception as e:
        error_msg = str(e)

    # デバッグ情報（サイドバーに表示）
    with st.sidebar:
        st.caption(f"**{user_id} デバッグ**")
        st.caption(f"cutoff: `{cutoff}`")
        if error_msg:
            st.error(f"取得エラー: {error_msg}")
        else:
            st.caption(f"取得件数: {len(raw_entities)} 件")
            if raw_entities:
                sample = raw_entities[0]
                st.caption(f"date値例: `{sample.get('date', 'なし')}`")
                st.caption(f"sentiment値例: `{sample.get('sentiment', 'なし')}`")

    # 日付ごとに集計
    # ※ 1レコード = 1会話（turn_count は加算しない）
    daily: dict = defaultdict(lambda: {"sentiments": [], "turns": 0})
    for entity in raw_entities:
        d = entity.get("date", "")
        if entity.get("sentiment") is not None:
            daily[d]["sentiments"].append(float(entity["sentiment"]))
        daily[d]["turns"] += 1  # レコード件数 = 会話回数

    # 7日分の日付リスト（データない日は0補完）
    all_dates = [(date.today() - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    result = []
    for d in all_dates:
        if d in daily:
            s = daily[d]["sentiments"]
            result.append({
                "date"         : d,
                "avg_sentiment": round(sum(s) / len(s), 2) if s else None,
                "total_turns"  : daily[d]["turns"],
            })
        else:
            result.append({
                "date"         : d,
                "avg_sentiment": None,
                "total_turns"  : 0,
            })
    return result


# =============================================
# グラフ生成
# =============================================
def make_sentiment_chart(df, color):
    df_with_data = df[df["感情スコア"].notna()]

    fig = go.Figure()
    fig.add_hrect(y0=0.6, y1=1.0, fillcolor="rgba(100,200,100,0.07)", line_width=0)
    fig.add_hrect(y0=0.4, y1=0.6, fillcolor="rgba(255,200,0,0.07)",   line_width=0)
    fig.add_hrect(y0=0.0, y1=0.4, fillcolor="rgba(255,100,100,0.07)", line_width=0)

    fig.add_trace(go.Scatter(
        x=df_with_data["日付"],
        y=df_with_data["感情スコア"],
        mode="lines+markers",
        line=dict(color=color, width=2.5),
        marker=dict(size=8, color=color),
        hovertemplate="%{x}<br>感情スコア: %{y:.2f}<extra></extra>",
    ))

    fig.update_layout(
        margin=dict(l=0, r=0, t=10, b=0),
        height=180,
        xaxis=dict(
            categoryorder="array",
            categoryarray=df["日付"].tolist(),  # 全7日を固定順で表示
            tickangle=0,
            tickfont=dict(size=10),
            showgrid=False,
        ),
        yaxis=dict(
            range=[0, 1],
            tickvals=[0, 0.4, 0.6, 1.0],
            ticktext=["0", "0.4", "0.6", "1.0"],
            tickfont=dict(size=11),
            showgrid=True,
            gridcolor="rgba(0,0,0,0.05)",
        ),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
    )
    return fig


def make_turns_chart(df, color):
    bar_colors = [
        color if v > 0 else "rgba(200,200,200,0.3)"
        for v in df["ターン数"]
    ]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df["日付"],
        y=df["ターン数"],
        marker_color=bar_colors,
        hovertemplate="%{x}<br>%{y} 回<extra></extra>",
    ))
    fig.update_layout(
        margin=dict(l=0, r=0, t=10, b=0),
        height=180,
        xaxis=dict(
            categoryorder="array",
            categoryarray=df["日付"].tolist(),  # 全7日を固定順で表示
            tickangle=0,
            tickfont=dict(size=10),
            showgrid=False,
        ),
        yaxis=dict(
            tickfont=dict(size=11),
            showgrid=True,
            gridcolor="rgba(0,0,0,0.05)",
        ),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
    )
    return fig


# =============================================
# UI描画
# =============================================
st.markdown('<div class="title">🌸 見守りダッシュボード</div>', unsafe_allow_html=True)

col_title, col_btn = st.columns([4, 1])
with col_title:
    st.caption(f"最終更新：{datetime.now().strftime('%Y/%m/%d %H:%M')}")
with col_btn:
    if st.button("🔄 更新", use_container_width=True):
        st.rerun()

# ── 直近7日間のトレンド ────────────────────
COLORS = {
    "parent_mom": ("#e75480", "#f4a4be"),
    "parent_dad": ("#4a90d9", "#a0c8f0"),
}

parent_items = list(PARENTS.items())
trend_cols   = st.columns(2)

for col, (user_id, parent_name) in zip(trend_cols, parent_items):
    with col:
        stats = get_stats(user_id, days=7)
        with st.container(border=True):
            st.markdown(f"**{parent_name}**")

            df = pd.DataFrame(stats)
            df["日付"]     = pd.to_datetime(df["date"]).apply(lambda d: f"{d.month}/{d.day}")
            df["感情スコア"] = df["avg_sentiment"]
            df["ターン数"]   = df["total_turns"]

            line_color, bar_color = COLORS[user_id]
            active_days = df[df["ターン数"] > 0]

            if len(active_days) == 0:
                st.info("データがありません")
            else:
                c1, c2 = st.columns(2)
                with c1:
                    st.caption("😊 感情スコア（高いほど元気）")
                    st.plotly_chart(make_sentiment_chart(df, line_color), use_container_width=True)
                with c2:
                    st.caption("💬 会話回数")
                    st.plotly_chart(make_turns_chart(df, bar_color), use_container_width=True)

                avg_score = active_days["感情スコア"].mean()
                avg_turns = active_days["ターン数"].mean()
                talk_days = len(active_days)

                s1, s2, s3 = st.columns(3)
                s1.metric("平均スコア",   f"{avg_score:.2f}" if avg_score else "—")
                s2.metric("会話した日数", f"{talk_days} 日 / 7日")
                s3.metric("平均会話回数", f"{avg_turns:.1f} 回" if avg_turns else "—")
