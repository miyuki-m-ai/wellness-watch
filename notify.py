"""
見守りシステム - LINE通知モジュール
=====================================
以下の3つの通知を送る：
  ① 今日会話がなかった場合
  ② 感情スコアが低い場合
  ③ 毎朝の定時レポート
"""

import os
import urllib.request
import json
from datetime import datetime, date
from dotenv import load_dotenv
from core_chatbot import get_weekly_stats, DB_PATH
import sqlite3

load_dotenv()

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_USER_ID              = os.getenv("LINE_USER_ID")

# =============================================
# LINEにメッセージを送る
# =============================================
def send_line_message(message: str) -> bool:
    """
    みゆきさんのLINEにメッセージを送る
    Returns: 成功したらTrue
    """
    url  = "https://api.line.me/v2/bot/message/push"
    data = json.dumps({
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": message}]
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type" : "application/json",
            "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
        },
        method="POST"
    )

    try:
        urllib.request.urlopen(req)
        print(f"✅ LINE送信成功：{message[:30]}...")
        return True
    except Exception as e:
        print(f"❌ LINE送信失敗：{e}")
        return False


# =============================================
# ① 今日会話がなかった場合の通知
# =============================================
def check_no_conversation(user_id: str, parent_name: str = "お母さん"):
    """
    今日まだ会話がない場合にみゆきさんに通知する
    """
    conn = sqlite3.connect(DB_PATH)
    row  = conn.execute("""
        SELECT COUNT(*) FROM daily_log
        WHERE user_id = ? AND date = ?
    """, (user_id, date.today().isoformat())).fetchone()
    conn.close()

    count = row[0] if row else 0

    if count == 0:
        now  = datetime.now()
        hour = now.hour

        # 夕方以降（18時以降）に通知
        if hour >= 18:
            message = (
                f"⚠️ {parent_name}への通知\n\n"
                f"今日（{date.today()}）はまだ\n"
                f"会話がありません。\n\n"
                f"お電話してみてはいかがですか？ 📞"
            )
            send_line_message(message)
        else:
            print(f"📝 {parent_name}：今日まだ会話なし（通知は18時以降）")
    else:
        print(f"✅ {parent_name}：今日{count}回会話済み")


# =============================================
# ② 感情スコアが低い場合の通知
# =============================================
def check_low_sentiment(user_id: str, parent_name: str = "お母さん", threshold: float = 0.4):
    """
    今日の感情スコアが低い場合に通知する
    """
    conn = sqlite3.connect(DB_PATH)
    row  = conn.execute("""
        SELECT AVG(sentiment) FROM daily_log
        WHERE user_id = ? AND date = ?
    """, (user_id, date.today().isoformat())).fetchone()
    conn.close()

    if not row or row[0] is None:
        return

    avg_sentiment = row[0]

    if avg_sentiment < threshold:
        emoji   = "😔" if avg_sentiment < 0.3 else "😐"
        message = (
            f"{emoji} {parent_name}の元気度アラート\n\n"
            f"今日の感情スコアが低めです。\n"
            f"スコア：{avg_sentiment:.2f}（基準：{threshold}以上）\n\n"
            f"少し気にかけてあげてください 💕"
        )
        send_line_message(message)
    else:
        print(f"✅ {parent_name}：感情スコア正常（{avg_sentiment:.2f}）")


# =============================================
# ③ 毎朝の定時レポート
# =============================================
def send_daily_report(user_id: str, parent_name: str = "お母さん"):
    """
    毎朝の元気度レポートを送る
    """
    stats = get_weekly_stats(user_id)
    days  = stats["days"]

    if not days:
        message = (
            f"🌸 {parent_name}の見守りレポート\n\n"
            f"まだデータがありません。\n"
            f"会話を始めてみましょう！"
        )
        send_line_message(message)
        return

    # 今日のデータ
    today_str  = date.today().isoformat()
    today_data = next((d for d in days if d["date"] == today_str), None)

    # 直近7日の平均
    avg_sentiment = sum(
        d["avg_sentiment"] for d in days if d["avg_sentiment"]
    ) / len(days) if days else 0

    # 絵文字で元気度を表現
    if avg_sentiment >= 0.7:
        mood = "😊 元気そうです！"
    elif avg_sentiment >= 0.5:
        mood = "😐 普通です"
    else:
        mood = "😔 少し心配です"

    # 直近7日の会話状況
    talk_days = len([d for d in days if d["total_tokens"] and d["total_tokens"] > 0])

    message = (
        f"🌸 {parent_name}の見守りレポート\n"
        f"━━━━━━━━━━━━━━\n"
        f"📅 {date.today()} 朝のレポート\n\n"
        f"【直近7日間】\n"
        f"元気度：{mood}\n"
        f"平均感情スコア：{avg_sentiment:.2f}\n"
        f"会話した日数：{talk_days}日／7日\n\n"
    )

    if today_data:
        message += (
            f"【昨日の記録】\n"
            f"感情スコア：{today_data['avg_sentiment']}\n"
            f"会話ターン：{today_data['total_turns']}回\n"
        )

    send_line_message(message)


# =============================================
# テスト送信
# =============================================
if __name__ == "__main__":
    print("=== LINE通知テスト ===")

    # テストメッセージを送る
    send_line_message(
        "🌸 見守りシステムからテスト通知\n\n"
        "LINE通知が正常に動作しています！\n"
        "これからお母さんの元気度をお知らせします 😊"
    )