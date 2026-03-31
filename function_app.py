import azure.functions as func
import logging
import os
import urllib.request
import json
from datetime import date
from azure.data.tables import TableServiceClient

app = func.FunctionApp()

# 設定
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_MOM_USER_ID          = os.getenv("LINE_MOM_USER_ID", "")
LINE_USER_ID              = os.getenv("LINE_USER_ID", "")
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
WELLNESS_MOM_USER_ID      = os.getenv("WELLNESS_MOM_USER_ID", "parent_mom")
LINE_DAD_USER_ID          = os.getenv("LINE_DAD_USER_ID", "")
WELLNESS_DAD_USER_ID      = os.getenv("WELLNESS_DAD_USER_ID", "parent_dad")

def send_line_message(to_user_id: str, message: str, token: str = None) -> bool:
    if not token:
        token = LINE_CHANNEL_ACCESS_TOKEN
    if not to_user_id:
        return False
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
        return True
    except Exception as e:
        logging.error(f"LINE送信失敗: {e}")
        return False

def get_today_stats(user_id: str) -> dict:
    try:
        service = TableServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
        table   = service.get_table_client("WellnessLog")
        today   = date.today().isoformat()
        entities = list(table.query_entities(query_filter=f"PartitionKey eq '{user_id}' and RowKey ge '{today}'"))
        if not entities:
            return {"total_turns": 0, "avg_sentiment": None}
        total_turns   = sum(e.get("turn_count", 0) for e in entities)
        sentiments    = [e.get("avg_sentiment") for e in entities if e.get("avg_sentiment") is not None]
        avg_sentiment = sum(sentiments) / len(sentiments) if sentiments else None
        return {"total_turns": total_turns, "avg_sentiment": avg_sentiment}
    except Exception as e:
        logging.error(f"Table Storage取得失敗: {e}")
        return {"total_turns": 0, "avg_sentiment": None}

def get_mood_label(score):
    if score is None: return "データなし"
    if score >= 0.7: return "😊 元気そう"
    elif score >= 0.5: return "🙂 普通"
    else: return "😔 少し心配"

# --- お母さん スケジュール ---
@app.timer_trigger(schedule="0 30 6 * * *", arg_name="myTimer") # 6:30
def mom_morning_greeting(myTimer: func.TimerRequest) -> None:
    send_line_message(LINE_MOM_USER_ID, "じゅんこさん、おはようございます！今日もよろしくね。")

@app.timer_trigger(schedule="0 0 19 * * *", arg_name="myTimer") # 19:00
def mom_evening_greeting(myTimer: func.TimerRequest) -> None:
    send_line_message(LINE_MOM_USER_ID, "じゅんこさん、今日も一日お疲れさまでした。ゆっくり休んでくださいね。")

@app.timer_trigger(schedule="0 0 21 * * *", arg_name="myTimer") # 21:00
def mom_nightly_check(myTimer: func.TimerRequest) -> None:
    stats = get_today_stats(WELLNESS_MOM_USER_ID)
    msg = f"📊 お母さんの見守りレポート\n📅 {date.today().isoformat()}\n\n"
    if stats["total_turns"] == 0:
        msg += "今日はまだ会話がありません。\nお電話してみてはいかがですか？"
    else:
        msg += f"会話数：{stats['total_turns']}回\n状態：{get_mood_label(stats['avg_sentiment'])}\n今日もお母さんと話せましたね！"
    send_line_message(LINE_USER_ID, msg)

# --- お父さん スケジュール ---
@app.timer_trigger(schedule="0 31 6 * * *", arg_name="myTimer") # 6:31
def dad_morning_greeting(myTimer: func.TimerRequest) -> None:
    send_line_message(LINE_DAD_USER_ID, "じゅんじさん、おはようございます！今日もよろしくね。")

@app.timer_trigger(schedule="0 1 19 * * *", arg_name="myTimer") # 19:01
def dad_evening_greeting(myTimer: func.TimerRequest) -> None:
    send_line_message(LINE_DAD_USER_ID, "じゅんじさん、今日も一日お疲れさまでした。ゆっくり休んでくださいね。")

@app.timer_trigger(schedule="0 0 21 * * *", arg_name="myTimer") # 21:00ちょうど
def dad_nightly_check(myTimer: func.TimerRequest) -> None:
    stats = get_today_stats(WELLNESS_DAD_USER_ID)
    msg = f"📊 お父さんの見守りレポート\n📅 {date.today().isoformat()}\n\n"
    if stats["total_turns"] == 0:
        msg += "今日はまだ会話がありません。\n連絡してみてはいかがですか？"
    else:
        msg += f"会話数：{stats['total_turns']}回\n状態：{get_mood_label(stats['avg_sentiment'])}\n今日もお父さんと話せましたね！"
    send_line_message(LINE_USER_ID, msg)