from pathlib import Path
import os
import shutil
import hashlib
import urllib.parse
import re

from flask import Flask, request, jsonify, render_template, send_file
from flask_cors import CORS
from bson import ObjectId
from pymongo import UpdateOne

import config_v2
import db_v2

PORT = 5055

BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__, template_folder=str(BASE_DIR))
CORS(app)

LANGS = [
    "english", "german", "spanish", "french", "italian",
    "japanese", "portuguese", "russian", "chinese", "korean",
]

BK_KEY = "total_done"

# ------------------------------------------------------------------
# LITERAL DRIVE-LETTER STRING. NEVER .resolve() / .as_posix() on it:
# resolving rewrites T: to \\home-server\Tera\... (UNC), which breaks
# the Mongo regex AND 403s every image against ALLOWED_ROOTS.
# ------------------------------------------------------------------
LANG_SOURCE_STR = r"T:\Full Card Database\Folder Database"
ALLOWED_ROOTS = [LANG_SOURCE_STR]
_ROOT_RE = "^" + re.escape(LANG_SOURCE_STR)

THUMB_DIR = Path("lang_thumbs")
THUMB_SIZE = (320, 480)
BATCH_LIMIT = 9


def _is_allowed(path):
    """Raw string-prefix compare — NO resolve(), which would rewrite
    T: into UNC and break the allowlist."""
    p = str(path)
    return any(p.startswith(r) for r in ALLOWED_ROOTS)


def _resolve_image_path(doc):
    fp = doc.get("file_path")
    if fp and _is_allowed(fp):
        p = Path(fp)
        if p.is_file():
            return p
    return None


def _reconstruct_path(doc):
    root = LANG_SOURCE_STR
    game = doc.get("game_name") or ""
    set_name = doc.get("set_name") or ""
    name = doc.get("image_name") or ""
    stems = [name, f"{name}_200w"]
    candidates = []
    for stem in stems:
        for ext in (".jpg", ".png"):
            candidates.append(Path(root) / game / set_name / f"{stem}{ext}")
            candidates.append(Path(root) / game / f"{stem}{ext}")
    for c in candidates:
        if c.is_file():
            return c
    return None


def _thumb_path(path):
    key = hashlib.md5(str(path).encode()).hexdigest()
    return THUMB_DIR / f"{key}.jpg"


def _make_thumb(src, dst):
    try:
        from PIL import Image
        img = Image.open(src)
        img.thumbnail(THUMB_SIZE)
        img.convert("RGB").save(dst, "JPEG", quality=82)
    except Exception:
        shutil.copyfile(src, dst)


@app.route("/thumb", methods=["GET"])
def serve_thumb():
    path = request.args.get("path", "")
    if not path:
        return "missing path", 400
    target = Path(path)
    if not _is_allowed(target):
        return "forbidden", 403
    if not target.is_file():
        return "not found", 404
    thumb = _thumb_path(target)
    if not thumb.exists():
        THUMB_DIR.mkdir(parents=True, exist_ok=True)
        _make_thumb(target, thumb)
    return send_file(str(thumb), mimetype="image/jpeg", conditional=True)


@app.route("/image", methods=["GET"])
def serve_image():
    path = request.args.get("path", "")
    if not path:
        return "missing path", 400
    target = Path(path)
    if not _is_allowed(target):
        return "forbidden", 403
    if not target.is_file():
        return "not found", 404
    return send_file(str(target), conditional=True)


@app.route("/")
def index():
    return render_template("lang_index.html", langs=LANGS, port=PORT)


@app.route("/api/pending_batch", methods=["GET"])
def pending_batch():
    """Up to BATCH_LIMIT pending cards, optionally from ONE folder
    via ?game=...&set=... . Confined to Folder Database in Mongo."""
    coll = db_v2.tracker_coll()
    limit = min(int(request.args.get("limit", BATCH_LIMIT)), 200)
    game = request.args.get("game") or None
    set_name = request.args.get("set") or None
    total_done = db_v2.bookkeeping_get(BK_KEY)

    query = {
        "status": "pending",
        "file_path": {"$regex": _ROOT_RE},
    }
    if game:
        query["game_name"] = game
    if set_name:
        query["set_name"] = set_name

    total_pending = coll.count_documents(query)

    cards = []
    for doc in coll.find(query).limit(limit):
        fp = doc.get("file_path")
        if not fp or not _is_allowed(fp) or not Path(fp).is_file():
            continue
        p = Path(fp)
        cards.append({
            "id": str(doc["_id"]),
            "image_name": doc.get("image_name"),
            "game": doc.get("game_name"),
            "set": doc.get("set_name"),
            "language": doc.get("language"),
            "image_url": f"/thumb?path={urllib.parse.quote(str(p))}",
            "full_url": f"/image?path={urllib.parse.quote(str(p))}",
        })

    return jsonify({
        "done": not cards,
        "pending": total_pending,
        "total_done": total_done,
        "cards": cards,
    })


@app.route("/api/assign_batch", methods=["POST"])
def assign_batch():
    data = request.get_json(force=True)
    coll = db_v2.tracker_coll()
    ops = []
    for c in data.get("cards", []):
        oid = ObjectId(c["id"])
        lang = c.get("language")
        status = "skipped" if not lang else "done"
        ops.append(UpdateOne(
            {"_id": oid},
            {"$set": {"language": lang, "status": status}},
        ))
    if ops:
        coll.bulk_write(ops, ordered=False)
        db_v2.bookkeeping_inc(BK_KEY, len(ops))
    return jsonify({"written": len(ops)})


@app.route("/api/assign_folder", methods=["POST"])
def assign_folder():
    data = request.get_json(force=True)
    game = data.get("game")
    set_name = data.get("set")
    lang = data.get("language")
    coll = db_v2.tracker_coll()
    query = {
        "status": "pending",
        "file_path": {"$regex": _ROOT_RE},
    }
    if game:
        query["game_name"] = game
    if set_name:
        query["set_name"] = set_name
    status = "skipped" if not lang else "done"
    result = coll.update_many(
        query,
        {"$set": {"language": lang, "status": status}},
    )
    if result.modified_count:
        db_v2.bookkeeping_inc(BK_KEY, result.modified_count)
        print(f"[FOLDER] Assigned '{lang or 'skip'}' to {result.modified_count} cards in {game}/{set_name}")
    return jsonify({"folder_modified": result.modified_count})


@app.route("/api/folders", methods=["GET"])
def folder_list():
    coll = db_v2.tracker_coll()
    folders = coll.aggregate([
        {"$match": {"status": "pending", "file_path": {"$regex": _ROOT_RE}}},
        {"$group": {"_id": {"game": "$game_name", "set": "$set_name"}, "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ])
    return jsonify({
        "folders": [
            {"game": f["_id"].get("game"), "set": f["_id"].get("set"), "count": f["count"]}
            for f in folders
        ]
    })


if __name__ == "__main__":
    print(f"lang_app - http://0.0.0.0:{PORT}/")
    app.run(host="0.0.0.0", port=PORT, debug=True)






