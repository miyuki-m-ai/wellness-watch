"""
見守りシステム - コアエンジン
================================
STEP 1: 会話エンジン + 感情スコア + ログ保存

使用技術:
  - Azure OpenAI (GPT-4o-mini) : 会話・感情分析
  - Azure Table Storage        : ログ保存

プライバシー方針:
  - 会話テキスト本文はDBに保存しない
  - 保存するのは数値と要約のみ
"""

import os
from datetime import datetime, date, timezone
from openai import AzureOpenAI
from dotenv import load_dotenv
from azure.data.tables import TableServiceClient, TableEntity
from azure.core.exceptions import ResourceExistsError

load_dotenv()

# =============================================
# クライアント初期化
# =============================================
client = AzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version="2024-02-01",
)

DEPLOYMENT_NAME   = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
TABLE_NAME        = "WellnessLog"
MEMORY_TABLE_NAME = "WellnessMemory"

# Table Storage クライアント（シングルトン）
_table_service: TableServiceClient | None = None


def get_table_service() -> TableServiceClient:
    global _table_service
    if _table_service is None:
        _table_service = TableServiceClient.from_connection_string(CONNECTION_STRING)
    return _table_service


def init_db():
    """テーブルを初期化する（なければ作成）"""
    service = get_table_service()
    for name in [TABLE_NAME, MEMORY_TABLE_NAME]:
        try:
            service.create_table(name)
            print(f"✅ テーブル作成：{name}")
        except ResourceExistsError:
            pass


# =============================================
# システムプロンプト
# =============================================
def build_system_prompt(memory_summary: str = "") -> str:
    base = """あなたは優しくて親しみやすい話し相手です。
相手の名前はじゅんこさんです。会話の中で自然に「じゅんこさん」と名前を呼んでください。
高齢の方と毎日自然に会話してください。

【会話のルール】
・質問は一度に一つだけにする
・難しい言葉は使わない
・相手の話をしっかり聞いて共感する
・体調や気分をさりげなく確認する
・明るく穏やかなトーンで話す
・返答は短めに（3〜4文程度）"""

    if memory_summary:
        base += f"""

【この方についての最近の情報】
{memory_summary}

この情報をもとに自然に話しかけてください。"""

    return base


# =============================================
# 会話処理
# =============================================
def chat(user_id: str, message: str, history: list, memory_summary: str = "") -> dict:
    messages = [
        {"role": "system", "content": build_system_prompt(memory_summary)}
    ] + history + [
        {"role": "user", "content": message}
    ]

    response = client.chat.completions.create(
        model=DEPLOYMENT_NAME,
        messages=messages,
        max_tokens=512,
        temperature=0.8,
    )
    reply_text = response.choices[0].message.content
    sentiment  = get_sentiment(message)

    return {
        "reply"        : reply_text,
        "sentiment"    : sentiment,
        "input_tokens" : response.usage.prompt_tokens,
        "output_tokens": response.usage.completion_tokens,
        "timestamp"    : datetime.now().isoformat(),
        "user_id"      : user_id,
    }


# =============================================
# 感情スコア分析
# =============================================
def get_sentiment(message: str) -> float:
    try:
        response = client.chat.completions.create(
            model=DEPLOYMENT_NAME,
            messages=[{
                "role": "user",
                "content": (
                    "以下の発言の感情スコアを返してください。\n"
                    "0.0（とてもネガティブ）〜1.0（とてもポジティブ）の数値のみ返してください。\n"
                    "数値以外は何も返さないでください。\n\n"
                    f"発言：{message}"
                )
            }],
            max_tokens=10,
            temperature=0,
        )
        score = float(response.choices[0].message.content.strip())
        return max(0.0, min(1.0, score))
    except (ValueError, Exception):
        return 0.5


