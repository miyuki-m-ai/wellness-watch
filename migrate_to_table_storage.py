"""
migrate_to_table_storage.py
============================
SQLite（wellness.db）のデータを Azure Table Storage に移行する。

実行方法：
  python migrate_to_table_storage.py

テーブル設計：
  テーブル名    : WellnessLog
  PartitionKey  : user_id       （例: parent_mom）
  RowKey        : timestamp     （例: 2026-03-19T22:59:10.582696）
  その他フィールド: date, sentiment, input_tokens, output_tokens, turn_count
"""

import os
import sqlite3
from dotenv import load_dotenv
from azure.data.tables import TableServiceClient, TableEntity
from azure.core.exceptions import ResourceExistsError

load_dotenv()

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DB_PATH    = os.path.join(BASE_DIR, "wellness.db")
TABLE_NAME = "WellnessLog"

CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
if not CONNECTION_STRING:
    raise EnvironmentError("AZURE_STORAGE_CONNECTION_STRING が .env に設定されていません")


def migrate():
    # ── 1. Table Storage に接続してテーブルを作成 ──
    service = TableServiceClient.from_connection_string(CONNECTION_STRING)
    try:
        service.create_table(TABLE_NAME)
        print(f"✅ テーブル作成：{TABLE_NAME}")
    except ResourceExistsError:
        print(f"ℹ️  テーブルはすでに存在します：{TABLE_NAME}")

    table_client = service.get_table_client(TABLE_NAME)

    # ── 2. SQLite から全データを取得 ──
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT user_id, date, timestamp, sentiment, input_tokens, output_tokens, turn_count
        FROM daily_log
        ORDER BY timestamp ASC
    """).fetchall()
    conn.close()

    print(f"📦 SQLite から {len(rows)} 件取得")

    # ── 3. Table Storage に upsert ──
    success = 0
    skip    = 0
    for row in rows:
        user_id, date, timestamp, sentiment, input_tokens, output_tokens, turn_count = row

        # RowKey に使えない文字（: など）を置換
        row_key = timestamp.replace(":", "-") if timestamp else date

        entity = TableEntity()
        entity["PartitionKey"]  = user_id
        entity["RowKey"]        = row_key
        entity["date"]          = date
        entity["timestamp"]     = timestamp or ""
        entity["sentiment"]     = float(sentiment) if sentiment is not None else 0.5
        entity["input_tokens"]  = int(input_tokens)  if input_tokens  else 0
        entity["output_tokens"] = int(output_tokens) if output_tokens else 0
        entity["turn_count"]    = int(turn_count)    if turn_count    else 1

        try:
            table_client.upsert_entity(entity)
            success += 1
        except Exception as e:
            print(f"⚠️ スキップ（{row_key}）：{e}")
            skip += 1

    print(f"\n✅ 移行完了：{success} 件成功 / {skip} 件スキップ")


if __name__ == "__main__":
    migrate()