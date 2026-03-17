import os, sqlite3, shutil, threading, time, random
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import unquote
from flask import Flask, render_template, send_from_directory, jsonify, request
from flask_cors import CORS

app = Flask(__name__, template_folder='utils')
CORS(app)

# ==========================
# CONFIGURATION
# ==========================
DRIVE_SOURCE = r"G:\My Drive\New Cards"
DRIVE_YES_DIR = r"G:\My Drive\Card Database"
DRIVE_NO_DIR = r"G:\My Drive\Skipped Cards"
BASE_LOCAL_PATH = r"C:\Users\seeya\OneDrive\Desktop\Cards"
SKIPPED_DB = "skipped_images.sqlite"

active_users = {"seeya", "riverleaf"}
user_prefs = {"seeya": "WAITING", "riverleaf": "WAITING"}
user_history = {"seeya": [], "riverleaf": []}

SYNC_BATCH_SIZE = 1500
MIN_THRESHOLD = 300
MAX_DOWNLOAD_THREADS = 10
download_lock = threading.Lock()


def init_system():
    if not os.path.exists(BASE_LOCAL_PATH): os.makedirs(BASE_LOCAL_PATH)
    conn = sqlite3.connect(SKIPPED_DB)
    # Ensure the core progress table exists
    conn.execute('''CREATE TABLE IF NOT EXISTS progress
                    (img_path TEXT, username TEXT, processed_at TEXT, status TEXT, 
                    PRIMARY KEY (img_path, username))''')
    # Ensure our categorized skip table exists
    conn.execute('''CREATE TABLE IF NOT EXISTS skipped_images 
                    (image_name TEXT, game_name TEXT, language TEXT, added_at TEXT,
                    PRIMARY KEY (image_name, game_name, language))''')
    conn.commit()
    conn.close()


def get_user_paths(username):
    user_dir = os.path.join(BASE_LOCAL_PATH, "users", username)
    paths = {"inbox": os.path.join(user_dir, "inbox"), "yes": os.path.join(user_dir, "yes"),
             "no": os.path.join(user_dir, "no")}
    for p in paths.values(): os.makedirs(p, exist_ok=True)
    return paths


def is_processed_by_anyone(file_path):
    conn = sqlite3.connect(SKIPPED_DB)
    res = conn.execute('SELECT 1 FROM progress WHERE img_path = ?', (file_path,)).fetchone()
    conn.close()
    return res is not None


def auto_sync_worker():
    while True:
        if not download_lock.locked():
            for user in list(active_users):
                if user_prefs[user] == "WAITING": continue
                paths = get_user_paths(user)
                inbox_count = sum([len(files) for r, d, files in os.walk(paths['inbox'])])
                if inbox_count < MIN_THRESHOLD:
                    with download_lock:
                        to_copy = []
                        target = user_prefs.get(user)
                        scan_paths = [os.path.join(DRIVE_SOURCE, target)] if (target and target != "ALL") else [
                            os.path.join(DRIVE_SOURCE, d) for d in os.listdir(DRIVE_SOURCE) if
                            os.path.isdir(os.path.join(DRIVE_SOURCE, d))]
                        if target == "ALL": random.shuffle(scan_paths)

                        for scan_root in scan_paths:
                            if not os.path.exists(scan_root) or len(to_copy) >= SYNC_BATCH_SIZE: continue
                            for root, _, files in os.walk(scan_root):
                                if len(to_copy) >= SYNC_BATCH_SIZE: break
                                for f in files:
                                    if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                                        drive_p = os.path.join(root, f)
                                        if not is_processed_by_anyone(drive_p):
                                            rel_p = os.path.relpath(drive_p, DRIVE_SOURCE)
                                            in_use = any(
                                                os.path.exists(os.path.join(get_user_paths(u)['inbox'], rel_p)) for u in
                                                active_users)
                                            if not in_use:
                                                to_copy.append((drive_p, os.path.join(paths['inbox'], rel_p)))
                                                if len(to_copy) >= SYNC_BATCH_SIZE: break
                        if to_copy:
                            with ThreadPoolExecutor(max_workers=MAX_DOWNLOAD_THREADS) as ex:
                                for dp, lp in to_copy:
                                    os.makedirs(os.path.dirname(lp), exist_ok=True)
                                    shutil.copy2(dp, lp)
        time.sleep(10)


@app.route('/')
def index(): return render_template('index.html')


@app.route('/api/stats')
def api_stats():
    user = request.args.get('user')
    if user not in active_users: return jsonify({"error": "invalid"}), 403

    paths = get_user_paths(user)

    # 1. Count files waiting to be sorted
    inbox_c = sum([len(files) for r, d, files in os.walk(paths['inbox'])])

    # 2. Count files ALREADY sorted but NOT YET synced (The Yes/No folders)
    yes_c = sum([len(files) for r, d, files in os.walk(paths['yes'])])
    no_c = sum([len(files) for r, d, files in os.walk(paths['no'])])
    pending_sync = yes_c + no_c

    # 3. Count total historical progress from DB
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
    flds = [d for d in os.listdir(DRIVE_SOURCE) if os.path.isdir(os.path.join(DRIVE_SOURCE, d))]
    flds.sort(key=str.lower);
    return jsonify({"folders": flds})


