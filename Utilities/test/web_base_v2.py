import os
import shutil
import threading
import time
import random
import signal
import logging
from datetime import datetime
from flask import Flask, render_template, send_from_directory, jsonify, request
from flask_cors import CORS
import config_v2
import db_v2

# Tells Flask to look for index.html in the Utilities folder
app = Flask(__name__, template_folder=os.path.dirname(os.path.abspath(__file__)))
CORS(app)

# Silence werkzeug's per-request 200 lines but keep connection info
class RequestFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        if '"GET ' in msg or '"POST ' in msg or '"PUT ' in msg or '"DELETE ' in msg:
            return False
        return True

logging.getLogger('werkzeug').addFilter(RequestFilter())

# ==============================================================
# TOGGLES
# ==============================================================
FLASK_DEBUG = False
VERBOSE = False  # controls only [CONN] noise; change logging and moves/syncs always print

# ==============================================================
# 1. PLATFORM DETECTION & CONFIGURATION
# ==============================================================
IS_WINDOWS = os.name == 'nt'
# card_tracker is the single source of truth. progress / immich_upload are retired.
CARD_TRACKER_COLL = config_v2.CARD_TRACKER_COLL

if IS_WINDOWS:
    DRIVE_SOURCE = r"T:\Full Card Database\New Cards"
    DRIVE_YES_DIR = r"T:\Full Card Database\Card Upload"   # uploader reads this
    DRIVE_NO_DIR = r"T:\Full Card Database\Skipped Cards"
    BASE_LOCAL_PATH = r"C:\Users\seeya\OneDrive\Desktop\Cards"
else:
    DRIVE_SOURCE = os.path.expanduser("~/Desktop/GDrive/New Cards")
    DRIVE_YES_DIR = os.path.expanduser("~/Desktop/GDrive/Card Database")
    DRIVE_NO_DIR = os.path.expanduser("~/Desktop/GDrive/Skipped Cards")
    BASE_LOCAL_PATH = os.path.expanduser("~/Desktop/Cards")

PROTECTED_ROOTS = {
    os.path.normpath(DRIVE_SOURCE),
    os.path.normpath(DRIVE_YES_DIR),
    os.path.normpath(DRIVE_NO_DIR),
    os.path.normpath(BASE_LOCAL_PATH),
    os.path.normpath(os.path.join(BASE_LOCAL_PATH, "users"))
}

# ==============================================================
# 2. STATE MANAGEMENT
# ==============================================================
active_users = {"seeya", "riverleaf"}
user_prefs = {"seeya": "WAITING", "riverleaf": "WAITING"}
user_history = {"seeya": [], "riverleaf": []}

SYNC_BATCH_SIZE = 1500
MIN_THRESHOLD = 300
MAX_DOWNLOAD_THREADS = 10
download_lock = threading.Lock()

sync_progress = {"active": False, "done": 0, "total": 0, "current": ""}

JAPANESE_GAMES = {
    "Weiss Schwarz", "Cardfight Vanguard", "Digimon", "Pokemon", "One Piece",
    "Dragon Ball", "Yu-Gi-Oh", "Flesh and Blood", "Final Fantasy", "Gundam"
}


# ==========================
# HELPER FUNCTIONS
# ==========================

def recursive_cleanup(root_path):
    if not os.path.exists(root_path):
        print(f"[CLEANUP] Nothing to clean - path does not exist: {root_path}")
        return 0
    deleted_count = 0
    for root, dirs, files in os.walk(root_path, topdown=False):
        for name in dirs:
            dir_path = os.path.normpath(os.path.join(root, name))
            if dir_path in PROTECTED_ROOTS:
                continue
            try:
                if not os.listdir(dir_path):
                    os.rmdir(dir_path)
                    print(f"[CLEANUP] Removed empty folder: {dir_path}")
                    deleted_count += 1
            except OSError as e:
                print(f"[CLEANUP] ERROR removing {dir_path}: {e}")
    return deleted_count


def tracker_coll():
    return db_v2.get_db()[CARD_TRACKER_COLL]


def detect_language(game_name):
    return "japanese" if game_name in JAPANESE_GAMES else "english"


def init_system():
    os.makedirs(BASE_LOCAL_PATH, exist_ok=True)
    tracker_coll().create_index([("image_name", 1), ("game_name", 1)])
    db_v2.record_run("web_app_v2.py")


def get_user_paths(username):
    user_dir = os.path.join(BASE_LOCAL_PATH, "users", username)
    paths = {
        "inbox": os.path.join(user_dir, "inbox"),
        "yes": os.path.join(user_dir, "yes"),
        "no": os.path.join(user_dir, "no")
    }
    for p in paths.values():
        os.makedirs(p, exist_ok=True)
        PROTECTED_ROOTS.add(os.path.normpath(p))
    return paths


# ==========================
# NEW FLOW: SERVE PENDING FROM card_tracker DIRECTLY
# ==========================

