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
user_prefs = {"seeya": "ALL", "riverleaf": "ALL"}
user_history = {"seeya": [], "riverleaf": []}

SYNC_BATCH_SIZE = 1500
MIN_THRESHOLD = 300
MAX_DOWNLOAD_THREADS = 10
download_lock = threading.Lock()

sync_progress = {"active": False, "done": 0, "total": 0, "current": ""}




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

def find_card_file(image_id, search_roots):
    """Locate a file whose stem matches image_id (handles _200w / any extension).
    Returns the absolute path or None."""
    for root in search_roots:
        if not os.path.isdir(root):
            continue
        for dirpath, _, files in os.walk(root):
            for f in files:
                if os.path.splitext(f)[0].replace("_200w", "") == image_id:
                    return os.path.join(dirpath, f)
    return None


def move_to_upload(image_id, game):
    """Physically move a YES card from New Cards into Card Upload,
    printing an explicit confirmation for every file."""
    src = find_card_file(image_id, [DRIVE_SOURCE])
    if not src:
        print(f"[MOVE] ✗ {image_id} [{game}] — SOURCE NOT FOUND, file left in New Cards")
        return False

    game_name = (game or "").strip() or "Uncategorized"
    dest_dir = os.path.join(DRIVE_YES_DIR, game_name) if game_name != "Uncategorized" else DRIVE_YES_DIR
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, os.path.basename(src))
    base, ext = os.path.splitext(dest)
    n = 1
    while os.path.exists(dest):
        dest = f"{base}_{n}{ext}"
        n += 1

    try:
        shutil.move(src, dest)
    except Exception as e:
        print(f"[MOVE] ✗ {image_id} [{game_name}] — MOVE FAILED ({e}), file left in New Cards")
        return False

    if os.path.exists(dest):
        print(f"[MOVE] ✓ {image_id} [{game_name}]\n"
              f"      {os.path.relpath(src, DRIVE_SOURCE)}  ->  {os.path.relpath(dest, DRIVE_YES_DIR)}")
        return True
    else:
        print(f"[MOVE] ✓ DB marked yes but file not verified at destination for {image_id}")
        return True


def pending_cards(limit=9, folder=None):
    """Return up to `limit` pending cards from card_tracker, optionally filtered
    to one game folder. Skips anything already yes/no."""
    query = {"status": "pending"}
    if folder and folder != "ALL":
        query["game_name"] = folder
    docs = tracker_coll().find(query).limit(limit)
    cards = []
    for doc in docs:
        game = doc.get("game_name", "Uncategorized")
        image_id = doc.get("image_name", "")
        set_name = doc.get("set_name")
        # Build a path the app can serve. Files live under DRIVE_SOURCE.
        rel = os.path.join(game, image_id + ".jpg")
        cards.append({
            "id": image_id,
            "game": game,
            "set": set_name,
            "url": f"/api/card/{game}/{image_id}",
            "path": rel
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

    folder = user_prefs.get(user, "ALL") or "ALL"

    # Pending count, filtered to the current folder
    pending_query = {"status": "pending"}
    if folder != "ALL":
        pending_query["game_name"] = folder
    pending_count = tracker_coll().count_documents(pending_query)

    today = datetime.now().strftime("%Y-%m-%d")
    today_done = tracker_coll().count_documents({
        "status": "yes",
        "processed_at": {"$regex": f"^{today}"}
    })

    BASE_DONE = 1880868
    current_done = tracker_coll().count_documents({"status": "yes"})
    total_done_count = BASE_DONE + current_done

    return jsonify({
        "inbox": pending_count,
        "pending": pending_count,
        "total": today_done,
        "total_done": total_done_count,
        "folder": folder
    })


@app.route('/api/next_batch')
def api_next_batch():
    user = request.args.get('user')
    if user not in active_users: return jsonify({"error": "invalid"}), 403
    folder = user_prefs.get(user, "ALL")
    cards = pending_cards(9, folder)
    return jsonify({"batch": cards})


@app.route('/api/card/<game>/<image_id>')
def serve_card(game, image_id):
    """Serve the actual image file. Looks in New Cards first, then Card Upload
    (so a moved YES card still displays, including after an undo)."""
    src = find_card_file(image_id, [DRIVE_SOURCE, DRIVE_YES_DIR])
    if src:
        return send_from_directory(os.path.dirname(src), os.path.basename(src))
    return "Not found", 404


@app.route('/api/decision_batch', methods=['POST'])
def api_decision_batch():
    data = request.json
    user = data['user']
    if user not in active_users: return jsonify({"error": "invalid"}), 403
    selected_no = set(data.get('selected', []))
    all_cards = data.get('all', [])

    moved = 0
    batch = []  # <-- record the batch so undo can reverse it
    for card in all_cards:
        image_id = card['id']
        game = card['game']
        dec = 'no' if image_id in selected_no else 'yes'
        db_v2.tracker_mark_reviewed(image_id, game, dec)
        batch.append({"id": image_id, "game": game})
        moved += 1
        if dec == 'yes':
            move_to_upload(image_id, game)  # <-- physically move YES files to Card Upload

    user_history[user].append(batch)  # <-- FIX: enables undo

    print(f"[MOVE] Batch done: {moved} files for {user} ({len(selected_no)} no, {moved - len(selected_no)} yes)")
    return jsonify({"status": "success", "moved": moved})


@app.route('/api/skip_broken', methods=['POST'])
def skip_broken():
    """Mark a card that failed to load as 'no' so it leaves the queue,
    then return a fresh batch so the grid refills."""
    data = request.json
    user = data['user']
    if user not in active_users: return jsonify({"error": "invalid"}), 403
    cards = data.get('cards', [])
    for card in cards:
        db_v2.tracker_mark_reviewed(card['id'], card['game'], 'no')
    print(f"[SKIP] Skipped {len(cards)} unloadable card(s) for {user}")
    folder = user_prefs.get(user, "ALL")
    return jsonify({"status": "success", "batch": pending_cards(9, folder)})


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
