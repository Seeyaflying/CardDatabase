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
VERBOSE = False  # controls only [CONN] noise; change logging and moves/syncs always print

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


# ==========================
# FETCH LOGIC (manual + auto)
# ==========================

def _fetch_core(user, tag, inbox_count):
    """Shared scan + dedup + copy used by both fetch paths.
    Returns the number of images copied into the inbox."""
    paths = get_user_paths(user)
    to_copy = []
    target = user_prefs.get(user)

    with download_lock:
        if target and target != "ALL":
            scan_root = os.path.join(DRIVE_SOURCE, target)
            scan_paths = [scan_root] if os.path.isdir(scan_root) else []
            print(f"{tag} {user}: scanning folder '{target}' (inbox at {inbox_count})")
        else:
            if os.path.exists(DRIVE_SOURCE):
                scan_paths = [os.path.join(DRIVE_SOURCE, d) for d in os.listdir(DRIVE_SOURCE)
                              if os.path.isdir(os.path.join(DRIVE_SOURCE, d))]
                if target == "ALL":
                    random.shuffle(scan_paths)
                print(f"{tag} {user}: scanning source root ({len(scan_paths)} game folders)")
            else:
                scan_paths = []
                print(f"{tag} {user}: WARNING - source {DRIVE_SOURCE} not found")

        for scan_root in scan_paths:
            if not os.path.exists(scan_root) or len(to_copy) >= SYNC_BATCH_SIZE: continue
            for root, _, files in os.walk(scan_root):
                for f in files:
                    if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                        drive_p = os.path.join(root, f)
                        rel_p = os.path.relpath(drive_p, DRIVE_SOURCE)
                        to_copy.append((drive_p, os.path.join(paths['inbox'], rel_p)))
                        if len(to_copy) >= SYNC_BATCH_SIZE: break

        print(f"{tag} {user}: found {len(to_copy)} candidates before dedup")

        # BATCHED dedup check + skip anything already in the inbox
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
                if not os.path.exists(lp)
                and (os.path.splitext(os.path.relpath(dp, DRIVE_SOURCE).replace("\\", "/").split("/")[-1])[0].replace("_200w", ""),
                     os.path.relpath(dp, DRIVE_SOURCE).replace("\\", "/").split("/")[0],
                     detect_language(os.path.relpath(dp, DRIVE_SOURCE).replace("\\", "/").split("/")[0])) not in processed
            ]
            print(f"{tag} {user}: {len(to_copy)} new after dedup ({len(keys) - len(processed)} already processed)")

        if to_copy:
            print(f"{tag} {user}: copying {len(to_copy)} images ({(len(to_copy)/SYNC_BATCH_SIZE)*100:.1f}% of batch cap)...")
            copied = 0
            errors = 0
            for dp, lp in to_copy:
                try:
                    os.makedirs(os.path.dirname(lp), exist_ok=True)
                    shutil.copy2(dp, lp)
                    copied += 1
                    print(f"{tag} {user}: downloaded {copied}: {os.path.basename(dp)}")
                except Exception as e:
                    errors += 1
                    print(f"{tag} {user}: ERROR copying {os.path.basename(dp)}: {e}")
            if errors:
                print(f"{tag} {user}: {copied} copied, {errors} FAILED")
            else:
                print(f"{tag} {user}: DONE - {copied} images added to inbox")
            games = Counter(
                os.path.relpath(lp, paths['inbox']).split(os.sep)[0] for _, lp in to_copy)
            for g, c in games.items():
                print(f"  {g}: {c}")
        else:
            print(f"{tag} {user}: nothing new to fetch")

        return len(to_copy)


def manual_fetch(user):
    """FETCH button: always pulls a full batch, ignores threshold and WAITING pref."""
    tag = "[FETCH-BTN]"
    paths = get_user_paths(user)
    inbox_count = sum(len(files) for r, _, files in os.walk(paths['inbox']))
    return _fetch_core(user, tag, inbox_count)


def auto_fetch(user):
    """Background worker: only tops up if inbox is under MIN_THRESHOLD and pref isn't WAITING."""
    tag = "[FETCH-AUTO]"
    paths = get_user_paths(user)
    inbox_count = sum(len(files) for r, _, files in os.walk(paths['inbox']))

    if inbox_count >= MIN_THRESHOLD:
        print(f"{tag} {user}: inbox already has {inbox_count} items, skipping")
        return 0

    if user_prefs.get(user) == "WAITING":
        print(f"{tag} {user}: pref WAITING, not filling inbox")
        return 0

    return _fetch_core(user, tag, inbox_count)


def auto_sync_worker():
    """Background thread: auto_fetch every 60 seconds."""
    while True:
        for user in list(active_users):
            try:
                auto_fetch(user)
            except Exception as e:
                print(f"[FETCH-AUTO] {user}: worker error - {e}")
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
    return render_template('grid_index.html')


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
    copied = manual_fetch(user)
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


# ==========================
# SINGLE-CARD ROUTES (kept for compatibility)
# ==========================

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
        print(f"Moved to {dec}: {rel}")
        progress_coll().update_one(
            {"image_name": clean_id, "game_name": game_name, "language": lang},
            {"$set": {
                "status": dec,
                "processed_at": datetime.now().strftime("%Y-%m-%d %H:%M")
            }},
            upsert=True
        )
        # Wrapped in [] so it matches the batch format used by /api/undo
        user_history[user].append([{"rel": rel, "dest": dest, "id": clean_id, "game": game_name, "lang": lang}])
    return jsonify({"status": "success"})


