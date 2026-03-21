import os
import sqlite3
import shutil
import threading
import time
import random
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import unquote
from flask import Flask, render_template, send_from_directory, jsonify, request
from flask_cors import CORS

app = Flask(__name__, template_folder='utils')
CORS(app)

# ==============================================================
# 1. PLATFORM DETECTION & CONFIGURATION
# ==============================================================
IS_WINDOWS = os.name == 'nt'

# The SQLite DB stays relative to the script
SKIPPED_DB = "skipped_images.sqlite"

if IS_WINDOWS:
    # Windows Native Paths
    DRIVE_SOURCE = r"G:\My Drive\New Cards"
    DRIVE_YES_DIR = r"G:\My Drive\Card Database"
    DRIVE_NO_DIR = r"G:\My Drive\Skipped Cards"
    BASE_LOCAL_PATH = r"C:\Users\seeya\OneDrive\Desktop\Cards"
else:
    # Ubuntu Paths (Assumes rclone mount at ~/Desktop/GDrive)
    DRIVE_SOURCE = os.path.expanduser("~/Desktop/GDrive/New Cards")
    DRIVE_YES_DIR = os.path.expanduser("~/Desktop/GDrive/Card Database")
    DRIVE_NO_DIR = os.path.expanduser("~/Desktop/GDrive/Skipped Cards")
    # Local working directory on Ubuntu SSD (Faster for triage than GDrive)
    BASE_LOCAL_PATH = os.path.expanduser("~/Desktop/Cards_Triage_Local")

# List of folders that must NEVER be deleted, even if empty
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
user_history = {"seeya": []}  # Added riverleaf in get_user_paths dynamically if needed

SYNC_BATCH_SIZE = 1500
MIN_THRESHOLD = 300
MAX_DOWNLOAD_THREADS = 10
download_lock = threading.Lock()


# ==========================
# HELPER FUNCTIONS
# ==========================

def recursive_cleanup(root_path):
    """Deletes empty folders recursively from the bottom up, skipping protected ones."""
    if not os.path.exists(root_path):
        return 0

    deleted_count = 0
    # topdown=False is critical: it cleans children before parents
    for root, dirs, files in os.walk(root_path, topdown=False):
        for name in dirs:
            dir_path = os.path.normpath(os.path.join(root, name))

            if dir_path in PROTECTED_ROOTS:
                continue

            try:
                if not os.listdir(dir_path):
                    os.rmdir(dir_path)
                    print(f"   [CLEANUP] Removed empty folder: {dir_path}")
                    deleted_count += 1
            except OSError:
                pass
    return deleted_count


def init_system():
    """Initializes the synchronized database schema."""
    os.makedirs(BASE_LOCAL_PATH, exist_ok=True)
    conn = sqlite3.connect(SKIPPED_DB)
    # Using triple quotes for cleaner SQL
    conn.execute('''CREATE TABLE IF NOT EXISTS progress
    (
        image_name
        TEXT,
        game_name
        TEXT,
        language
        TEXT,
        status
        TEXT,
        processed_at
        TEXT,
        PRIMARY
        KEY
                    (
        image_name,
        game_name,
        language
                    ))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS skipped_images
    (
        image_name
        TEXT,
        game_name
        TEXT,
        language
        TEXT,
        added_at
        TEXT,
        PRIMARY
        KEY
                    (
        image_name,
        game_name,
        language
                    ))''')
    conn.commit()
    conn.close()


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

    if username not in user_history:
        user_history[username] = []

    return paths


def is_processed_by_anyone(rel_path):
    parts = rel_path.split(os.sep)
    if len(parts) < 2: return False
    game_name, filename = parts[0], parts[-1]
    name_only = os.path.splitext(filename)[0]

    # Logic for language detection
    lang = "english" if "_200w" in name_only else "japanese"
    image_id = name_only.replace("_200w", "") if lang == "english" else name_only

    conn = sqlite3.connect(SKIPPED_DB)
    res = conn.execute('SELECT 1 FROM progress WHERE image_name = ? AND game_name = ? AND language = ?',
                       (image_id, game_name, lang)).fetchone()
    conn.close()
    return res is not None


def auto_sync_worker():
    """Background thread to keep user inboxes full from the Google Drive Source."""
    while True:
        if not download_lock.locked():
            for user in list(active_users):
                if user_prefs.get(user) == "WAITING": continue

                paths = get_user_paths(user)
                # Fast file count check
                inbox_count = sum([len(files) for r, d, files in os.walk(paths['inbox'])])

                if inbox_count < MIN_THRESHOLD:
                    with download_lock:
                        to_copy = []
                        target = user_prefs.get(user)

                        if target and target != "ALL":
                            scan_paths = [os.path.join(DRIVE_SOURCE, target)]
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
                                if len(to_copy) >= SYNC_BATCH_SIZE: break
                                for f in files:
                                    if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                                        drive_p = os.path.join(root, f)
                                        rel_p = os.path.relpath(drive_p, DRIVE_SOURCE)

                                        if not is_processed_by_anyone(rel_p):
                                            in_use = any(os.path.exists(os.path.join(get_user_paths(u)['inbox'], rel_p))
                                                         for u in active_users)
                                            if not in_use:
                                                to_copy.append((drive_p, os.path.join(paths['inbox'], rel_p)))
                                                if len(to_copy) >= SYNC_BATCH_SIZE: break

                        if to_copy:
                            print(f"[SYNC] Pushing {len(to_copy)} images to {user}'s inbox...")
                            with ThreadPoolExecutor(max_workers=MAX_DOWNLOAD_THREADS) as ex:
                                for dp, lp in to_copy:
                                    os.makedirs(os.path.dirname(lp), exist_ok=True)
                                    shutil.copy2(dp, lp)
        time.sleep(15)


