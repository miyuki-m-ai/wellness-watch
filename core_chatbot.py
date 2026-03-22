"""
見守りシステム - コアエンジン
================================
STEP 1: 会話エンジン + 感情スコア + ログ保存

使用技術:
  - Azure OpenAI (GPT-4o-mini) : 会話・感情分析
  - SQLite                     : ログ保存（開発用）

プライバシー方針:
  - 会話テキスト本文はDBに保存しない
  - 保存するのは数値と要約のみ
"""

import os
import json
import sqlite3
from datetime import datetime, date
from openai import AzureOpenAI
from dotenv import load_dotenv

load_dotenv()

# =============================================
# クライアント初期化
# =============================================
client = AzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version="2024-02-01",
)

DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
DB_PATH = "wellness.db"


# =============================================
# システムプロンプト
# =============================================
def build_system_prompt(memory_summary: str = "") -> str:
    """
    長期記憶（要約）をシステムプロンプトに差し込む
    """
    base = """あなたは優しくて親しみやすい話し相手です。
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

この情報をもとに自然に話しかけてください。
例：「昨日のダンス教室はいかがでしたか？」"""

    return base


# =============================================
# 会話処理
# =============================================
def chat(user_id: str, message: str, history: list, memory_summary: str = "") -> dict:
    """
    会話して感情スコアとログを返す。
    会話テキスト本文はDBに保存しない。

    Args:
        user_id       : 親の識別ID（例: "parent_mom"）
        message       : 親のメッセージ（テキスト変換済み）
        history       : 今日の会話履歴（メモリ上のみ）
        memory_summary: 長期記憶の要約テキスト

    Returns:
        {
          "reply"        : str,   # ボットの返答（画面表示用・DB保存しない）
          "sentiment"    : float, # 感情スコア 0.0〜1.0 ✅保存
          "input_tokens" : int,   ✅保存
          "output_tokens": int,   ✅保存
          "timestamp"    : str,   ✅保存
          "user_id"      : str,   ✅保存
        }
    """
    # --- ① 会話 ---
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

    # --- ② 感情スコア取得（テキストは使い捨て）---
    sentiment = get_sentiment(message)

    return {
        "reply"        : reply_text,                            # 表示のみ・保存しない
        "sentiment"    : sentiment,                             # ✅ 保存OK
        "input_tokens" : response.usage.prompt_tokens,         # ✅ 保存OK
        "output_tokens": response.usage.completion_tokens,     # ✅ 保存OK
        "timestamp"    : datetime.now().isoformat(),            # ✅ 保存OK
        "user_id"      : user_id,                              # ✅ 保存OK
    }


# =============================================
# 感情スコア分析
# =============================================
def get_sentiment(message: str) -> float:
    """
    メッセージの感情スコアを返す（0.0〜1.0）
    0.0 = とてもネガティブ / 1.0 = とてもポジティブ
    テキスト本文はAPIに送るが保存しない。
    """
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
        return 0.5  # パース失敗時はニュートラル


# =============================================
# 長期記憶：会話要約の生成
# =============================================
def summarize_conversation(conversation_history: list) -> str:
    """
    会話終了後に「事実の要約」だけを生成する。
    会話テキスト本文は破棄し、要約のみDBに保存する。

    Returns:
        要約テキスト（例: "・ダンス教室に行った\n・足が疲れていた"）
    """
    if not conversation_history:
        return ""

    # 会話を文字列に変換
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
                    "例：\n"
                    "・ダンス教室に通っている（毎週火曜）\n"
                    "・膝が少し痛いと話していた\n"
                    "・孫の運動会が来週ある\n\n"
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
# DB操作
# =============================================
def init_db(db_path: str = DB_PATH):
    """DBとテーブルを初期化する"""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_log (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       TEXT    NOT NULL,
            date          TEXT    NOT NULL,
            timestamp     TEXT,
            sentiment     REAL,
            input_tokens  INTEGER,
            output_tokens INTEGER,
            turn_count    INTEGER DEFAULT 1
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memory_summary (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    TEXT    NOT NULL,
            date       TEXT    NOT NULL,
            summary    TEXT,               -- 要約のみ保存（テキスト本文なし）
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def save_log(log: dict, turn_count: int = 1, db_path: str = DB_PATH):
    """数値データのみ保存（テキスト列なし）"""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        INSERT INTO daily_log
          (user_id, date, timestamp, sentiment, input_tokens, output_tokens, turn_count)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        log["user_id"],
        date.today().isoformat(),
        log["timestamp"],
        log["sentiment"],
        log["input_tokens"],
        log["output_tokens"],
        turn_count,
    ))
    conn.commit()
    conn.close()


