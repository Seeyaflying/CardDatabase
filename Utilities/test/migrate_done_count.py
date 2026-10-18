"""
migrate_done_count.py
=====================
One-time migration: carry your old DONE count from the 'progress'
collection into card_tracker, so the new web app's DONE number
starts where you left off.

Seeds done cards as status='yes', uploaded=True.
Idempotent — safe to re-run; won't duplicate.

Run once:  python migrate_done_count.py
"""
import time
from datetime import datetime
import config_v2 as config   # <-- _v2
import db_v2 as db           # <-- _v2

# Old collections that may hold your done count.
# 'progress' is first since that's where your done data lives.
OLD_COLLECTIONS = ["progress", "immich_upload", "card_index", "card_tracker_old"]


def main():
    database = db.get_db()
    print("=== DONE COUNT MIGRATION ===")
    print(f"Database: {config.DB_NAME}")

    total_seeded = 0

    for coll_name in OLD_COLLECTIONS:
        try:
            coll = database[coll_name]
            count = coll.count_documents({})
            if count == 0:
                print(f"[{coll_name}] empty (0 docs) — skipping")
                continue
            print(f"[{coll_name}] found {count} docs")
        except Exception as e:
            print(f"[{coll_name}] error: {e}")
            continue

        done_docs = []
        for doc in coll.find({}):
            status = doc.get("status", "")
            uploaded = doc.get("uploaded", False)
            is_done = (
                status in ("yes", "done", "uploaded", "Uploaded", "Duplicate")
                or uploaded is True
            )
            if not is_done:
                continue

            image_name = (
                doc.get("image_name")
                or doc.get("name")
                or (doc.get("filename", "").rsplit(".", 1)[0] if doc.get("filename") else None)
            )
            game_name = doc.get("game_name") or doc.get("game") or doc.get("album")
            if not image_name or not game_name:
                print(f"  [SKIP] {doc.get('_id')} — missing image_name/game_name")
                continue

            done_docs.append({
                "image_name": str(image_name).replace("_200w", ""),
                "game_name": str(game_name),
                "set": doc.get("set") or doc.get("set_name"),
                "language": doc.get("language", "english"),
                "asset_id": doc.get("asset_id"),
                "is_duplicate": doc.get("is_duplicate", False),
            })

        tracker = db.tracker_coll()
        for d in done_docs:
            result = tracker.update_one(
                {"image_name": d["image_name"], "game_name": d["game_name"]},
                {"$setOnInsert": {
                    "image_name": d["image_name"],
                    "game_name": d["game_name"],
                    "set": d["set"],
                    "language": d["language"],
                    "status": "yes",
                    "processed_at": time.strftime("%Y-%m-%d %H:%M"),
                    "uploaded": True,
                    "uploaded_at": datetime.now().isoformat(),
                    "asset_id": d["asset_id"],
                    "is_duplicate": d["is_duplicate"],
                }},
                upsert=True,
            )
            if result.upserted_id:
                total_seeded += 1

    print(f"\n=== RESULT ===")
    print(f"Seeded {total_seeded} done cards into card_tracker")
    print(f"card_tracker total: {db.tracker_total()}")
    print(f"card_tracker done:  {db.tracker_done()}")

    # ---- VERIFICATION (auto-runs) ----
    print("\n=== VERIFICATION ===")
    print(f"Confirmed done count: {db.tracker_done()}")
    print("Migration complete. Data is saved to MongoDB.")


if __name__ == "__main__":
    main()