# ==========================
# FLASK ROUTES
# ==========================

@app.route('/')
def index():
    return "<h1>TCG Triage Server Active</h1><p>Connect via the web interface.</p>"


@app.route('/api/stats')
def api_stats():
    user = request.args.get('user')
    if user not in active_users: return jsonify({"error": "invalid"}), 403
    paths = get_user_paths(user)
    inbox_c = sum([len(files) for r, d, files in os.walk(paths['inbox'])])
    pending_sync = sum([len(files) for r, d, files in os.walk(paths['yes'])]) + \
                   sum([len(files) for r, d, files in os.walk(paths['no'])])

    conn = sqlite3.connect(SKIPPED_DB)
    total_done = conn.execute("SELECT COUNT(*) FROM progress").fetchone()[0]
    conn.close()

    return jsonify({
        "inbox": inbox_c,
        "pending": pending_sync,
        "total": total_done,
        "folder": user_prefs.get(user, "WAITING")
    })


@app.route('/api/list_folders')
def list_folders():
    if not os.path.exists(DRIVE_SOURCE): return jsonify({"folders": []})
    flds = [d for d in os.listdir(DRIVE_SOURCE) if os.path.isdir(os.path.join(DRIVE_SOURCE, d))]
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
    # unquote handles URL-encoded filenames (common in TCG sets)
    return send_from_directory(get_user_paths(user)['inbox'], unquote(filename))


@app.route('/api/next')
def api_next():
    user = request.args.get('user')
    paths = get_user_paths(user)
    for root, _, files in os.walk(paths['inbox']):
        for f in files:
            if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                rel = os.path.relpath(os.path.join(root, f), paths['inbox'])
                # Replace backslashes with forward slashes for URL routing
                return jsonify({"url": f"/images/{user}/{rel.replace(os.sep, '/')}", "path": rel})
    return jsonify({"url": None})


@app.route('/api/decision', methods=['POST'])
def api_decision():
    data = request.json
    user, rel, dec = data['user'], data['path'], data['decision']

    # Path parsing logic
    parts = rel.split(os.sep)
    game_name = parts[0] if len(parts) > 1 else "Uncategorized"
    filename = parts[-1]
    name_only = os.path.splitext(filename)[0]
    lang = "english" if "_200w" in name_only else "japanese"
    clean_id = name_only.replace("_200w", "") if lang == "english" else name_only

    paths = get_user_paths(user)
    src = os.path.join(paths['inbox'], rel)
    dest = os.path.join(paths['yes'] if dec == 'yes' else paths['no'], rel)

    if os.path.exists(src):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.move(src, dest)

        conn = sqlite3.connect(SKIPPED_DB)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        conn.execute('INSERT OR REPLACE INTO progress VALUES (?, ?, ?, ?, ?)',
                     (clean_id, game_name, lang, dec, timestamp))
        conn.commit()
        conn.close()

        user_history[user].append({
            "rel": rel, "dest": dest, "drive_orig": os.path.join(DRIVE_SOURCE, rel),
            "id": clean_id, "game": game_name, "lang": lang
        })
    return jsonify({"status": "success"})


@app.route('/api/undo', methods=['POST'])
def api_undo():
    user = request.json.get('user')
    if not user_history.get(user): return jsonify({"status": "error"}), 400

    last = user_history[user].pop()
    rel, src, c_id, g_name, lang = last["rel"], last["dest"], last["id"], last["game"], last["lang"]
    dest = os.path.join(get_user_paths(user)['inbox'], rel)

    if os.path.exists(src):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.move(src, dest)
        conn = sqlite3.connect(SKIPPED_DB)
        conn.execute('DELETE FROM progress WHERE image_name = ? AND game_name = ? AND language = ?',
                     (c_id, g_name, lang))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    return jsonify({"status": "error"}), 404


@app.route('/api/sync_to_drive', methods=['POST'])
def sync_to_drive():
    user = request.json.get('user')
    paths = get_user_paths(user)
    moved_count, folders_removed = 0, 0

    with download_lock:
        print(f"\n>>> SYNCING [{user.upper()}] TO GOOGLE DRIVE...")
        mapping = [('YES', DRIVE_YES_DIR, paths['yes']), ('NO', DRIVE_NO_DIR, paths['no'])]
        for label, dr_root, loc_root in mapping:
            if not os.path.exists(loc_root): continue
            for root, _, files in os.walk(loc_root):
                for f in files:
                    l_path = os.path.join(root, f)
                    rel = os.path.relpath(l_path, loc_root)
                    d_path = os.path.join(dr_root, rel)

                    os.makedirs(os.path.dirname(d_path), exist_ok=True)
                    shutil.move(l_path, d_path)

                    # Delete original from source to clean up
                    orig = os.path.join(DRIVE_SOURCE, rel)
                    if os.path.exists(orig):
                        try:
                            os.remove(orig)
                            moved_count += 1
                        except:
                            pass

        print(f">>> STARTING SAFE FOLDER CLEANUP...")
        folders_removed += recursive_cleanup(os.path.join(BASE_LOCAL_PATH, "users", user))
        folders_removed += recursive_cleanup(DRIVE_SOURCE)

    print(f">>> SYNC COMPLETE: {moved_count} files moved | {folders_removed} folders deleted.")
    return jsonify({"status": "success", "moved": moved_count, "deleted_folders": folders_removed})


if __name__ == '__main__':
    init_system()
    # Start the background sync worker
    threading.Thread(target=auto_sync_worker, daemon=True).start()

    # Run server - host 0.0.0.0 makes it accessible on your local network
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)