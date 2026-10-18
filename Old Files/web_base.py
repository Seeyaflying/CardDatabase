import os
import shutil
import threading
import time
import random
import signal
import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import unquote
from flask import Flask, render_template, send_from_directory, jsonify, request
from flask_cors import CORS

import config
import db

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
VERBOSE = False  # controls only [CONN]/[UPLOAD] noise; change logging always runs

# ==============================================================
# 1. PLATFORM DETECTION & CONFIGURATION
# ==============================================================
IS_WINDOWS = os.name == 'nt'
PROGRESS_COLLECTION = config.PROGRESS_COLLECTION

if IS_WINDOWS:
    DRIVE_SOURCE = r"T:\Full Card Database\New Cards"
    DRIVE_YES_DIR = r"T:\Full Card Database\Card Upload"
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
    if not os.path.exists(root_path): return 0
    deleted_count = 0
    for root, dirs, files in os.walk(root_path, topdown=False):
        for name in dirs:
            dir_path = os.path.normpath(os.path.join(root, name))
            if dir_path in PROTECTED_ROOTS: continue
            try:
                if not os.listdir(dir_path):
                    os.rmdir(dir_path)
                    deleted_count += 1
            except OSError:
                pass
    return deleted_count


def progress_coll():
    return db.get_db()[PROGRESS_COLLECTION]


def detect_language(game_name):
    return "japanese" if game_name in JAPANESE_GAMES else "english"


def init_system():
    os.makedirs(BASE_LOCAL_PATH, exist_ok=True)
    progress_coll().create_index([("image_name", 1), ("game_name", 1), ("language", 1)])
    db.record_run("web_base.py")


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


def is_processed_by_anyone(rel_path):
    parts = rel_path.replace("\\", "/").split("/")
    if len(parts) < 2: return False
    game_name, filename = parts[0], parts[-1]
    name_only = os.path.splitext(filename)[0]
    lang = detect_language(game_name)
    image_id = name_only.replace("_200w", "")
    res = progress_coll().find_one(
        {"image_name": image_id, "game_name": game_name, "language": lang})
    return res is not None


def fill_inbox(user, force=False):
    """Copy up to SYNC_BATCH_SIZE new images into a user's inbox.
    force=True bypasses the MIN_THRESHOLD check (manual button)."""
    paths = get_user_paths(user)
    inbox_count = sum([len(files) for r, d, files in os.walk(paths['inbox'])])

    if not force and inbox_count >= MIN_THRESHOLD:
        return 0  # inbox full, skip

    with download_lock:
        to_copy = []
        target = user_prefs.get(user)

        if target and target != "ALL":
            scan_root = os.path.join(DRIVE_SOURCE, target)
            scan_paths = [scan_root] if os.path.isdir(scan_root) else []
        else:
            if os.path.exists(DRIVE_SOURCE):
                scan_paths = [os.path.join(DRIVE_SOURCE, d) for d in os.listdir(DRIVE_SOURCE)
                              if os.path.isdir(os.path.join(DRIVE_SOURCE, d))]
                if target == "ALL": random.shuffle(scan_paths)
            else:
                scan_paths = []

        for scan_root in scan_paths:
            if not os.path.exists(scan_root) or len(to_copy) >= SYNC_BATCH_SIZE: continue
            for root, _, files in os.walk(scan_root):
                for f in files:
                    if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                        drive_p = os.path.join(root, f)
                        rel_p = os.path.relpath(drive_p, DRIVE_SOURCE)
                        to_copy.append((drive_p, os.path.join(paths['inbox'], rel_p)))
                        if len(to_copy) >= SYNC_BATCH_SIZE: break

        # BATCHED dedup check
        if to_copy:
            keys = set()
            for dp, lp in to_copy:
                rel_p = os.path.relpath(dp, DRIVE_SOURCE).replace("\\", "/")
                parts = rel_p.split("/")
                if len(parts) < 2: continue
                game_name = parts[0]
                image_id = os.path.splitext(parts[-1])[0].replace("_200w", "")
                lang = detect_language(game_name)
                keys.add((image_id, game_name, lang))

            processed = set()
            if keys:
                query = {"$or": [
                    {"image_name": k[0], "game_name": k[1], "language": k[2]} for k in keys
                ]}
                for doc in progress_coll().find(query):
                    processed.add((doc["image_name"], doc["game_name"], doc["language"]))

            to_copy = [
                (dp, lp) for dp, lp in to_copy
                if (os.path.splitext(os.path.relpath(dp, DRIVE_SOURCE).replace("\\", "/").split("/")[-1])[0].replace("_200w", ""),
                    os.path.relpath(dp, DRIVE_SOURCE).replace("\\", "/").split("/")[0],
                    detect_language(os.path.relpath(dp, DRIVE_SOURCE).replace("\\", "/").split("/")[0])) not in processed
            ]

        if to_copy:
            print(f"[SYNC] Pushing {len(to_copy)} images to {user}...")  # always prints
            with ThreadPoolExecutor(max_workers=MAX_DOWNLOAD_THREADS) as ex:
                for dp, lp in to_copy:
                    os.makedirs(os.path.dirname(lp), exist_ok=True)
                    shutil.copy2(dp, lp)
            # Always print the per-game breakdown, regardless of VERBOSE
            games = Counter(
                os.path.relpath(lp, paths['inbox']).split(os.sep)[0] for _, lp in to_copy)
            for g, c in games.items():
                print(f"  {g}: {c}")

        return len(to_copy)


def auto_sync_worker():
    """Background thread to keep user inboxes full (uses force=False)."""
    while True:
        for user in list(active_users):
            if user_prefs.get(user) == "WAITING": continue
            fill_inbox(user, force=False)
        time.sleep(60)


# ==========================
# FLASK ROUTES
# ==========================

