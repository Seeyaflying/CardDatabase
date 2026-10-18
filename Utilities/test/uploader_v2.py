import os
import shutil
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
import requests
from tqdm import tqdm

import config_v2
import db_v2

load_dotenv()  # loads your .env file

# ============ CONFIG FROM .env ============
IMMICH_URL          = os.getenv("IMMICH_URL", "http://100.80.179.119:8081")
IMMICH_API_KEY      = os.getenv("IMMICH_API_KEY", "")
IMMICH_MAX_WORKERS  = int(os.getenv("IMMICH_MAX_WORKERS", "12"))
CARD_UPLOAD         = Path(os.getenv("CARD_UPLOAD", r"T:\Full Card Database\Card Upload"))
FOLDER_DATABASE     = Path(os.getenv("FOLDER_DATABASE", r"T:\Full Card Database\Folder Database"))
IMAGE_EXTS          = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".tif", ".tiff"}
SKIP_FOLDERS        = {"backed up"}

# card_tracker is the single source of truth. immich_upload is retired.
CARD_TRACKER_COLL   = config_v2.CARD_TRACKER_COLL

# Test mode: set to a game name to process only that folder, empty = run everything
TEST_GAME = os.getenv("TEST_GAME", "")

# Debug: print extra detail (URLs, status codes, bodies, timing)
DEBUG = os.getenv("DEBUG", "true").lower() == "true"
# ============================================

headers = {"x-api-key": IMMICH_API_KEY}


def dbg(msg):
    if DEBUG:
        print(f"[DEBUG] {msg}")


def req(method, url, **kwargs):
    """Request wrapper that logs detail when DEBUG is on."""
    import time
    start = time.time()
    dbg(f"{method} {url}")
    r = requests.request(method, url, headers=headers, **kwargs)
    elapsed = time.time() - start
    dbg(f"  -> {r.status_code} in {elapsed:.2f}s")
    if DEBUG and r.text:
        dbg(f"  body: {r.text[:300]}")
    return r


def save_to_mongo(path, asset_id, album_name, set_name, status, is_duplicate):
    """Update the matching card_tracker record after upload.

    The web app created the record when the card was approved (status=yes).
    The uploader finds it by (image_name, game_name) and marks it uploaded.
    """
    image_id = path.stem.replace("_200w", "")
    try:
        if asset_id:
            db_v2.tracker_mark_uploaded(
                image_id, album_name, asset_id, set_name, is_duplicate)
            print(f"[MONGO] card_tracker updated: {path.name} -> {asset_id}")
        else:
            # Upload failed — keep the record as reviewed so it's not lost
            print(f"[MONGO] Upload failed for {path.name}, "
                  f"card_tracker left as reviewed")
    except Exception as e:
        print(f"[MONGO-ERROR] Could not update {path.name}: {e}")


def load_albums():
    print("[LOAD] Fetching albums...")
    r = req("GET", f"{IMMICH_URL}/api/albums")
    r.raise_for_status()
    return {a["albumName"]: a["id"] for a in r.json()}


def create_album(name):
    print(f"[ALBUM] Creating album: {name}")
    r = req("POST", f"{IMMICH_URL}/api/albums", json={"albumName": name})
    r.raise_for_status()
    return r.json()["id"]


def get_album(name, albums):
    if name in albums:
        return albums[name]
    albums[name] = create_album(name)
    return albums[name]


def load_tags():
    print("[LOAD] Fetching tags...")
    r = req("GET", f"{IMMICH_URL}/api/tags")
    r.raise_for_status()
    return {t["name"]: t["id"] for t in r.json()}


def create_tag(name):
    print(f"[TAG] Creating tag: {name}")
    r = req("POST", f"{IMMICH_URL}/api/tags", json={"name": name})
    r.raise_for_status()
    return r.json()["id"]


def get_or_create_tag(name, tags):
    if name in tags:
        return tags[name]
    tags[name] = create_tag(name)
    return tags[name]


def upload_image(path):
    """Upload an image. Returns (asset_id, is_duplicate)."""
    print(f"[UPLOAD] Uploading {path.name}...")
    with open(path, "rb") as image:
        r = req("POST", f"{IMMICH_URL}/api/assets",
                files={"assetData": image},
                data={"deviceAssetId": path.name, "deviceId": "TCG Import",
                      "fileCreatedAt": "2025-01-01T00:00:00.000Z",
                      "fileModifiedAt": "2025-01-01T00:00:00.000Z"})
    r.raise_for_status()
    body = r.json()
    if isinstance(body, list):
        item = body[0]
        is_dup = (not item.get("success", True)) or item.get("error") == "duplicate"
        asset_id = item.get("id")
        print(f"[UPLOAD] {path.name} -> {asset_id} "
              f"({'DUPLICATE' if is_dup else 'NEW'})")
        return asset_id, is_dup
    is_dup = body.get("status") == "duplicate"
    asset_id = body.get("id")
    print(f"[UPLOAD] {path.name} -> {asset_id} "
          f"({'DUPLICATE' if is_dup else 'NEW'})")
    return asset_id, is_dup


