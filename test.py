import sqlite3
import json
import os
from datetime import datetime
from pymongo import MongoClient, errors

# ============ CONFIG (from previous chat) ============
SQLITE_PATH = r"C:\Users\seeya\OneDrive\Desktop\CardDatabase\skipped_images.sqlite"
MONGO_URI   = "mongodb://card_manager:1369@100.80.179.119:27018/carddb"
DB_NAME     = "carddb"
# ======================================================

# ---- Step 1: Connect to SQLite ----
print("Connecting to SQLite...")
sqlite_conn = sqlite3.connect(SQLITE_PATH)
sqlite_conn.row_factory = sqlite3.Row
sqlite_cur = sqlite_conn.cursor()
print("   SQLite CONNECTED ->", SQLITE_PATH)

# ---- Step 2: Connect to MongoDB ----
print("Connecting to MongoDB...")
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000)
client.admin.command("ping")   # raises if unreachable
db = client[DB_NAME]
print("   MongoDB CONNECTED ->", MONGO_URI)
print("   Target DB:", DB_NAME, "\n")

# ---- Step 3: Backup existing Mongo collections ----
def backup_collection(db, coll_name):
    coll = db[coll_name]
    count = coll.count_documents({})
    if count == 0:
        return 0
    os.makedirs("mongo_backup", exist_ok=True)
    safe = coll_name.replace("/", "_")
    fname = f"mongo_backup/{safe}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(fname, "w", encoding="utf-8") as f:
        for doc in coll.find({}):
            doc["_id"] = str(doc["_id"])
            f.write(json.dumps(doc, default=str) + "\n")
    print(f"   Backed up {count} docs from '{coll_name}' -> {fname}")
    return count

print("Backing up existing Mongo collections...")
sqlite_cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
tables = [r[0] for r in sqlite_cur.fetchall()]
for t in tables:
    backup_collection(db, t)

print("\nStarting merge...\n")
grand_total = 0

for table in tables:
    if table == "sqlite_sequence":
        continue

    sqlite_cur.execute(f'PRAGMA table_info("{table}")')
    cols = [r[1] for r in sqlite_cur.fetchall()]

    sqlite_cur.execute(f'SELECT * FROM "{table}"')
    rows = sqlite_cur.fetchall()

    coll = db[table]
    inserted = 0
    existed = 0

    print(f"--- {table}: {len(rows)} rows ---")
    for row in rows:
        doc = {c: row[c] for c in cols}
        filt = {k: v for k, v in doc.items() if v is not None}

        try:
            result = coll.update_one(filt, {"$setOnInsert": doc}, upsert=True)
            if result.upserted_id is not None:
                inserted += 1
                print(f"   [INSERTED] {doc}")
            else:
                existed += 1
        except errors.DuplicateKeyError:
            existed += 1

    grand_total += inserted
    print(f"   -> {table}: {inserted} inserted, {existed} already present\n")

print(f"\nDONE. Total new documents inserted: {grand_total}")
client.close()
sqlite_conn.close()
