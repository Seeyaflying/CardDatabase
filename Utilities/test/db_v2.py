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

def tracker_insert(doc):
    """Insert one card_tracker document. Returns the inserted id.

    Used by insert_main_folders_v2.py to add new 'pending' records.
    """
    return tracker_coll().insert_one(doc)

def tracker_mark_pending(image_id, game_name, set_name=None, language=None, file_path=None):
    coll = tracker_coll()
    doc = {
        "image_name": image_id,
        "game_name": game_name,
        "set_name": set_name,
        "language": language,
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

def tracker_mark_skipped(image_name, game_name):
    """Flag an EXISTING card as skipped so miners don't re-download it."""
    tracker_coll().update_one(
        {"image_name": image_name, "game_name": game_name},
        {"$set": {
            "skipped": True,
            "skipped_at": datetime.now().isoformat(),
        }},
    )


def tracker_mark_skipped_new(image_name, game_name, set_name=None):
    """Insert a NEW card as skipped (a blocklist entry) when no match exists."""
    doc = {
        "image_name": image_name,
        "game_name": game_name,
        "set_name": set_name,
        "language": None,
        "status": "skipped",
        "processed_at": None,
        "uploaded": False,
        "skipped": True,
        "skipped_at": datetime.now().isoformat(),
    }
    tracker_coll().update_one(
        {"image_name": image_name, "game_name": game_name},
        {"$setOnInsert": doc},
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

# ============================================================
# bookkeeping helpers — running totals (web app)
# ============================================================

def bookkeeping_inc(key, n=1):
    """Increment a running counter in the bookkeeping collection."""
    coll = get_db()[config_v2.BOOKKEEPING_COLL]
    coll.update_one(
        {"key": key},
        {"$inc": {"value": n}},
        upsert=True,
    )

def bookkeeping_get(key):
    """Read a running counter from the bookkeeping collection (0 if absent)."""
    coll = get_db()[config_v2.BOOKKEEPING_COLL]
    doc = coll.find_one({"key": key})
    return doc["value"] if doc else 0

def bookkeeping_set(key, value):
    """Set a running counter to an exact value (used to seed the baseline)."""
    coll = get_db()[config_v2.BOOKKEEPING_COLL]
    coll.update_one(
        {"key": key},
        {"$set": {"value": value}},
        upsert=True,
    )