def add_to_album(album_id, asset_id):
    print(f"[ALBUM] Adding {asset_id} to album {album_id}")
    req("PUT", f"{IMMICH_URL}/api/albums/{album_id}/assets",
        json={"ids": [asset_id]})


def add_tag_to_asset(asset_id, tag_id):
    print(f"[TAG] Tagging {asset_id} with tag {tag_id}")
    req("PUT", f"{IMMICH_URL}/api/tags/{tag_id}/assets",
        json={"ids": [asset_id]})


def count_album_assets(album_id):
    """Count assets in an album via the detail endpoint (has assetCount)."""
    r = req("GET", f"{IMMICH_URL}/api/albums/{album_id}")
    r.raise_for_status()
    return r.json().get("assetCount", 0)


def process_image(path, album_id, tag_id, album_name, set_name):
    try:
        asset_id, is_dup = upload_image(path)
        if is_dup:
            print(f"[DONE] {path.name}: ALREADY EXISTS (no album/tag calls)")
            save_to_mongo(path, asset_id, album_name, set_name, "Duplicate", True)
            return "Duplicate"
        add_to_album(album_id, asset_id)
        add_tag_to_asset(asset_id, tag_id)
        print(f"[DONE] {path.name}: UPLOADED + TAGGED")
        save_to_mongo(path, asset_id, album_name, set_name, "Uploaded", False)
        return "Uploaded"
    except Exception as e:
        print(f"[ERROR] {path}: {e}")
        save_to_mongo(path, None, album_name, set_name, "Failed", False)
        return "Failed"


def move_set_to_folder_database(set_folder, game_folder):
    """Move a completed set folder into Folder Database, preserving structure."""
    dest = FOLDER_DATABASE / game_folder.name / set_folder.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        print(f"[MOVE] Destination already exists: {dest} — skipping move")
        return False
    print(f"[MOVE] Moving {set_folder} -> {dest}")
    shutil.move(str(set_folder), str(dest))
    print(f"[MOVE] Done: {dest}")
    return True


def main():
    print("Loading Immich albums and tags...")
    albums = load_albums()
    tags = load_tags()
    root = CARD_UPLOAD
    if not root.exists():
        print(f"Card Upload folder not found: {root}")
        return

    for folder in root.iterdir():
        if not folder.is_dir() or folder.name.lower() in SKIP_FOLDERS:
            continue
        if TEST_GAME and folder.name != TEST_GAME:
            print(f"[SKIP] {folder.name} (test mode only processes '{TEST_GAME}')")
            continue
        album_name = folder.name
        album_id = get_album(album_name, albums)

        before = count_album_assets(album_id)
        print(f"\n{'='*28}\n{album_name}\n{'='*28}")
        print(f"[COUNT] Assets in album BEFORE: {before}")

        # Group images by set (subfolder)
        sets = {}
        for img in folder.rglob("*"):
            if img.suffix.lower() in IMAGE_EXTS:
                set_name = img.parent.name
                sets.setdefault(set_name, []).append(img)
                print(f"[COLLECT] {img} (tag: {set_name})")

        for set_name, imgs in sets.items():
            print(f"\n--- SET: {set_name} ({len(imgs)} images) ---")
            tag_id = get_or_create_tag(set_name, tags)
            with ThreadPoolExecutor(max_workers=IMMICH_MAX_WORKERS) as ex:
                jobs = [ex.submit(process_image, img, album_id, tag_id,
                                  album_name, set_name)
                        for img in imgs]
                for job in tqdm(as_completed(jobs), total=len(jobs)):
                    job.result()
            # Move this set folder once its images are done
            set_folder = imgs[0].parent
            move_set_to_folder_database(set_folder, folder)

        after = count_album_assets(album_id)
        print(f"\n[COUNT] Assets in album AFTER:  {after}")
        print(f"[COUNT] Net change: {after - before}")

        # Clean up the now-empty game folder if all sets were moved
        if folder.exists() and not any(folder.iterdir()):
            print(f"[MOVE] Game folder now empty, removing: {folder}")
            folder.rmdir()
    print("\nIMPORT COMPLETE")


if __name__ == "__main__":
    main()