@app.before_request
def log_ip():
    if VERBOSE:
        print(f"[CONN] {request.remote_addr} -> {request.method} {request.path}")


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/shutdown', methods=['POST'])
def shutdown():
    print("Server shutting down...")
    os.kill(os.getpid(), signal.SIGINT)
    return jsonify({"status": "shutdown"})


@app.route('/api/fetch_now', methods=['POST'])
def fetch_now():
    """Manual endpoint: fill the inbox up to the batch cap regardless of threshold."""
    user = request.json.get('user')
    if user not in active_users:
        return jsonify({"error": "invalid"}), 403
    copied = fill_inbox(user, force=True)
    return jsonify({"status": "success", "copied": copied})


@app.route('/api/stats')
def api_stats():
    user = request.args.get('user')
    if user not in active_users: return jsonify({"error": "invalid"}), 403
    paths = get_user_paths(user)
    inbox_c = sum([len(files) for r, d, files in os.walk(paths['inbox'])])
    pending_sync = sum([len(files) for r, d, files in os.walk(paths['yes'])]) + \
                   sum([len(files) for r, d, files in os.walk(paths['no'])])

    total_done = progress_coll().count_documents({})

    return jsonify({
        "inbox": inbox_c,
        "pending": pending_sync,
        "total": total_done,
        "folder": user_prefs.get(user, "WAITING") or "ALL"
    })


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


@app.route('/images/<user>/<path:filename>')
def serve_image(user, filename):
    response = send_from_directory(get_user_paths(user)['inbox'], unquote(filename))
    response.cache_control.max_age = 31536000
    return response


@app.route('/api/next')
def api_next():
    user = request.args.get('user')
    paths = get_user_paths(user)
    for root, _, files in os.walk(paths['inbox']):
        for f in files:
            if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                rel = os.path.relpath(os.path.join(root, f), paths['inbox'])
                return jsonify({"url": f"/images/{user}/{rel.replace(os.sep, '/')}", "path": rel})
    return jsonify({"url": None})


@app.route('/api/decision', methods=['POST'])
def api_decision():
    data = request.json
    user, rel, dec = data['user'], data['path'], data['decision']

    parts = rel.replace("\\", "/").split("/")
    game_name = parts[0] if len(parts) > 1 else "Uncategorized"
    name_only = os.path.splitext(parts[-1])[0]
    lang = detect_language(game_name)
    clean_id = name_only.replace("_200w", "")

    paths = get_user_paths(user)
    src = os.path.join(paths['inbox'], rel)
    dest = os.path.join(paths['yes'] if dec == 'yes' else paths['no'], rel)

    if os.path.exists(src):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.move(src, dest)
        print(f"Moved to {dec}: {rel}")  # always prints
        progress_coll().update_one(
            {"image_name": clean_id, "game_name": game_name, "language": lang},
            {"$set": {
                "status": dec,
                "processed_at": datetime.now().strftime("%Y-%m-%d %H:%M")
            }},
            upsert=True
        )
        user_history[user].append({"rel": rel, "dest": dest, "id": clean_id, "game": game_name, "lang": lang})
    return jsonify({"status": "success"})


@app.route('/api/undo', methods=['POST'])
def api_undo():
    user = request.json.get('user')
    if not user_history.get(user): return jsonify({"status": "error"}), 400
    last = user_history[user].pop()
    dest = os.path.join(get_user_paths(user)['inbox'], last["rel"])
    if os.path.exists(last["dest"]):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.move(last["dest"], dest)
        progress_coll().delete_one(
            {"image_name": last["id"], "game_name": last["game"], "language": last["lang"]})
        return jsonify({"status": "success"})
    return jsonify({"status": "error"}), 404


@app.route('/api/sync_to_drive', methods=['POST'])
def sync_to_drive():
    user = request.json.get('user')
    paths = get_user_paths(user)
    moved_count = 0

    total = 0
    for label, dr_root, loc_root in [('YES', DRIVE_YES_DIR, paths['yes']), ('NO', DRIVE_NO_DIR, paths['no'])]:
        if os.path.exists(loc_root):
            total += sum(len(files) for r, d, files in os.walk(loc_root))
    sync_progress.update({"active": True, "done": 0, "total": total, "current": ""})

    with download_lock:
        for label, dr_root, loc_root in [('YES', DRIVE_YES_DIR, paths['yes']), ('NO', DRIVE_NO_DIR, paths['no'])]:
            if not os.path.exists(loc_root): continue
            for root, _, files in os.walk(loc_root):
                for f in files:
                    l_path = os.path.join(root, f)
                    rel = os.path.relpath(l_path, loc_root)
                    d_path = os.path.join(dr_root, rel)
                    os.makedirs(os.path.dirname(d_path), exist_ok=True)
                    shutil.move(l_path, d_path)
                    moved_count += 1
                    sync_progress.update({"done": moved_count, "current": rel})
                    if VERBOSE:
                        print(f"[UPLOAD] {label}: {rel}")

                    orig = os.path.join(DRIVE_SOURCE, rel)
                    if os.path.exists(orig):
                        try:
                            os.remove(orig)
                        except:
                            pass
        recursive_cleanup(os.path.join(BASE_LOCAL_PATH, "users", user))
        recursive_cleanup(DRIVE_SOURCE)

    sync_progress.update({"active": False, "current": ""})
    print(f"[SYNC] Uploaded {moved_count} files for {user}")  # always prints
    return jsonify({"status": "success", "moved": moved_count})


@app.route('/api/sync_status')
def sync_status():
    return jsonify(sync_progress)


if __name__ == '__main__':
    init_system()
    threading.Thread(target=auto_sync_worker, daemon=True).start()
    print("Card Sorter Server Active on http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=FLASK_DEBUG, threaded=True)
