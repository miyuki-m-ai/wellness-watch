import os
from dotenv import load_dotenv
from azure.data.tables import TableServiceClient, TableEntity
from datetime import datetime, date

load_dotenv()

svc = TableServiceClient.from_connection_string(os.getenv("AZURE_STORAGE_CONNECTION_STRING"))
tbl = svc.get_table_client("WellnessLog")

# 全件取得して日付一覧を確認
rows = list(tbl.query_entities("PartitionKey eq 'parent_mom'"))
print(f"総件数: {len(rows)} 件")

# 日付ごとの件数を集計
from collections import Counter
dates = Counter(r.get("date", "不明") for r in rows)
for d in sorted(dates.keys()):
    print(f"  {d}: {dates[d]} 件")

# ── save_log のテスト ──
print("\n--- save_log テスト ---")
entity = TableEntity()
entity["PartitionKey"]  = "parent_mom"
entity["RowKey"]        = "test-" + datetime.now().isoformat().replace(":", "-")
entity["date"]          = date.today().isoformat()
entity["timestamp"]     = datetime.now().isoformat()
entity["sentiment"]     = 0.99
entity["input_tokens"]  = 1
entity["output_tokens"] = 1
entity["turn_count"]    = 1

try:
    tbl.upsert_entity(entity)
    print(f"✅ テスト書き込み成功: {date.today().isoformat()}")
except Exception as e:
    print(f"❌ テスト書き込み失敗: {e}")
