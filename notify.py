"""
見守りシステム - LINE通知モジュール
=====================================
以下の3つの通知を送る：
  ① 今日会話がなかった場合
  ② 感情スコアが低い場合
  ③ 毎晩の定時レポート
"""

import os
import urllib.request
import json
from datetime import datetime, date
from dotenv import load_dotenv
from core_chatbot import get_weekly_stats

load_dotenv()

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_USER_ID              = os.getenv("LINE_USER_ID")

# =============================================
# LINEにメッセージを送る
# =============================================
def send_line_message(message: str) -> bool:
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
    Azure Table Storage から取得
    """
    stats     = get_weekly_stats(user_id)
    days      = stats["days"]
    today_str = date.today().isoformat()
    today     = next((d for d in days if d["date"] == today_str), None)
    count     = today["total_turns"] if today else 0

    if count == 0:
        hour = datetime.now().hour
        if hour >= 18:
            message = (
                f"⚠️ {parent_name}への通知\n\n"
                f"今日（{today_str}）はまだ\n"
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
    Azure Table Storage から取得
    """
    stats     = get_weekly_stats(user_id)
    days      = stats["days"]
    today_str = date.today().isoformat()
    today     = next((d for d in days if d["date"] == today_str), None)

    if not today or today["avg_sentiment"] is None:
        print(f"📝 {parent_name}：今日の感情データなし")
        return

    avg_sentiment = today["avg_sentiment"]

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
# ③ 毎晩の定時レポート
# =============================================
def send_daily_report(user_id: str, parent_name: str = "お母さん"):
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

    # 直近7日の平均感情スコア
    scored_days   = [d for d in days if d["avg_sentiment"] is not None]
    avg_sentiment = sum(d["avg_sentiment"] for d in scored_days) / len(scored_days)

    # 元気度の絵文字（共通関数）
    def mood_label(score):
        if score >= 0.7:
            return "😊 元気そうです！"
        elif score >= 0.5:
            return "😐 普通です"
        else:
            return "😔 少し心配です"

    # 直近7日の会話状況
    talk_days = len([d for d in days if d["total_tokens"] and d["total_tokens"] > 0])

    # 直近のデータ（今日 or 最新の日）
    today_str   = date.today().isoformat()
    latest_data = next((d for d in reversed(days) if d["total_turns"] > 0), None)

    message = (
        f"🌸 {parent_name}の見守りレポート\n"
        f"━━━━━━━━━━━━━━\n"
        f"📅 {date.today()} 夜のレポート\n\n"
        f"【直近7日間】\n"
        f"元気度：{mood_label(avg_sentiment)}\n"
        f"平均感情スコア：{avg_sentiment:.2f}\n"
        f"会話した日数：{talk_days}日／7日\n\n"
    )

    if latest_data:
        label         = "今日" if latest_data["date"] == today_str else latest_data["date"]
        latest_score  = latest_data["avg_sentiment"]
        message += (
            f"【{label}の記録】\n"
            f"元気度：{mood_label(latest_score)}\n"
            f"感情スコア：{latest_score}\n"
            f"会話ターン：{latest_data['total_turns']}回\n"
        )

    send_line_message(message)

# =============================================
# テスト送信
# =============================================
if __name__ == "__main__":
    print("=== LINE通知テスト ===")
    mom_id = os.getenv("WELLNESS_MOM_USER_ID", "parent_mom")
    send_daily_report(mom_id, "お母さん")