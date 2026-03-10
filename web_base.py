import os
import sqlite3
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import unquote
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
SELECTED_FOLDER = None
IS_WAITING_FOR_INPUT = False
SYNC_BATCH_SIZE = 6000
MIN_THRESHOLD = 300
MAX_DOWNLOAD_THREADS = 10

download_lock = threading.Lock()
history_stack = []


# ==========================
# CORE LOGIC
# ==========================

def get_inbox_image_count():
    count = 0
    if not os.path.exists(LOCAL_REVIEW_SOURCE): return 0
    for root, _, files in os.walk(LOCAL_REVIEW_SOURCE):
        for f in files:
            if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                count += 1
    return count


def terminal_selection_logic():
    global SELECTED_FOLDER, IS_WAITING_FOR_INPUT
    IS_WAITING_FOR_INPUT = True
    print("\n" + "=" * 45 + "\n      CARD DATABASE MANAGER\n" + "=" * 45)
    print(" [1] PROCESS ALL FOLDERS\n [2] LIST SPECIFIC FOLDERS")
    try:
        mode = input("Select (1/2) or Enter for ALL: ").strip()
        if mode == "2":
            subfolders = [d for d in os.listdir(DRIVE_SOURCE) if os.path.isdir(os.path.join(DRIVE_SOURCE, d))]
            subfolders.sort(key=str.lower)
            for i, fld in enumerate(subfolders, 1): print(f" [{i:02d}] {fld}")
            choice = input("\nType Number or Name: ").strip()
            if choice.isdigit() and 0 < int(choice) <= len(subfolders):
                SELECTED_FOLDER = subfolders[int(choice) - 1]
            else:
                SELECTED_FOLDER = choice if choice else None
        else:
            SELECTED_FOLDER = None
        IS_WAITING_FOR_INPUT = False
    except:
        IS_WAITING_FOR_INPUT = False


def init_system():
    for folder in [LOCAL_REVIEW_SOURCE, LOCAL_YES, LOCAL_NO]: os.makedirs(folder, exist_ok=True)
    conn = sqlite3.connect(SKIPPED_DB)
    conn.execute('CREATE TABLE IF NOT EXISTS progress (img_path TEXT PRIMARY KEY, processed_at TEXT, status TEXT)')
    conn.commit()
    conn.close()


def is_processed(file_path):
    conn = sqlite3.connect(SKIPPED_DB)
    res = conn.execute('SELECT 1 FROM progress WHERE img_path = ?', (file_path,)).fetchone()
    conn.close()
    return res is not None


def auto_sync_worker():
    global IS_WAITING_FOR_INPUT, SELECTED_FOLDER
    while True:
        if not download_lock.locked() and not IS_WAITING_FOR_INPUT:
            try:
                if get_inbox_image_count() < MIN_THRESHOLD:
                    with download_lock:
                        to_copy = []
                        scan_root = os.path.join(DRIVE_SOURCE, SELECTED_FOLDER) if SELECTED_FOLDER else DRIVE_SOURCE
                        if os.path.exists(scan_root):
                            for root, _, files in os.walk(scan_root):
                                for f in files:
                                    if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                                        drive_p = os.path.join(root, f)
                                        if not is_processed(drive_p):
                                            rel_p = os.path.relpath(drive_p, DRIVE_SOURCE)
                                            loc_p = os.path.join(LOCAL_REVIEW_SOURCE, rel_p)
                                            if not os.path.exists(loc_p):
                                                to_copy.append((drive_p, loc_p))
                                                if len(to_copy) >= SYNC_BATCH_SIZE: break
                                if len(to_copy) >= SYNC_BATCH_SIZE: break
                        if to_copy:
                            with ThreadPoolExecutor(max_workers=MAX_DOWNLOAD_THREADS) as ex:
                                for dp, lp in to_copy:
                                    os.makedirs(os.path.dirname(lp), exist_ok=True)
                                    shutil.copy2(dp, lp)
            except Exception as e:
                print(f"Sync Worker Error: {e}")
        time.sleep(5)


# ==========================
# FLASK ROUTES
# ==========================

@app.route('/')
def index(): return render_template('index.html')


@app.route('/api/stats')
def api_stats():
    inbox_c = get_inbox_image_count()
    conn = sqlite3.connect(SKIPPED_DB)
    total = conn.execute("SELECT COUNT(*) FROM progress").fetchone()[0]
    conn.close()
    return jsonify(
        {"inbox": inbox_c, "total": total, "waiting": IS_WAITING_FOR_INPUT, "folder": SELECTED_FOLDER or "ALL"})


@app.route('/api/list_folders')
def list_folders():
    try:
        subfolders = [d for d in os.listdir(DRIVE_SOURCE) if os.path.isdir(os.path.join(DRIVE_SOURCE, d))]
        subfolders.sort(key=str.lower)
        return jsonify({"folders": subfolders})
    except:
        return jsonify({"folders": []})