def save_memory(user_id: str, summary: str, db_path: str = DB_PATH):
    """要約記憶を保存（会話テキスト本文は含まない）"""
    if not summary:
        return
    conn = sqlite3.connect(db_path)
    conn.execute("""
        INSERT INTO memory_summary (user_id, date, summary, created_at)
        VALUES (?, ?, ?, ?)
    """, (
        user_id,
        date.today().isoformat(),
        summary,
        datetime.now().isoformat(),
    ))
    conn.commit()
    conn.close()


def load_recent_memory(user_id: str, days: int = 3, db_path: str = DB_PATH) -> str:
    """
    直近N日分の要約を読み込む
    翌日の会話でシステムプロンプトに差し込む用
    """
    conn = sqlite3.connect(db_path)
    rows = conn.execute("""
        SELECT date, summary FROM memory_summary
        WHERE user_id = ?
        ORDER BY date DESC
        LIMIT ?
    """, (user_id, days)).fetchall()
    conn.close()

    if not rows:
        return ""

    lines = []
    for row_date, summary in reversed(rows):
        lines.append(f"【{row_date}】\n{summary}")
    return "\n".join(lines)


def get_weekly_stats(user_id: str, db_path: str = DB_PATH) -> dict:
    """
    過去7日間の元気度スタッツを集計する
    みゆきさんのダッシュボード用
    """
    conn = sqlite3.connect(db_path)
    rows = conn.execute("""
        SELECT date,
               AVG(sentiment)                    AS avg_sentiment,
               SUM(input_tokens + output_tokens) AS total_tokens,
               SUM(turn_count)                   AS total_turns
        FROM daily_log
        WHERE user_id = ?
          AND date >= date('now', '-7 days')
        GROUP BY date
        ORDER BY date ASC
    """, (user_id,)).fetchall()
    conn.close()

    return {
        "user_id": user_id,
        "days": [
            {
                "date"         : row[0],
                "avg_sentiment": round(row[1], 2) if row[1] else None,
                "total_tokens" : row[2],
                "total_turns"  : row[3],
            }
            for row in rows
        ]
    }


# =============================================
# 動作確認用：ターミナルで会話テスト
# =============================================
if __name__ == "__main__":
    print("=" * 45)
    print("  🌸 見守りチャットボット テスト起動")
    print("  終了: Ctrl+C  |  会話終了: 'q'")
    print("=" * 45)

    # DB初期化
    init_db()

    user_id = "parent_mom"
    history = []       # セッション内の会話履歴（メモリ上のみ）
    turn_count = 0

    # 長期記憶を読み込む
    memory = load_recent_memory(user_id, days=3)
    if memory:
        print(f"\n📝 直近の記憶を読み込みました：\n{memory}\n")

    # 最初の挨拶
    greeting_result = chat(
        user_id=user_id,
        message="おはようございます",
        history=[],
        memory_summary=memory,
    )
    print(f"\nボット: {greeting_result['reply']}\n")

    history.append({"role": "user",      "content": "おはようございます"})
    history.append({"role": "assistant", "content": greeting_result["reply"]})
    save_log(greeting_result, turn_count=1)
    turn_count = 1

    # 会話ループ
    try:
        while True:
            user_input = input("親: ").strip()
            if not user_input or user_input.lower() == "q":
                break

            result = chat(
                user_id=user_id,
                message=user_input,
                history=history,
                memory_summary=memory,
            )
            turn_count += 1

            print(f"\nボット: {result['reply']}")
            print(
                f"  └ 感情: {result['sentiment']:.2f} "
                f"| tokens: {result['input_tokens'] + result['output_tokens']}\n"
            )

            # 会話履歴はメモリ上のみ（セッション終了で消える）
            history.append({"role": "user",      "content": user_input})
            history.append({"role": "assistant", "content": result["reply"]})

            # DBには数値のみ保存
            save_log(result, turn_count=turn_count)

    except KeyboardInterrupt:
        pass

    # 会話終了：要約を生成してDBに保存
    print("\n--- 会話終了。要約を生成しています... ---")
    summary = summarize_conversation(history)
    if summary:
        save_memory(user_id, summary)
        print(f"📝 保存した要約：\n{summary}")

    # 今週のスタッツ表示
    stats = get_weekly_stats(user_id)
    print(f"\n📊 今週の記録（{user_id}）：")
    for day in stats["days"]:
        sentiment_bar = "😊" if (day["avg_sentiment"] or 0) >= 0.6 else "😐" if (day["avg_sentiment"] or 0) >= 0.4 else "😔"
        print(
            f"  {day['date']} {sentiment_bar} "
            f"感情:{day['avg_sentiment']}  "
            f"tokens:{day['total_tokens']}  "
            f"ターン:{day['total_turns']}"
        )

    print("\n✅ 終了しました。")