@app.route('/api/set_folder', methods=['POST'])
def set_folder():
    data = request.json
    user, folder = data.get('user'), data.get('folder')
    if user in active_users: user_prefs[user] = None if folder == "ALL" else folder
    return jsonify({"status": "success"})


@app.route('/images/<user>/<path:filename>')
def serve_image(user, filename):
    return send_from_directory(get_user_paths(user)['inbox'], unquote(filename))


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

    # 1. IDENTIFY GAME AND LANGUAGE
    # Assumes path like: "Pokemon/CardABC.jpg"
    parts = rel.split(os.sep)
    game_name = parts[0] if len(parts) > 1 else "Uncategorized"
    filename = parts[-1]

    # Language logic: _200w = English, otherwise Japanese
    lang = "english" if "_200w" in filename else "japanese"
    # We store the base ID (without the _200w suffix) for cleaner lookups
    clean_id = filename.replace("_200w", "").split('.')[0] if lang == "english" else filename.split('.')[0]

    paths = get_user_paths(user)
    src = os.path.join(paths['inbox'], rel)
    dest = os.path.join(paths['yes'] if dec == 'yes' else paths['no'], rel)
    drive_orig = os.path.join(DRIVE_SOURCE, rel)

    if os.path.exists(src):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.move(src, dest)

        conn = sqlite3.connect(SKIPPED_DB)
        # Log general progress
        conn.execute('INSERT OR REPLACE INTO progress VALUES (?, ?, ?, ?)',
                     (drive_orig, user, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), dec))

        # IF IT IS A 'NO' -> Add to our Master Skip List
        if dec == 'no':
            conn.execute('''INSERT
            OR IGNORE INTO skipped_images 
                            (image_name, game_name, language, added_at) 
                            VALUES (?, ?, ?, ?)''',
                         (clean_id, game_name, lang, datetime.now().strftime("%Y-%m-%d %H:%M")))

        conn.commit()
        conn.close()
        user_history[user].append({"rel": rel, "dest": dest, "drive_orig": drive_orig})

    return jsonify({"status": "success"})


@app.route('/api/undo', methods=['POST'])
def api_undo():
    user = request.json.get('user')
    if not user_history.get(user): return jsonify({"status": "error"}), 400
    last = user_history[user].pop()
    rel, src, drive_orig = last["rel"], last["dest"], last["drive_orig"]
    dest = os.path.join(get_user_paths(user)['inbox'], rel)
    if os.path.exists(src):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.move(src, dest)
        conn = sqlite3.connect(SKIPPED_DB)
        conn.execute('DELETE FROM progress WHERE img_path = ? AND username = ?', (drive_orig, user))
        conn.commit();
        conn.close()
        return jsonify({"status": "success"})
    return jsonify({"status": "error"}), 404


@app.route('/api/sync_to_drive', methods=['POST'])
def sync_to_drive():
    user = request.json.get('user')
    paths = get_user_paths(user)
    moved_count = 0
    drive_folders_removed = 0
    local_folders_removed = 0

    with download_lock:
        print("\n" + "=" * 40)
        print(f">>> SYNC & DEEP CLEAN: [{user.upper()}]")
        print("=" * 40)

        # 1. Move Local Files to Drive
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

                    orig = os.path.join(DRIVE_SOURCE, rel)
                    if os.path.exists(orig):
                        try:
                            os.remove(orig); moved_count += 1
                        except:
                            pass

        # 2. Clean DRIVE_SOURCE (ignoring hidden junk)
        for root, dirs, _ in os.walk(DRIVE_SOURCE, topdown=False):
            for d in dirs:
                d_full = os.path.join(root, d)
                if not any(f for f in os.listdir(d_full) if f not in ['.DS_Store', 'desktop.ini', 'Thumbs.db']):
                    try:
                        os.rmdir(d_full); drive_folders_removed += 1
                    except:
                        pass

        # 3. Clean LOCAL FOLDERS
        local_user_root = os.path.dirname(paths['inbox'])
        for root, dirs, _ in os.walk(local_user_root, topdown=False):
            for d in dirs:
                d_full = os.path.join(root, d)
                if not any(f for f in os.listdir(d_full) if f not in ['.DS_Store', 'desktop.ini', 'Thumbs.db']):
                    try:
                        os.rmdir(d_full); local_folders_removed += 1
                    except:
                        pass

        print(f" - Files moved: {moved_count}")
        print(f" - Drive folders purged: {drive_folders_removed}")
        print(f" - Local folders purged: {local_folders_removed}")
        print("=" * 40 + "\n")

    return jsonify({"status": "success", "moved": moved_count})


if __name__ == '__main__':
    init_system()
    threading.Thread(target=auto_sync_worker, daemon=True).start()
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)