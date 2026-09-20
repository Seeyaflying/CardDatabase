import sys
import os
import shutil
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# config.py and db.py live in the utilities folder
sys.path.insert(0, r"C:\Users\seeya\OneDrive\Desktop\CardDatabase\utilities")

import config
import db

IS_WINDOWS = os.name == 'nt'

if IS_WINDOWS:
    DRIVE_SOURCE = r"T:\Full Card Database\New Cards"
    DRIVE_YES_DIR = r"T:\Full Card Database\Card Upload"
    BASE_LOCAL_PATH = r"C:\Users\seeya\OneDrive\Desktop\Cards"
else:
    DRIVE_SOURCE = os.path.expanduser("~/Desktop/GDrive/New Cards")
    DRIVE_YES_DIR = os.path.expanduser("~/Desktop/GDrive/Card Database")
    BASE_LOCAL_PATH = os.path.expanduser("~/Desktop/Cards")

MTG_FOLDER = "Magic the Gathering"
MAX_UPLOAD_THREADS = 10


def progress_coll():
    return db.get_db()[config.PROGRESS_COLLECTION]


def main():
    print("=" * 60)
    print("MTG BYPASS START")
    print("=" * 60)

    # ---- STEP 1: LOCATE THE SOURCE FOLDER ----
    mtg_root = os.path.join(DRIVE_SOURCE, MTG_FOLDER)
    print(f"[CHECK] Looking for source folder: {mtg_root}")
    if not os.path.isdir(mtg_root):
        print(f"[ERROR] Folder not found: {mtg_root}")
        print("[ABORT] Nothing to do. Exiting.")
        return
    print(f"[OK] Source folder exists: {mtg_root}")

    # ---- STEP 2: SCAN EVERY FILE ----
    print(f"[SCAN] Walking {mtg_root} to find image files...")
    files = []
    for root, dirs, fnames in os.walk(mtg_root):
        for f in fnames:
            if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                full = os.path.join(root, f)
                files.append(full)
                print(f"[SCAN] Found: {os.path.relpath(full, DRIVE_SOURCE)}")
    print(f"[SCAN] Total image files found: {len(files)}")
    if not files:
        print("[ABORT] No image files found. Exiting.")
        return

    # ---- STEP 3: MARK EACH FILE AS ACCURATE IN THE DATABASE ----
    print(f"[DB] Marking {len(files)} files as 'accurate' in the database...")
    docs = []
    for fp in files:
        image_id = os.path.splitext(os.path.basename(fp))[0].replace("_200w", "")
        rel = os.path.relpath(fp, DRIVE_SOURCE)
        print(f"[DB] Mark accurate: {image_id} ({rel})")
        docs.append({
            "image_name": image_id,
            "game_name": MTG_FOLDER,
            "language": "english",
            "status": "accurate",
            "processed_at": datetime.now().strftime("%Y-%m-%d %H:%M")
        })
    if docs:
        progress_coll().insert_many(docs, ordered=False)
        print(f"[DB] Wrote {len(docs)} accurate records to database.")

    # ---- STEP 4: MOVE EACH FILE TO THE UPLOAD (YES) FOLDER ----
    print(f"[MOVE] Moving {len(files)} files to {DRIVE_YES_DIR}...")
    moved = 0
    for fp in files:
        rel = os.path.relpath(fp, DRIVE_SOURCE)
        dest = os.path.join(DRIVE_YES_DIR, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        print(f"[MOVE] {rel}  ->  {os.path.relpath(dest, DRIVE_YES_DIR)}")
        shutil.move(fp, dest)
        moved += 1
    print(f"[MOVE] Moved {moved} files total.")

    # ---- STEP 5: CLEAN UP EMPTY DIRECTORIES IN THE SOURCE ----
    print("[CLEAN] Removing empty folders left in source...")
    for root, dirs, _ in os.walk(mtg_root, topdown=False):
        for d in dirs:
            p = os.path.join(root, d)
            try:
                if not os.listdir(p):
                    os.rmdir(p)
                    print(f"[CLEAN] Removed empty dir: {os.path.relpath(p, DRIVE_SOURCE)}")
            except OSError as e:
                print(f"[CLEAN] Could not remove {p}: {e}")
    try:
        if not os.listdir(mtg_root):
            os.rmdir(mtg_root)
            print(f"[CLEAN] Removed empty root: {MTG_FOLDER}")
    except OSError as e:
        print(f"[CLEAN] Could not remove root {mtg_root}: {e}")

    # ---- STEP 6: UPLOAD (MOVE) EACH FILE TO THE DRIVE DESTINATION ----
    upload_root = os.path.join(DRIVE_YES_DIR, MTG_FOLDER)
    print(f"[UPLOAD] Scanning upload folder: {upload_root}")
    uploads = []
    if os.path.isdir(upload_root):
        for root, _, fnames in os.walk(upload_root):
            for f in fnames:
                uploads.append(os.path.join(root, f))
    print(f"[UPLOAD] Found {len(uploads)} files ready to upload.")

    print(f"[UPLOAD] Moving {len(uploads)} files to final drive location...")
    with ThreadPoolExecutor(max_workers=MAX_UPLOAD_THREADS) as ex:
        futures = []
        for fp in uploads:
            rel = os.path.relpath(fp, DRIVE_YES_DIR)
            dest = os.path.join(DRIVE_YES_DIR, rel)
            print(f"[UPLOAD] {rel}  ->  {dest}")
            futures.append(ex.submit(shutil.move, fp, dest))
        for fut in futures:
            fut.result()

    print(f"[UPLOAD] Uploaded {len(uploads)} files to drive.")

    # ---- DONE ----
    print("=" * 60)
    print("MTG BYPASS COMPLETE")
    print("=" * 60)


if __name__ == '__main__':
    main()

