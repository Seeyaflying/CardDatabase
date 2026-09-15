import hashlib
import sqlite3
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from tqdm import tqdm
import config

headers = {"x-api-key": config.IMMICH_API_KEY}
SUPPORTED = config.IMAGE_EXTS
SKIP_FOLDERS = {"backed up"}

def setup_database():
    conn = sqlite3.connect(config.IMMICH_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS uploads (
        hash TEXT PRIMARY KEY, filepath TEXT, asset_id TEXT, album TEXT)""")
    conn.commit()
    conn.close()

def already_uploaded(file_hash):
    conn = sqlite3.connect(config.IMMICH_DB)
    cur = conn.cursor()
    cur.execute("SELECT hash FROM uploads WHERE hash=?", (file_hash,))
    result = cur.fetchone()
    conn.close()
    return result is not None

def save_upload(file_hash, filepath, asset_id, album):
    conn = sqlite3.connect(config.IMMICH_DB)
    conn.execute("INSERT OR IGNORE INTO uploads VALUES (?,?,?,?)",
                 (file_hash, filepath, asset_id, album))
    conn.commit()
    conn.close()

def calculate_hash(path):
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            sha.update(chunk)
    return sha.hexdigest()

def load_albums():
    r = requests.get(f"{config.IMMICH_URL}/api/albums", headers=headers)
    r.raise_for_status()
    return {a["albumName"]: a["id"] for a in r.json()}

def create_album(name):
    r = requests.post(f"{config.IMMICH_URL}/api/albums", headers=headers,
                      json={"albumName": name})
    r.raise_for_status()
    return r.json()["id"]

def get_album(name, albums):
    if name in albums:
        return albums[name]
    print(f"Creating album: {name}")
    albums[name] = create_album(name)
    return albums[name]

def upload_image(path):
    with open(path, "rb") as image:
        r = requests.post(f"{config.IMMICH_URL}/api/assets", headers=headers,
                          files={"assetData": image},
                          data={"deviceAssetId": path.name, "deviceId": "TCG Import",
                                "fileCreatedAt": "2025-01-01T00:00:00.000Z",
                                "fileModifiedAt": "2025-01-01T00:00:00.000Z"})
    r.raise_for_status()
    return r.json()["id"]

def add_to_album(album_id, asset_id):
    requests.put(f"{config.IMMICH_URL}/api/albums/{album_id}/assets",
                 headers=headers, json={"ids": [asset_id]})

def process_image(path, album_name, album_id):
    file_hash = calculate_hash(path)
    if already_uploaded(file_hash):
        return "Skipped"
    try:
        asset_id = upload_image(path)
        add_to_album(album_id, asset_id)
        save_upload(file_hash, str(path), asset_id, album_name)
        return "Uploaded"
    except Exception as e:
        print(f"\nERROR {path}: {e}")
        return "Failed"

def main():
    setup_database()
    print("Loading Immich albums...")
    albums = load_albums()
    root = config.CARD_UPLOAD
    if not root.exists():
        print("Card Upload folder not found")
        return
    for folder in root.iterdir():
        if not folder.is_dir() or folder.name.lower() in SKIP_FOLDERS:
            continue
        album_name = folder.name
        print(f"\n{'='*28}\n{album_name}\n{'='*28}")
        album_id = get_album(album_name, albums)
        images = [f for f in folder.iterdir() if f.suffix.lower() in SUPPORTED]
        print(f"{len(images)} images found")
        with ThreadPoolExecutor(max_workers=config.IMMICH_MAX_WORKERS) as ex:
            jobs = [ex.submit(process_image, img, album_name, album_id)
                    for img in images]
            for job in tqdm(as_completed(jobs), total=len(jobs)):
                job.result()
    print("\nIMPORT COMPLETE")

if __name__ == "__main__":
    main()
