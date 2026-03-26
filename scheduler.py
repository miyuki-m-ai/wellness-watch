"""
見守りシステム - スケジューラー
=====================================
毎日以下を実行する：
  ✅ お母さんへの朝の挨拶チェック
  ✅ 感情スコアチェック
  ✅ みゆきさんへの日次レポート送信
  ✅ お母さんへの朝・夜の話しかけ
"""
import schedule
import time
import os
import urllib.request
import json
from dotenv import load_dotenv
from notify import check_no_conversation, check_low_sentiment, send_daily_report

load_dotenv()

LINE_MOM_USER_ID          = os.getenv("LINE_MOM_USER_ID", "")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")


# =============================================
# お母さんのLINEに直接メッセージを送る
# =============================================
def send_message_to_mom(message: str) -> bool:
    """お母さんのLINEにプッシュメッセージを送る"""
    if not LINE_MOM_USER_ID or not LINE_CHANNEL_ACCESS_TOKEN:
        print("❌ LINE_MOM_USER_ID または LINE_CHANNEL_ACCESS_TOKEN が未設定")
        return False

    url  = "https://api.line.me/v2/bot/message/push"
    data = json.dumps({
        "to": LINE_MOM_USER_ID,
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
        print(f"✅ お母さんへLINE送信成功: {message[:30]}...")
        return True
    except Exception as e:
        print(f"❌ お母さんへのLINE送信失敗: {e}")
        return False


# =============================================
# 朝6時30分 - おはようメッセージ
# =============================================
def morning_greeting():
    print("🌸 朝の挨拶送信中...")
    send_message_to_mom("じゅんこさん、おはようございます！今日もよろしくね。")


# =============================================
# 夜19時 - おやすみメッセージ
# =============================================
def evening_greeting():
    print("🌙 夜の挨拶送信中...")
    send_message_to_mom("じゅんこさん、今日も一日お疲れ様でした。ゆっくり休んでくださいね。")


# =============================================
# 毎日21時 - 通知チェック
# =============================================
def run_nightly_check():
    print("🔍 21時チェック開始...")
    mom_id = os.getenv("WELLNESS_MOM_USER_ID", "parent_mom")
    if mom_id:
        check_no_conversation(mom_id, "お母さん")
        check_low_sentiment(mom_id, "お母さん")
        send_daily_report(mom_id, "お母さん")
    else:
        print("❌ WELLNESS_MOM_USER_ID が設定されていません")
    print("✅ 21時チェック完了")


# =============================================
# スケジュール設定
# =============================================
schedule.every().day.at("06:30").do(morning_greeting)
schedule.every().day.at("19:00").do(evening_greeting)
schedule.every().day.at("21:00").do(run_nightly_check)

print("🌸 スケジューラー起動")
print("   06:30 お母さんへ朝の挨拶")
print("   19:00 お母さんへ夜の挨拶")
print("   21:00 自動チェック")
print("   停止するには Ctrl+C")

while True:
    schedule.run_pending()
    time.sleep(30)