# =============================================
# 長期記憶：会話要約の生成
# =============================================
def summarize_conversation(conversation_history: list) -> str:
    if not conversation_history:
        return ""

    conv_text = "\n".join([
        f"{'親' if m['role'] == 'user' else 'ボット'}: {m['content']}"
        for m in conversation_history
    ])

    try:
        response = client.chat.completions.create(
            model=DEPLOYMENT_NAME,
            messages=[{
                "role": "user",
                "content": (
                    "以下の会話から、次回の会話に役立つ事実だけを\n"
                    "箇条書きで3行以内に要約してください。\n"
                    "個人的な感情の詳細や発言内容そのままは含めないでください。\n"
                    "形式：「・〇〇」の箇条書きのみ\n\n"
                    f"会話：\n{conv_text}"
                )
            }],
            max_tokens=200,
            temperature=0,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return ""


# =============================================
# Table Storage：ログ保存
# =============================================
def save_log(log: dict, turn_count: int = 1):
    """数値データのみ保存（テキスト列なし）"""
    timestamp = log.get("timestamp", datetime.now().isoformat())
    row_key   = timestamp.replace(":", "-")

    entity = TableEntity()
    entity["PartitionKey"]  = log["user_id"]
    entity["RowKey"]        = row_key
    entity["date"]          = date.today().isoformat()
    entity["timestamp"]     = timestamp
    entity["sentiment"]     = float(log["sentiment"])
    entity["input_tokens"]  = int(log["input_tokens"])
    entity["output_tokens"] = int(log["output_tokens"])
    entity["turn_count"]    = int(turn_count)

    try:
        table_client = get_table_service().get_table_client(TABLE_NAME)
        table_client.upsert_entity(entity)
    except Exception as e:
        print(f"⚠️ save_log 失敗：{e}")


# =============================================
# Table Storage：記憶保存
# =============================================
def save_memory(user_id: str, summary: str):
    """要約記憶を保存（会話テキスト本文は含まない）"""
    if not summary:
        return

    today   = date.today().isoformat()
    row_key = datetime.now().isoformat().replace(":", "-")

    entity = TableEntity()
    entity["PartitionKey"] = user_id
    entity["RowKey"]       = row_key
    entity["date"]         = today
    entity["summary"]      = summary

    try:
        table_client = get_table_service().get_table_client(MEMORY_TABLE_NAME)
        table_client.upsert_entity(entity)
    except Exception as e:
        print(f"⚠️ save_memory 失敗：{e}")


# =============================================
# Table Storage：記憶読み込み
# =============================================
def load_recent_memory(user_id: str, days: int = 3) -> str:
    """直近N日分の要約を読み込む"""
    from datetime import timedelta
    cutoff = (date.today() - timedelta(days=days)).isoformat()

    try:
        table_client = get_table_service().get_table_client(MEMORY_TABLE_NAME)
        entities = table_client.query_entities(
            query_filter=f"PartitionKey eq '{user_id}' and date ge '{cutoff}'"
        )
        rows = sorted(entities, key=lambda e: e["date"])
    except Exception:
        return ""

    if not rows:
        return ""

    lines = []
    for entity in rows:
        lines.append(f"【{entity['date']}】\n{entity['summary']}")
    return "\n".join(lines)


# =============================================
# Table Storage：週次統計
# =============================================
def get_weekly_stats(user_id: str) -> dict:
    """過去7日間の統計を集計する"""
    from datetime import timedelta
    from collections import defaultdict

    cutoff = (date.today() - timedelta(days=7)).isoformat()

    try:
        table_client = get_table_service().get_table_client(TABLE_NAME)
        entities = table_client.query_entities(
            query_filter=f"PartitionKey eq '{user_id}' and date ge '{cutoff}'"
        )
    except Exception:
        return {"user_id": user_id, "days": []}

    # 日付ごとに集計
    daily: dict = defaultdict(lambda: {"sentiments": [], "tokens": 0, "turns": 0})
    for entity in entities:
        d = entity.get("date", "")
        if entity.get("sentiment") is not None:
            daily[d]["sentiments"].append(float(entity["sentiment"]))
        daily[d]["tokens"] += int(entity.get("input_tokens", 0)) + int(entity.get("output_tokens", 0))
        daily[d]["turns"]  += int(entity.get("turn_count", 1))

    days_list = []
    for d in sorted(daily.keys()):
        s = daily[d]["sentiments"]
        days_list.append({
            "date"         : d,
            "avg_sentiment": round(sum(s) / len(s), 2) if s else None,
            "total_tokens" : daily[d]["tokens"],
            "total_turns"  : daily[d]["turns"],
        })

    return {"user_id": user_id, "days": days_list}