def pending_cards(limit=9):
    docs = tracker_coll().find({"status": "pending"}).limit(limit)
    cards = []
    for doc in docs:
        game = doc.get("game_name", "Uncategorized")
        image_id = doc.get("image_name", "")
        set_name = doc.get("set_name")
        file_path = doc.get("file_path")
        cards.append({
            "id": image_id,
            "game": game,
            "set": set_name,
            "url": f"/api/card/{game}/{image_id}",
            "path": file_path or os.path.join(game, image_id + ".jpg")
        })
    return cards


# ==========================
# FLASK ROUTES
# ==========================

@app.before_request
def log_ip():
    if VERBOSE:
        print(f"[CONN] {request.remote_addr} -> {request.method} {request.path}")


@app.route('/')
def index():
    return render_template('grid_index.html')


@app.route('/api/shutdown', methods=['POST'])
def shutdown():
    print("Server shutting down...")
    os.kill(os.getpid(), signal.SIGINT)
    return jsonify({"status": "shutdown"})


@app.route('/api/stats')
def api_stats():
    user = request.args.get('user')
    if user not in active_users: return jsonify({"error": "invalid"}), 403

    # card_tracker counts
    pending_count = tracker_coll().count_documents({"status": "pending"})

    # today's date as a string (matches processed_at format: YYYY-MM-DD)
    today = datetime.now().strftime("%Y-%m-%d")

    # DONE = cards marked yes today (rolling daily total)
    today_done = tracker_coll().count_documents({
        "status": "yes",
        "processed_at": {"$regex": f"^{today}"}
    })

    # TOTAL DONE = old base + ALL yes-marked cards ever
    BASE_DONE = 1880868
    current_done = tracker_coll().count_documents({"status": "yes"})
    total_done_count = BASE_DONE + current_done

    return jsonify({
        "inbox": pending_count,
        "pending": pending_count,
        "total": today_done,
        "total_done": total_done_count,
        "folder": user_prefs.get(user, "WAITING") or "ALL"
    })


@app.route('/api/next_batch')
def api_next_batch():
    user = request.args.get('user')
    if user not in active_users: return jsonify({"error": "invalid"}), 403
    cards = pending_cards(9)
    return jsonify({"batch": cards})


@app.route('/api/card/<game>/<image_id>')
def serve_card(game, image_id):
    doc = tracker_coll().find_one({"image_name": image_id, "game_name": game})
    if not doc or not doc.get("file_path"):
        return "Not found", 404
    fpath = doc["file_path"]
    if not os.path.exists(fpath):
        return "Not found", 404
    return send_file(fpath)


@app.route('/api/decision_batch', methods=['POST'])
def api_decision_batch():
    data = request.json
    user = data['user']
    if user not in active_users: return jsonify({"error": "invalid"}), 403
    selected_no = set(data.get('selected', []))
    all_cards = data.get('all', [])

    moved = 0
    for card in all_cards:
        image_id = card['id']
        game = card['game']
        dec = 'no' if image_id in selected_no else 'yes'
        db_v2.tracker_mark_reviewed(image_id, game, dec)
        moved += 1

    print(f"[MOVE] Batch done: {moved} files for {user} ({len(selected_no)} no, {moved - len(selected_no)} yes)")
    return jsonify({"status": "success", "moved": moved})


@app.route('/api/undo', methods=['POST'])
def api_undo():
    user = request.json.get('user')
    if not user_history.get(user): return jsonify({"status": "error"}), 400
    batch = user_history[user].pop()

    undone = 0
    for last in batch:
        db_v2.tracker_mark_reviewed(last["id"], last["game"], "pending")
        undone += 1

    print(f"[UNDO] Reversed {undone} files for {user} from last batch")
    return jsonify({"status": "success", "undone": undone})


# ==========================
# SYNC (kept for compatibility — uploader handles Immich now)
# ==========================

@app.route('/api/sync_to_drive', methods=['POST'])
def sync_to_drive():
    user = request.json.get('user')
    print(f"[SYNC] {user}: sync to drive is retired — use the uploader for Immich.")
    return jsonify({"status": "success", "moved": 0, "deleted": 0})


@app.route('/api/sync_status')
def sync_status():
    return jsonify(sync_progress)


@app.route('/api/list_folders')
def list_folders():
    flds = [d for d in os.listdir(DRIVE_SOURCE) if os.path.isdir(os.path.join(DRIVE_SOURCE, d))] if os.path.exists(
        DRIVE_SOURCE) else []
    flds.sort(key=str.lower)
    return jsonify({"folders": flds})


@app.route('/api/set_folder', methods=['POST'])
def set_folder():
    data = request.json
    user, folder = data.get('user'), data.get('folder')
    if user in active_users:
        user_prefs[user] = None if folder == "ALL" else folder
    return jsonify({"status": "success"})


if __name__ == '__main__':
    init_system()
    print("Card Sorter Server Active on http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=FLASK_DEBUG, threaded=True)
