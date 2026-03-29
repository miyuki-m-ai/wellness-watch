import azure.functions as func
import logging
import os
import urllib.request
import json
from datetime import datetime, date
from azure.data.tables import TableServiceClient
from dotenv import load_dotenv

load_dotenv()

app = func.FunctionApp()

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_MOM_USER_ID          = os.getenv("LINE_MOM_USER_ID", "")
LINE_USER_ID              = os.getenv("LINE_USER_ID", "")  # みゆきさん
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
WELLNESS_MOM_USER_ID      = os.getenv("WELLNESS_MOM_USER_ID", "parent_mom")


def send_line_message(to_user_id: str, message: str, token: str = None) -> bool:
    """指定したユーザーにLINEメッセージを送る"""
    if not token:
        token = LINE_CHANNEL_ACCESS_TOKEN
    url  = "https://api.line.me/v2/bot/message/push"
    data = json.dumps({
        "to": to_user_id,
        "messages": [{"type": "text", "text": message}]
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={
            "Content-Type" : "application/json",
            "Authorization": f"Bearer {token}"
        },
        method="POST"
    )
    try:
        urllib.request.urlopen(req)
        logging.info(f"LINE送信成功: {message[:30]}...")
        return True
    except Exception as e:
        logging.error(f"LINE送信失敗: {e}")
        return False


def get_today_stats(user_id: str) -> dict:
    """Azure Table StorageからWellnessLogを取得"""
    try:
        service = TableServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
        table   = service.get_table_client("WellnessLog")
        today   = date.today().isoformat()
        entities = list(table.query_entities(
            f"PartitionKey eq '{user_id}' and RowKey ge '{today}'"
        ))
        if not entities:
            return {"total_turns": 0, "avg_sentiment": None}
        total_turns   = sum(e.get("total_turns", 0) for e in entities)
        sentiments    = [e.get("avg_sentiment") for e in entities if e.get("avg_sentiment") is not None]
        avg_sentiment = sum(sentiments) / len(sentiments) if sentiments else None
        return {"total_turns": total_turns, "avg_sentiment": avg_sentiment}
    except Exception as e:
        logging.error(f"Table Storage取得失敗: {e}")
        return {"total_turns": 0, "avg_sentiment": None}


# =============================================
# 朝6:30 お母さんへおはようメッセージ
# =============================================
@app.timer_trigger(schedule="0 30 21 * * *", arg_name="myTimer", run_on_startup=False,
                   use_monitor=False)
def mom_morning_greeting(myTimer: func.TimerRequest) -> None:
    logging.info("朝の挨拶送信中...")
    if LINE_MOM_USER_ID:
        send_line_message(LINE_MOM_USER_ID, "じゅんこさん、おはようございます！今日もよろしくね😊")
    else:
        logging.error("LINE_MOM_USER_IDが未設定")


# =============================================
# 夜19:00 お母さんへおやすみメッセージ
# =============================================
@app.timer_trigger(schedule="0 0 10 * * *", arg_name="myTimer", run_on_startup=False,
                   use_monitor=False)
def mom_evening_greeting(myTimer: func.TimerRequest) -> None:
    logging.info("夜の挨拶送信中...")
    if LINE_MOM_USER_ID:
        send_line_message(LINE_MOM_USER_ID, "じゅんこさん、今日も一日お疲れさまでした。ゆっくり休んでくださいね😌")
    else:
        logging.error("LINE_MOM_USER_IDが未設定")


# =============================================
# 夜21:00 みゆきさんへ日次レポート
# =============================================
@app.timer_trigger(schedule="0 0 12 * * *", arg_name="myTimer", run_on_startup=False,
                   use_monitor=False)
def mom_nightly_check(myTimer: func.TimerRequest) -> None:
    logging.info("21時チェック開始...")
    stats         = get_today_stats(WELLNESS_MOM_USER_ID)
    total_turns   = stats["total_turns"]
    avg_sentiment = stats["avg_sentiment"]
    today_str     = date.today().isoformat()

    def mood_label(score):
        if score is None:
            return "データなし"
        if score >= 0.7:
            return "😊 元気そう！"
        elif score >= 0.5:
            return "🙂 普通です"
        else:
            return "😟 少し心配"

    if total_turns == 0:
        message = (
            f"🌙 お母さんの見守りレポート\n"
            f"{'='*20}\n"
            f"📅 {today_str}\n\n"
            f"⚠️ 今日はまだ会話がありません。\n"
            f"お電話してみてはいかがですか？📞"
        )
    else:
        message = (
            f"🌙 お母さんの見守りレポート\n"
            f"{'='*20}\n"
            f"📅 {today_str}\n\n"
            f"会話ターン数：{total_turns}回\n"
            f"気分状態：{mood_label(avg_sentiment)}\n"
            f"感情スコア：{f'{avg_sentiment:.2f}' if avg_sentiment else 'なし'}\n\n"
            f"今日もお母さんと話せましたね😊"
        )

    if LINE_USER_ID:
        send_line_message(LINE_USER_ID, message)
    else:
        logging.error("LINE_USER_IDが未設定")
# =============================================
# 朝6:30 お父さんへおはようメッセージ
# =============================================
@app.timer_trigger(schedule="0 30 21 * * *", arg_name="myTimer", run_on_startup=False,
                   use_monitor=False)
def dad_morning_greeting(myTimer: func.TimerRequest) -> None:
    logging.info("お父さん朝の挨拶送信中...")
    dad_user_id = os.getenv("LINE_DAD_USER_ID", "")
    if dad_user_id:
        send_line_message(dad_user_id, "じゅんじさん、おはようございます！今日もよろしくね😊")
    else:
        logging.error("LINE_DAD_USER_ID未設定")


# =============================================
# 夜19:00 お父さんへおやすみメッセージ
# =============================================
@app.timer_trigger(schedule="0 0 10 * * *", arg_name="myTimer", run_on_startup=False,
                   use_monitor=False)
def dad_evening_greeting(myTimer: func.TimerRequest) -> None:
    logging.info("お父さん夜の挨拶送信中...")
    dad_user_id = os.getenv("LINE_DAD_USER_ID", "")
    if dad_user_id:
        send_line_message(dad_user_id, "じゅんじさん、今日も一日お疲れさまでした。ゆっくり休んでくださいね😊")
    else:
        logging.error("LINE_DAD_USER_ID未設定")


# =============================================
# 夜21:00 みゆきさんへお父さんの日次レポート
# =============================================
@app.timer_trigger(schedule="0 0 12 * * *", arg_name="myTimer", run_on_startup=False,
                   use_monitor=False)
def dad_nightly_check(myTimer: func.TimerRequest) -> None:
    logging.info("お父さん21時チェック開始...")
    dad_user_id = os.getenv("LINE_DAD_USER_ID", "")
    stats       = get_today_stats("parent_dad")
    total_turns   = stats["total_turns"]
    avg_sentiment = stats["avg_sentiment"]
    today_str     = date.today().isoformat()

    def mood_label(score):
        if score is None:
            return "データなし"
        if score >= 0.7:
            return "😊 元気そう"
        elif score >= 0.5:
            return "😐 普通"
        else:
            return "😟 少し心配"

    if total_turns == 0:
        message = (
            f"👨 お父さんの見守りレポート\n"
            f"{'='*20}\n"
            f"📅 {today_str}\n\n"
            f"今日はまだ会話がありません。\n"
            f"連絡してみてはいかがですか？"
        )
    else:
        message = (
            f"👨 お父さんの見守りレポート\n"
            f"{'='*20}\n"
            f"📅 {today_str}\n\n"
            f"会話ターン数：{total_turns}回\n"
            f"気分状態：{mood_label(avg_sentiment)}\n"
            f"感情スコア：{f'{avg_sentiment:.2f}' if avg_sentiment else 'なし'}\n\n"
            f"今日もお父さんと話せましたね！"
        )

    if LINE_USER_ID:
        send_line_message(LINE_USER_ID, message)
    else:
        logging.error("LINE_USER_ID未設定")