@app.route('/api/set_folder', methods=['POST'])
def set_folder():
    global SELECTED_FOLDER
    SELECTED_FOLDER = request.json.get('folder')
    if SELECTED_FOLDER == "ALL": SELECTED_FOLDER = None
    print(f"\n[SET SWITCH] Now processing: {SELECTED_FOLDER or 'ALL'}")
    return jsonify({"status": "success"})


@app.route('/images/<path:filename>')
def serve_image(filename):
    full_path = os.path.join(LOCAL_REVIEW_SOURCE, unquote(filename))
    if os.path.exists(full_path):
        return send_from_directory(os.path.dirname(full_path), os.path.basename(full_path))
    return "Not Found", 404


@app.route('/api/next')
def api_next():
    for root, _, files in os.walk(LOCAL_REVIEW_SOURCE):
        for f in files:
            if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                full_local = os.path.join(root, f)
                rel = os.path.relpath(full_local, LOCAL_REVIEW_SOURCE)
                return jsonify({
                    "url": f"/images/{rel.replace(os.sep, '/')}",
                    "path": rel,
                    "display_name": rel.replace(os.sep, ' / ')
                })
    return jsonify({"url": None})


@app.route('/api/decision', methods=['POST'])
def api_decision():
    data = request.json
    rel, dec = data['path'], data['decision']
    src = os.path.join(LOCAL_REVIEW_SOURCE, rel)
    dest = os.path.join(LOCAL_YES if dec == 'yes' else LOCAL_NO, rel)
    drive_orig = os.path.join(DRIVE_SOURCE, rel)
    if os.path.exists(src):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.move(src, dest)
        conn = sqlite3.connect(SKIPPED_DB)
        conn.execute('INSERT OR REPLACE INTO progress VALUES (?, ?, ?)',
                     (drive_orig, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), dec))
        conn.commit()
        conn.close()
        history_stack.append({"rel": rel, "dest": dest, "orig": drive_orig})
    return jsonify({"status": "success"})


@app.route('/api/undo', methods=['POST'])
def api_undo():
    if not history_stack: return jsonify({"status": "error"}), 400
    last = history_stack.pop()
    rel, src, drive_orig = last["rel"], last["dest"], last["orig"]
    dest = os.path.join(LOCAL_REVIEW_SOURCE, rel)
    if os.path.exists(src):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.move(src, dest)
        conn = sqlite3.connect(SKIPPED_DB)
        conn.execute('DELETE FROM progress WHERE img_path = ?', (drive_orig,))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    return jsonify({"status": "error"}), 404


@app.route('/api/sync_to_drive', methods=['POST'])
def sync_to_drive():
    with download_lock:
        print("\n" + "-" * 35)
        print(">>> STARTING DRIVE SYNC & CLEANUP")
        moved_count = 0
        deleted_folders_count = 0

        mapping = [('yes', DRIVE_YES_DIR, LOCAL_YES), ('no', DRIVE_NO_DIR, LOCAL_NO)]

        for dec, dr_root, loc_root in mapping:
            if not os.path.exists(loc_root): continue
            for root, _, files in os.walk(loc_root):
                for f in files:
                    l_path = os.path.join(root, f)
                    rel = os.path.relpath(l_path, loc_root)
                    d_path = os.path.join(dr_root, rel)
                    orig_drive = os.path.join(DRIVE_SOURCE, rel)

                    # 1. Move to Final Drive Destination
                    os.makedirs(os.path.dirname(d_path), exist_ok=True)
                    shutil.move(l_path, d_path)

                    # 2. Delete original source from New Cards
                    if os.path.exists(orig_drive):
                        try:
                            os.remove(orig_drive)
                        except Exception as e:
                            print(f"Error removing original: {e}")
                    moved_count += 1

        # 3. Cleanup empty folders in all relevant roots
        target_roots = [LOCAL_YES, LOCAL_NO, LOCAL_REVIEW_SOURCE, DRIVE_SOURCE]
        for clean_root in target_roots:
            if not os.path.exists(clean_root): continue
            # Walk bottom-up so we can delete a folder after its subfolders are gone
            for root, dirs, _ in os.walk(clean_root, topdown=False):
                for d in dirs:
                    d_full = os.path.join(root, d)
                    try:
                        if not os.listdir(d_full):
                            os.rmdir(d_full)
                            if clean_root == DRIVE_SOURCE:
                                deleted_folders_count += 1
                    except:
                        pass

        print(f">>> SYNC COMPLETE")
        print(f" - Files moved/cleared: {moved_count}")
        print(f" - Empty folders removed from Source: {deleted_folders_count}")
        print("-" * 35 + "\n")

    return jsonify({
        "status": "success",
        "moved": moved_count,
        "folders_removed": deleted_folders_count
    })


if __name__ == '__main__':
    init_system()
    terminal_selection_logic()
    threading.Thread(target=auto_sync_worker, daemon=True).start()
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)