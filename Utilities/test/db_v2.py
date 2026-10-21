import time
from pymongo import MongoClient
import config_v2
from datetime import datetime

_client = None

def get_db():
    global _client
    if _client is None:
        _client = MongoClient(config_v2.MONGO_URI, serverSelectionTimeoutMS=5000)
    return _client[config_v2.DB_NAME]

def coll():
    return get_db()[config_v2.COLLECTION]

def tracker_coll():
    """The card_tracker collection — the single source of truth."""
    return get_db()[config_v2.CARD_TRACKER_COLL]

def init_db():
    coll().create_index([("game", 1), ("filename", 1)], unique=True)

def has_data():
    return coll().count_documents({}) > 0

def mark_uploaded(filename, game, dst_file):
    coll().update_one(
        {"filename": filename, "game": game},
        {"$set": {"status": "uploaded", "dest_path": str(dst_file),
                  "uploaded_at": time.strftime("%Y-%m-%d %H:%M:%S")}})

def mark_missing_source(filename, game):
    coll().update_one({"filename": filename, "game": game},
                      {"$set": {"status": "missing_source"}})

# ============================================================
# card_tracker helpers — the unified tracker
# ============================================================

def tracker_find_one(image_name, game_name):
    return tracker_coll().find_one({"image_name": image_name, "game_name": game_name})

def tracker_mark_pending(image_id, game_name, set_name=None, lang="english", file_path=None):
    coll = get_db()[CARD_TRACKER_COLL]
    doc = {
        "image_name": image_id,
        "game_name": game_name,
        "set_name": set_name,
        "lang": lang,
        "status": "pending",
        "processed_at": None,
        "uploaded": False,
    }
    if file_path:
        doc["file_path"] = file_path
    coll.update_one(
        {"image_name": image_id, "game_name": game_name},
        {"$setOnInsert": doc},
        upsert=True
    )


def tracker_mark_reviewed(image_name, game_name, status):
    """Set yes/no when the web app makes a decision."""
    tracker_coll().update_one(
        {"image_name": image_name, "game_name": game_name},
        {"$set": {
            "status": status,
            "processed_at": time.strftime("%Y-%m-%d %H:%M"),
        }},
        upsert=True,
    )

def tracker_mark_uploaded(image_name, game_name, asset_id, set_name, is_duplicate):
    """Set uploaded state when the uploader finishes a card."""
    tracker_coll().update_one(
        {"image_name": image_name, "game_name": game_name},
        {"$set": {
            "uploaded": True,
            "uploaded_at": datetime.now().isoformat(),
            "asset_id": asset_id,
            "set": set_name,
            "is_duplicate": is_duplicate,
        }},
        upsert=True,
    )

def tracker_total():
    return tracker_coll().count_documents({})

def tracker_done():
    """Cards fully done = reviewed yes AND uploaded."""
    return tracker_coll().count_documents({"status": "yes", "uploaded": True})

def record_run(script_name):
    coll = get_db()[config_v2.RUN_HISTORY_COLLECTION]
    coll.update_one(
        {"script": script_name},
        {"$set": {"last_run": datetime.now().isoformat()}},
        upsert=True,
    )

def get_run_history():
    coll = get_db()[config_v2.RUN_HISTORY_COLLECTION]
    return {doc["script"]: doc["last_run"] for doc in coll.find({}, {"_id": 0, "script": 1, "last_run": 1})}

def close():
    global _client
    if _client is not None:
        _client.close()
        _client = None
