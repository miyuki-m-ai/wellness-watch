"""
見守りシステム - スケジューラ
=====================================
毎日23時に以下を実行する：
  ① お母さんへの会話チェック
  ② 感情スコアチェック
  ③ みゆきさんへの日次レポート送信
"""

import schedule
import time
import os
from dotenv import load_dotenv
from notify import check_no_conversation, check_low_sentiment, send_daily_report

load_dotenv()

LINE_MOM_USER_ID = os.getenv("LINE_MOM_USER_ID", "")


def run_nightly_check():
    """毎日23時に実行するチェック"""
    print("🌙 23時チェック開始...")

    if LINE_MOM_USER_ID:
        # ① 今日会話がなかった場合の通知
        check_no_conversation(LINE_MOM_USER_ID, "お母さん")

        # ② 感情スコアが低い場合の通知
        check_low_sentiment(LINE_MOM_USER_ID, "お母さん")

        # ③ 日次レポート送信
        send_daily_report(LINE_MOM_USER_ID, "お母さん")
    else:
        print("⚠️ LINE_MOM_USER_ID が設定されていません")

    print("✅ 23時チェック完了")


# 毎日23:00に実行
schedule.every().day.at("23:00").do(run_nightly_check)

print("⏰ スケジューラ起動")
print("   毎日 23:00 に自動チェックします")
print("   停止するには Ctrl+C")

# すぐにテスト実行したい場合はコメントを外す
# run_nightly_check()

while True:
    schedule.run_pending()
    time.sleep(30)