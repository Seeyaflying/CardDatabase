import os, sqlite3, shutil, threading, time, random, signal, sys, logging, socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import unquote
from flask import Flask, render_template, send_from_directory, jsonify, request
from flask_cors import CORS

# Suppress Flask/Werkzeug logging for clean console
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

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

# Flags and Global Executors for Clean Shutdown
shutdown_event = threading.Event()
download_lock = threading.Lock()
upload_executor = ThreadPoolExecutor(max_workers=15)
download_executor = ThreadPoolExecutor(max_workers=25)

PROTECTED_ROOTS = {
    os.path.normpath(DRIVE_SOURCE),
    os.path.normpath(DRIVE_YES_DIR),
    os.path.normpath(DRIVE_NO_DIR),
    os.path.normpath(BASE_LOCAL_PATH),
    os.path.normpath(os.path.join(BASE_LOCAL_PATH, "users"))
}

active_users = {"seeya", "riverleaf"}
user_prefs = {"seeya": "WAITING", "riverleaf": "WAITING"}
user_history = {"seeya": [], "riverleaf": []}

# Thresholds
SYNC_BATCH_SIZE = 1000
MIN_THRESHOLD = 500


# ==========================
# HELPER FUNCTIONS
# ==========================

def get_local_ip():
    """Finds the actual local IP address of the machine."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Dummy connection to determine the interface IP
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP


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
            except:
                pass
    return deleted_count


def init_system():
    if not os.path.exists(BASE_LOCAL_PATH): os.makedirs(BASE_LOCAL_PATH)
    conn = sqlite3.connect(SKIPPED_DB)
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
    conn.commit()
    conn.close()


def get_user_paths(username):
    user_dir = os.path.join(BASE_LOCAL_PATH, "users", username)
    paths = {"inbox": os.path.join(user_dir, "inbox"), "yes": os.path.join(user_dir, "yes"),
             "no": os.path.join(user_dir, "no")}
    for p in paths.values():
        os.makedirs(p, exist_ok=True)
        PROTECTED_ROOTS.add(os.path.normpath(p))
    return paths


def is_processed_by_anyone(rel_path):
    parts = rel_path.split(os.sep)
    if len(parts) < 2: return False
    game_name, filename = parts[0], parts[-1]
    name_only = os.path.splitext(filename)[0]
    lang = "english" if "_200w" in name_only else "japanese"
    image_id = name_only.replace("_200w", "") if lang == "english" else name_only
    conn = sqlite3.connect(SKIPPED_DB)
    res = conn.execute('SELECT 1 FROM progress WHERE image_name = ? AND game_name = ? AND language = ?',
                       (image_id, game_name, lang)).fetchone()
    conn.close()
    return res is not None


# ==========================
# THREADED TASKS
# ==========================

def download_file_task(src, dst):
    try:
        if not os.path.exists(src): return False, "Missing"
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        return True, None
    except Exception as e:
        return False, str(e)


def fast_upload_file(l_path, d_path, orig_path):
    try:
        if shutdown_event.is_set(): return False
        os.makedirs(os.path.dirname(d_path), exist_ok=True)
        if not os.path.exists(l_path): return False
        shutil.move(l_path, d_path)
        if os.path.exists(orig_path):
            try:
                os.remove(orig_path)
            except:
                pass
        return True
    except Exception as e:
        print(f"   [!] Sync Error: {os.path.basename(l_path)} -> {e}", flush=True)
        return False


def auto_sync_worker():
    while not shutdown_event.is_set():
        try:
            if not download_lock.locked():
                for user in list(active_users):
                    if shutdown_event.is_set(): break
                    if user_prefs.get(user) == "WAITING": continue
                    paths = get_user_paths(user)
                    inbox_count = sum([len(f) for r, d, f in os.walk(paths['inbox'])])
                    if inbox_count < MIN_THRESHOLD:
                        with download_lock:
                            to_copy = []
                            target = user_prefs.get(user)
                            scan_paths = [os.path.join(DRIVE_SOURCE, target)] if target and target != "ALL" else \
                                [os.path.join(DRIVE_SOURCE, d) for d in os.listdir(DRIVE_SOURCE) if
                                 os.path.isdir(os.path.join(DRIVE_SOURCE, d))]
                            if target == "ALL": random.shuffle(scan_paths)
                            for scan_root in scan_paths:
                                if not os.path.exists(scan_root) or len(to_copy) >= SYNC_BATCH_SIZE: continue
                                for root, _, files in os.walk(scan_root):
                                    if len(to_copy) >= SYNC_BATCH_SIZE: break
                                    for f in files:
                                        if shutdown_event.is_set(): break
                                        if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                                            drive_p = os.path.join(root, f)
                                            rel_p = os.path.relpath(drive_p, DRIVE_SOURCE)
                                            if not is_processed_by_anyone(rel_p) and not any(
                                                    os.path.exists(os.path.join(get_user_paths(u)['inbox'], rel_p)) for
                                                    u in active_users):
                                                to_copy.append((drive_p, os.path.join(paths['inbox'], rel_p)))
                            if to_copy:
                                print(f"\n[DOWNLOAD] {user.upper()} | Syncing {len(to_copy)} images...", flush=True)
                                futures = {download_executor.submit(download_file_task, dp, lp): dp for dp, lp in
                                           to_copy}
                                for i, f in enumerate(as_completed(futures)):
                                    if shutdown_event.is_set(): break
                                    if (i + 1) % 100 == 0: print(f"   [DOWNLOAD] Progress: {i + 1}/{len(to_copy)}",
                                                                 flush=True)
        except:
            pass
        for _ in range(5):
            if shutdown_event.is_set(): break
            time.sleep(1)


# ==========================
# FLASK ROUTES
# ==========================

@app.route('/')
def index(): return render_template('index.html')


@app.route('/api/stats')
def api_stats():
    user = request.args.get('user')
    paths = get_user_paths(user)
    inbox_c = sum([len(f) for r, d, f in os.walk(paths['inbox'])])
    pending_sync = sum([len(f) for r, d, f in os.walk(paths['yes'])]) + sum(
        [len(f) for r, d, f in os.walk(paths['no'])])
    conn = sqlite3.connect(SKIPPED_DB)
    total_done = conn.execute("SELECT COUNT(*) FROM progress").fetchone()[0]
    conn.close()
    return jsonify(
        {"inbox": inbox_c, "pending": pending_sync, "total": total_done, "folder": user_prefs.get(user, "WAITING")})


@app.route('/api/list_folders')
def list_folders():
    try:
        if not os.path.exists(DRIVE_SOURCE): return jsonify({"folders": []})
        folders = [d for d in os.listdir(DRIVE_SOURCE) if os.path.isdir(os.path.join(DRIVE_SOURCE, d))]
        return jsonify({"folders": sorted(folders)})
    except Exception as e:
        return jsonify({"folders": [], "error": str(e)})


@app.route('/api/set_folder', methods=['POST'])
def set_folder():
    data = request.json
    user_prefs[data.get('user')] = data.get('folder')
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
    parts = rel.split(os.sep)
    game_name, filename = parts[0] if len(parts) > 1 else "Uncategorized", parts[-1]
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
        conn.commit();
        conn.close()
        user_history[user].append({"rel": rel, "dest": dest, "id": clean_id, "game": game_name, "lang": lang})
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
        conn.commit();
        conn.close()
        return jsonify({"status": "success"})
    return jsonify({"status": "error"}), 404


@app.route('/api/sync_to_drive', methods=['POST'])
def sync_to_drive():
    user = request.json.get('user')
    paths = get_user_paths(user)
    with download_lock:
        print(f"\n[UPLOAD] Syncing {user.upper()} to Drive...", flush=True)
        upload_tasks = []
        mapping = [('YES', DRIVE_YES_DIR, paths['yes']), ('NO', DRIVE_NO_DIR, paths['no'])]
        for label, dr_root, loc_root in mapping:
            if not os.path.exists(loc_root): continue
            for root, _, files in os.walk(loc_root):
                for f in files:
                    l_p = os.path.join(root, f)
                    rel = os.path.relpath(l_p, loc_root)
                    upload_tasks.append((l_p, os.path.join(dr_root, rel), os.path.join(DRIVE_SOURCE, rel)))
        moved = 0
        if upload_tasks:
            futures = {upload_executor.submit(fast_upload_file, *t): t for t in upload_tasks}
            for i, f in enumerate(as_completed(futures)):
                if shutdown_event.is_set(): break
                if f.result(): moved += 1
                if (i + 1) % 25 == 0 or (i + 1) == len(upload_tasks): print(
                    f"   [UPLOAD] Progress: {i + 1}/{len(upload_tasks)}", flush=True)
        recursive_cleanup(os.path.join(BASE_LOCAL_PATH, "users", user))
        recursive_cleanup(DRIVE_SOURCE)
    print(f"[COMPLETE] Moved {moved} files.\n", flush=True)
    return jsonify({"status": "success", "moved": moved})


@app.route('/api/shutdown', methods=['POST'])
def api_shutdown():
    handle_exit(None, None)
    return jsonify({"status": "shutting down"})


# ==========================
# SYSTEM HANDLERS
# ==========================

def handle_exit(sig, frame):
    print("\n[SHUTDOWN] Nuclear exit initiated...", flush=True)
    shutdown_event.set()
    upload_executor.shutdown(wait=False, cancel_futures=True)
    download_executor.shutdown(wait=False, cancel_futures=True)
    os._exit(0)


if __name__ == '__main__':
    signal.signal(signal.SIGINT, handle_exit)
    init_system()

    # Start the background worker
    threading.Thread(target=auto_sync_worker, daemon=True).start()

    local_ip = get_local_ip()
    port = 5000

    print("-" * 45)
    print(f" SERVER ACTIVE")
    print(f" Local:   http://localhost:{port}")
    print(f" Network: http://{local_ip}:{port}")
    print(f" Console logs suppressed. Check browser for UI.")
    print("-" * 45, flush=True)

    # host='0.0.0.0' makes the server accessible across the network
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)