import time
from pymongo import MongoClient
import config

_client = None

def get_db():
    global _client
    if _client is None:
        _client = MongoClient(config.MONGO_URI, serverSelectionTimeoutMS=5000)
    return _client[config.DB_NAME]

def coll():
    return get_db()[config.COLLECTION]

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

def close():
    global _client
    if _client is not None:
        _client.close()
        _client = None
