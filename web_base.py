import os
import sqlite3
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from flask import Flask, render_template, send_from_directory, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ==========================
# CONFIGURATION
# ==========================
DRIVE_SOURCE = r"G:\My Drive\New Cards"
DRIVE_YES_DIR = r"G:\My Drive\Card Database"
DRIVE_NO_DIR = r"G:\My Drive\Skipped Cards"

LOCAL_REVIEW_SOURCE = r"C:\Users\seeya\OneDrive\Desktop\Cards\inbox"
LOCAL_YES = r"C:\Users\seeya\OneDrive\Desktop\Cards\yes"
LOCAL_NO = r"C:\Users\seeya\OneDrive\Desktop\Cards\no"

SKIPPED_DB = "skipped_images.sqlite"

# Background Sync Limits
SYNC_BATCH_SIZE = 100
MIN_THRESHOLD = 80
MAX_DOWNLOAD_THREADS = 15

download_lock = threading.Lock()
history_stack = []


def init_system():
    for folder in [LOCAL_REVIEW_SOURCE, LOCAL_YES, LOCAL_NO]:
        os.makedirs(folder, exist_ok=True)

    conn = sqlite3.connect(SKIPPED_DB)
    conn.execute('''
                 CREATE TABLE IF NOT EXISTS progress
                 (
                     img_path
                     TEXT
                     PRIMARY
                     KEY,
                     processed_at
                     TEXT,
                     status
                     TEXT
                 )
                 ''')
    conn.commit()
    conn.close()


def is_processed(file_path):
    conn = sqlite3.connect(SKIPPED_DB)
    cursor = conn.execute('SELECT 1 FROM progress WHERE img_path = ? LIMIT 1', (file_path,))
    res = cursor.fetchone()
    conn.close()
    return res is not None


def fast_copy(src, dst):
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        return True
    except:
        return False


def auto_sync_worker():
    while True:
        if not download_lock.locked():
            try:
                count = 0
                for root, _, files in os.walk(LOCAL_REVIEW_SOURCE):
                    count += len([f for f in files if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))])

                if count < MIN_THRESHOLD:
                    with download_lock:
                        to_copy = []
                        for root, _, files in os.walk(DRIVE_SOURCE):
                            if len(to_copy) >= SYNC_BATCH_SIZE: break
                            for f in files:
                                if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                                    drive_path = os.path.join(root, f)
                                    rel_path = os.path.relpath(drive_path, DRIVE_SOURCE)
                                    local_path = os.path.join(LOCAL_REVIEW_SOURCE, rel_path)

                                    if not os.path.exists(local_path) and not is_processed(drive_path):
                                        to_copy.append((drive_path, local_path))
                                        if len(to_copy) >= SYNC_BATCH_SIZE: break

                        if to_copy:
                            with ThreadPoolExecutor(max_workers=MAX_DOWNLOAD_THREADS) as executor:
                                executor.map(lambda p: fast_copy(*p), to_copy)
            except Exception as e:
                print(f"Worker Error: {e}")
        time.sleep(10)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/stats')
def api_stats():
    inbox_count = 0
    for root, _, files in os.walk(LOCAL_REVIEW_SOURCE):
        inbox_count += len([f for f in files if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))])

    conn = sqlite3.connect(SKIPPED_DB)
    res = conn.execute("SELECT COUNT(*) FROM progress").fetchone()
    conn.close()

    return jsonify({
        "inbox": inbox_count,
        "total": res[0]
    })


@app.route('/images/<path:filename>')
def serve_image(filename):
    return send_from_directory(LOCAL_REVIEW_SOURCE, filename)


@app.route('/api/next')
def api_next():
    for root, _, files in os.walk(LOCAL_REVIEW_SOURCE):
        for f in files:
            if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                rel_path = os.path.relpath(os.path.join(root, f), LOCAL_REVIEW_SOURCE)
                return jsonify({"url": f"/images/{rel_path.replace('\\', '/')}", "path": rel_path})
    return jsonify({"url": None, "path": None})


@app.route('/api/decision', methods=['POST'])
def api_decision():
    data = request.json
    rel_path, decision = data['path'], data['decision']
    full_drive_path = os.path.join(DRIVE_SOURCE, rel_path)
    src = os.path.join(LOCAL_REVIEW_SOURCE, rel_path)

    hourly_folder = datetime.now().strftime("%Y-%m-%d_%Hh")
    base_dest_dir = LOCAL_YES if decision == 'yes' else LOCAL_NO
    dest = os.path.join(base_dest_dir, hourly_folder, rel_path)

    if os.path.exists(src):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.move(src, dest)
        history_stack.append({"rel_path": rel_path, "actual_dest": dest, "drive_path": full_drive_path})

        now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = sqlite3.connect(SKIPPED_DB)
        conn.execute('''
            INSERT OR REPLACE INTO progress (img_path, processed_at, status) 
            VALUES (?, ?, ?)
        ''', (full_drive_path, now_ts, decision))
        conn.commit()
        conn.close()
    return jsonify({"status": "success"})


@app.route('/api/undo', methods=['POST'])
def api_undo():
    if not history_stack: return jsonify({"status": "error"}), 400
    last = history_stack.pop()
    src, rel_path, drive_path = last["actual_dest"], last["rel_path"], last["drive_path"]
    dest = os.path.join(LOCAL_REVIEW_SOURCE, rel_path)
    if os.path.exists(src):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.move(src, dest)
        conn = sqlite3.connect(SKIPPED_DB)
        conn.execute('DELETE FROM progress WHERE img_path = ?', (drive_path,))
        conn.commit()
        conn.close()
        return jsonify({"url": f"/images/{rel_path.replace('\\', '/')}", "path": rel_path})
    return jsonify({"status": "error"}), 404


@app.route('/api/sync_to_drive', methods=['POST'])
def sync_to_drive():
    counts = {"yes": 0, "no": 0, "deleted": 0}
    mapping = {'yes': (LOCAL_YES, DRIVE_YES_DIR), 'no': (LOCAL_NO, DRIVE_NO_DIR)}
    for cat, (local_root, drive_root) in mapping.items():
        if not os.path.exists(local_root): continue
        for hour_folder in os.listdir(local_root):
            hour_path = os.path.join(local_root, hour_folder)
            for root, _, files in os.walk(hour_path):
                for f in files:
                    local_file = os.path.join(root, f)
                    rel_to_hour = os.path.relpath(local_file, hour_path)
                    final_dest = os.path.join(drive_root, rel_to_hour)
                    os.makedirs(os.path.dirname(final_dest), exist_ok=True)
                    try:
                        shutil.move(local_file, final_dest)
                        counts[cat] += 1
                        orig = os.path.join(DRIVE_SOURCE, rel_to_hour)
                        if os.path.exists(orig):
                            os.remove(orig);
                            counts["deleted"] += 1
                    except:
                        pass
            try:
                shutil.rmtree(hour_path)
            except:
                pass
    return jsonify({"status": "success",
                    "message": f"Sync Complete!\n✅ {counts['yes']} Yes\n❌ {counts['no']} No\n🧹 {counts['deleted']} Deleted"})


if __name__ == '__main__':
    init_system()
    threading.Thread(target=auto_sync_worker, daemon=True).start()
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)