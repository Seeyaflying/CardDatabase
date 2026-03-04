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
SYNC_BATCH_SIZE = 1800
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
    conn.commit();
    conn.close()


def is_processed(file_path):
    conn = sqlite3.connect(SKIPPED_DB)
    res = conn.execute('SELECT 1 FROM progress WHERE img_path = ?', (file_path,)).fetchone()
    conn.close();
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
                                ex.map(lambda p: (os.makedirs(os.path.dirname(p[1]), exist_ok=True),
                                                  shutil.copy2(p[0], p[1])), to_copy)
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
    conn = sqlite3.connect(SKIPPED_DB);
    total = conn.execute("SELECT COUNT(*) FROM progress").fetchone()[0];
    conn.close()
    return jsonify(
        {"inbox": inbox_c, "total": total, "waiting": IS_WAITING_FOR_INPUT, "folder": SELECTED_FOLDER or "ALL"})


@app.route('/images/<path:filename>')
def serve_image(filename):
    full_path = os.path.join(LOCAL_REVIEW_SOURCE, unquote(filename))
    if os.path.exists(full_path): return send_from_directory(os.path.dirname(full_path), os.path.basename(full_path))
    return "Not Found", 404


@app.route('/api/next')
def api_next():
    for root, _, files in os.walk(LOCAL_REVIEW_SOURCE):
        for f in files:
            if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                full_local = os.path.join(root, f)
                rel = os.path.relpath(full_local, LOCAL_REVIEW_SOURCE)
                # We return the path for the UI display and the URL for the image source
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
    full_drive_source = os.path.join(DRIVE_SOURCE, rel)
    src = os.path.join(LOCAL_REVIEW_SOURCE, rel)
    # NO TIMESTAMP HERE - goes straight to Category/Folder/File
    dest = os.path.join(LOCAL_YES if dec == 'yes' else LOCAL_NO, rel)

    if os.path.exists(src):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.move(src, dest)
        history_stack.append({"rel_path": rel, "local_dest": dest, "drive_source": full_drive_source})
        conn = sqlite3.connect(SKIPPED_DB)
        conn.execute('INSERT OR REPLACE INTO progress VALUES (?, ?, ?)',
                     (full_drive_source, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), dec))
        conn.commit();
        conn.close()
    return jsonify({"status": "success"})


@app.route('/api/undo', methods=['POST'])
def api_undo():
    if not history_stack: return jsonify({"status": "error"}), 400
    last = history_stack.pop()
    src, rel, drive = last["local_dest"], last["rel_path"], last["drive_source"]
    dest = os.path.join(LOCAL_REVIEW_SOURCE, rel)
    if os.path.exists(src):
        os.makedirs(os.path.dirname(dest), exist_ok=True);
        shutil.move(src, dest)
        conn = sqlite3.connect(SKIPPED_DB);
        conn.execute('DELETE FROM progress WHERE img_path = ?', (drive,));
        conn.commit();
        conn.close()
        return jsonify({"url": f"/images/{rel.replace(os.sep, '/')}", "path": rel})
    return jsonify({"status": "error"}), 404


@app.route('/api/sync_to_drive', methods=['POST'])
def sync_to_drive():
    with download_lock:
        print("\n" + "-" * 35 + "\n>>> SYNCING TO GOOGLE DRIVE <<<")
        files_moved = 0
        mapping = {'yes': (LOCAL_YES, DRIVE_YES_DIR), 'no': (LOCAL_NO, DRIVE_NO_DIR)}

        for cat, (loc_root, dr_root) in mapping.items():
            for root, _, files in os.walk(loc_root):
                for f in files:
                    local_f = os.path.join(root, f)
                    rel = os.path.relpath(local_f, loc_root)
                    final_drive_path = os.path.join(dr_root, rel)
                    original_drive_source = os.path.join(DRIVE_SOURCE, rel)

                    # 1. Move to final destination on Drive
                    os.makedirs(os.path.dirname(final_drive_path), exist_ok=True)
                    shutil.move(local_f, final_drive_path)

                    # 2. Delete from original "New Cards" source
                    if os.path.exists(original_drive_source):
                        try:
                            os.remove(original_drive_source)
                        except Exception as e:
                            print(f"Error deleting original: {e}")

                    files_moved += 1

        # Cleanup empty folders in New Cards
        for root, dirs, _ in os.walk(DRIVE_SOURCE, topdown=False):
            for name in dirs:
                try:
                    os.rmdir(os.path.join(root, name))
                except:
                    pass

        print(f" - Completed: {files_moved} cards moved and cleared.\n>>> SYNC DONE <<<\n" + "-" * 35)
    return jsonify({"status": "success"})


if __name__ == '__main__':
    init_system()
    terminal_selection_logic()
    threading.Thread(target=auto_sync_worker, daemon=True).start()
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)