@app.route('/api/undo', methods=['POST'])
def api_undo():
    user = request.json.get('user')
    if not user_history.get(user): return jsonify({"status": "error"}), 400
    batch = user_history[user].pop()

    undone = 0
    for last in batch:
        inbox_path = os.path.join(get_user_paths(user)['inbox'], last["rel"])
        if os.path.exists(last["dest"]):
            os.makedirs(os.path.dirname(inbox_path), exist_ok=True)
            shutil.move(last["dest"], inbox_path)
            progress_coll().delete_one(
                {"image_name": last["id"], "game_name": last["game"], "language": last["lang"]})
            undone += 1

    print(f"[UNDO] Reversed {undone} files for {user} from last batch")
    return jsonify({"status": "success", "undone": undone})


# ==========================
# 3x3 GRID ROUTES
# ==========================

@app.route('/api/next_batch')
def api_next_batch():
    user = request.args.get('user')
    paths = get_user_paths(user)
    candidates = []
    for root, _, files in os.walk(paths['inbox']):
        for f in files:
            if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                rel = os.path.relpath(os.path.join(root, f), paths['inbox'])
                candidates.append({"url": f"/images/{user}/{rel.replace(os.sep, '/')}", "path": rel})
    random.shuffle(candidates)
    return jsonify({"batch": candidates[:9]})


@app.route('/api/decision_batch', methods=['POST'])
def api_decision_batch():
    data = request.json
    user = data['user']
    selected_no = set(data.get('selected', []))
    all_paths = data.get('all', [])
    paths = get_user_paths(user)

    batch_record = []
    moved = 0
    for rel in all_paths:
        dec = 'no' if rel in selected_no else 'yes'

        parts = rel.replace("\\", "/").split("/")
        game_name = parts[0] if len(parts) > 1 else "Uncategorized"
        name_only = os.path.splitext(parts[-1])[0]
        lang = detect_language(game_name)
        clean_id = name_only.replace("_200w", "")

        src = os.path.join(paths['inbox'], rel)
        dest = os.path.join(paths['yes'] if dec == 'yes' else paths['no'], rel)

        if os.path.exists(src):
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.move(src, dest)
            print(f"Moved to {dec}: {rel}")
            progress_coll().update_one(
                {"image_name": clean_id, "game_name": game_name, "language": lang},
                {"$set": {
                    "status": dec,
                    "processed_at": datetime.now().strftime("%Y-%m-%d %H:%M")
                }},
                upsert=True
            )
            batch_record.append(
                {"rel": rel, "dest": dest, "id": clean_id, "game": game_name, "lang": lang})
            moved += 1

    if batch_record:
        user_history[user].append(batch_record)

    print(f"[MOVE] Batch done: {moved} files for {user} ({len(selected_no)} no, {moved - len(selected_no)} yes)")
    return jsonify({"status": "success", "moved": moved})


@app.route('/api/sync_to_drive', methods=['POST'])
def sync_to_drive():
    user = request.json.get('user')
    paths = get_user_paths(user)
    moved_count = 0
    deleted_count = 0
    delete_failures = 0

    print(f"[SYNC] Source root exists? {os.path.exists(DRIVE_SOURCE)} -> {DRIVE_SOURCE}")

    total = 0
    for label, dr_root, loc_root in [('YES', DRIVE_YES_DIR, paths['yes']), ('NO', DRIVE_NO_DIR, paths['no'])]:
        if os.path.exists(loc_root):
            total += sum(len(files) for r, d, files in os.walk(loc_root))
    sync_progress.update({"active": True, "done": 0, "total": total, "current": ""})
    print(f"[SYNC] Starting upload for {user}: {total} files...")

    with download_lock:
        for label, dr_root, loc_root in [('YES', DRIVE_YES_DIR, paths['yes']), ('NO', DRIVE_NO_DIR, paths['no'])]:
            if not os.path.exists(loc_root):
                continue
            for root, _, files in os.walk(loc_root):
                for f in files:
                    l_path = os.path.join(root, f)
                    rel = os.path.relpath(l_path, loc_root)
                    d_path = os.path.join(dr_root, rel)
                    os.makedirs(os.path.dirname(d_path), exist_ok=True)
                    shutil.move(l_path, d_path)
                    moved_count += 1
                    sync_progress.update({"done": moved_count, "current": rel})
                    print(f"[UPLOAD] {label}: {rel}")

                    orig = os.path.join(DRIVE_SOURCE, rel)
                    if os.path.exists(orig):
                        try:
                            os.remove(orig)
                            deleted_count += 1
                            print(f"[SYNC] Deleted source: {rel}")
                        except Exception as e:
                            delete_failures += 1
                            print(f"[SYNC] ERROR deleting source {orig}: {e}")
                    else:
                        print(f"[SYNC] Source already gone or not found (T: content for {rel}): {'MISSING' if not os.path.exists(DRIVE_SOURCE) else 'no match at ' + orig}")
        recursive_cleanup(os.path.join(BASE_LOCAL_PATH, "users", user))
        recursive_cleanup(DRIVE_SOURCE)

    sync_progress.update({"active": False, "current": ""})
    print(f"[SYNC] Uploaded {moved_count} files for {user}; deleted {deleted_count} from source; {delete_failures} delete failures")
    return jsonify({"status": "success", "moved": moved_count, "deleted": deleted_count})

@app.route('/api/sync_status')
def sync_status():
    return jsonify(sync_progress)


if __name__ == '__main__':
    init_system()
    threading.Thread(target=auto_sync_worker, daemon=True).start()
    print("Card Sorter Server Active on http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=FLASK_DEBUG, threaded=True)