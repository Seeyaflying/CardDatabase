import os
import sqlite3
import shutil
import threading
import time
from datetime import datetime
from flask import Flask, render_template, send_from_directory, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ==========================
# PERMANENT CONFIGURATION
# ==========================
DRIVE_SOURCE = r"G:\My Drive\New Cards"
DRIVE_YES_DIR = r"G:\My Drive\Card Database"
DRIVE_NO_DIR = r"G:\My Drive\Skipped Cards"

LOCAL_REVIEW_SOURCE = r"C:\Users\seeya\OneDrive\Desktop\Cards\inbox"
LOCAL_YES = r"C:\Users\seeya\OneDrive\Desktop\Cards\yes"
LOCAL_NO = r"C:\Users\seeya\OneDrive\Desktop\Cards\no"
DB_FILE = "photo_history.db"

SYNC_BATCH_SIZE = 200
MIN_THRESHOLD = 50

history_stack = []


def init_system():
    for folder in [LOCAL_REVIEW_SOURCE, LOCAL_YES, LOCAL_NO]:
        os.makedirs(folder, exist_ok=True)
    os.makedirs(DRIVE_YES_DIR, exist_ok=True)
    os.makedirs(DRIVE_NO_DIR, exist_ok=True)

    conn = sqlite3.connect(DB_FILE)
    conn.execute('CREATE TABLE IF NOT EXISTS processed (path TEXT PRIMARY KEY, decision TEXT)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_path ON processed(path)')
    conn.commit()
    conn.close()


def is_processed(file_path):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.execute('SELECT 1 FROM processed WHERE path = ? LIMIT 1', (file_path,))
    res = cursor.fetchone()
    conn.close()
    return res is not None


# ==========================
# AUTO-SYNC ENGINE
# ==========================
def auto_sync_worker():
    while True:
        try:
            count = 0
            for r, d, f_list in os.walk(LOCAL_REVIEW_SOURCE):
                count += len([f for f in f_list if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))])

            if count < MIN_THRESHOLD:
                copied = 0
                for root, _, files in os.walk(DRIVE_SOURCE):
                    if copied >= SYNC_BATCH_SIZE: break
                    for f in files:
                        if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                            drive_path = os.path.join(root, f)
                            rel_path = os.path.relpath(drive_path, DRIVE_SOURCE)
                            local_path = os.path.join(LOCAL_REVIEW_SOURCE, rel_path)

                            if not os.path.exists(local_path) and not is_processed(drive_path):
                                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                                shutil.copy2(drive_path, local_path)
                                copied += 1
                                if copied >= SYNC_BATCH_SIZE: break
        except Exception as e:
            print(f"Sync Error: {e}")
        time.sleep(15)

    # ==========================


# ROUTES
# ==========================
@app.route('/')
def index():
    return render_template('index.html')


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
    hourly_folder = datetime.now().strftime("%Y-%m-%d_%Hh")

    src = os.path.join(LOCAL_REVIEW_SOURCE, rel_path)
    base_dest_dir = LOCAL_YES if decision == 'yes' else LOCAL_NO
    dest = os.path.join(base_dest_dir, hourly_folder, rel_path)

    if os.path.exists(src):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if os.path.exists(dest): os.remove(dest)
        shutil.move(src, dest)
        history_stack.append({"rel_path": rel_path, "actual_dest": dest})

        drive_orig_path = os.path.join(DRIVE_SOURCE, rel_path)
        conn = sqlite3.connect(DB_FILE)
        conn.execute('INSERT OR REPLACE INTO processed (path, decision) VALUES (?, ?)',
                     (drive_orig_path, decision))
        conn.commit()
        conn.close()
    return jsonify({"status": "success"})


@app.route('/api/sync_to_drive', methods=['POST'])
def sync_to_drive():
    counts = {"yes": 0, "no": 0, "deleted": 0}
    mapping = {'yes': (LOCAL_YES, DRIVE_YES_DIR), 'no': (LOCAL_NO, DRIVE_NO_DIR)}

    for cat, (local_root, drive_root) in mapping.items():
        if not os.path.exists(local_root): continue
        for hour_folder in os.listdir(local_root):
            hour_path = os.path.join(local_root, hour_folder)
            if not os.path.isdir(hour_path): continue

            for root, _, files in os.walk(hour_path):
                for f in files:
                    rel_to_hour = os.path.relpath(os.path.join(root, f), hour_path)
                    final_dest = os.path.join(drive_root, rel_to_hour)
                    os.makedirs(os.path.dirname(final_dest), exist_ok=True)

                    # Move to final destination
                    shutil.move(os.path.join(root, f), final_dest)

                    # Delete from Source
                    original_source = os.path.join(DRIVE_SOURCE, rel_to_hour)
                    if os.path.exists(original_source):
                        try:
                            os.remove(original_source)
                            counts["deleted"] += 1
                        except Exception as e:
                            print(f"Delete Error for {f}: {e}")

                    counts[cat] += 1
            shutil.rmtree(hour_path)

    return jsonify({
        "status": "success",
        "message": f"Sync Complete!\nMoved: {counts['yes']} to Database, {counts['no']} to Skipped.\nRemoved {counts['deleted']} originals from Source."
    })


@app.route('/api/undo', methods=['POST'])
def api_undo():
    if not history_stack: return jsonify({"status": "error"}), 400
    last = history_stack.pop()
    src, rel_path = last["actual_dest"], last["rel_path"]
    dest = os.path.join(LOCAL_REVIEW_SOURCE, rel_path)
    if os.path.exists(src):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.move(src, dest)
        conn = sqlite3.connect(DB_FILE)
        conn.execute('DELETE FROM processed WHERE path = ?', (os.path.join(DRIVE_SOURCE, rel_path),))
        conn.commit()
        conn.close()
        return jsonify({"url": f"/images/{rel_path.replace('\\', '/')}", "path": rel_path})
    return jsonify({"status": "error"}), 404


if __name__ == '__main__':
    init_system()
    threading.Thread(target=auto_sync_worker, daemon=True).start()
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)