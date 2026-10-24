import hashlib
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from tqdm import tqdm
import pymongo
import config

headers = {"x-api-key": config.IMMICH_API_KEY}
SUPPORTED = config.IMAGE_EXTS
SKIP_FOLDERS = {"backed up"}

MONGO_COLL = "immich_upload"


def get_mongo_collection():
    client = pymongo.MongoClient(config.MONGO_URI)
    return client[config.DB_NAME][MONGO_COLL]


def save_to_mongo(path, asset_id, album, status, is_duplicate):
    """Upsert one record per uploaded card into immich_upload."""
    doc = {
        "asset_id": asset_id,
        "name": path.stem,
        "filename": path.name,
        "set": None,                    # single-file mode has no set subfolder
        "game": album,
        "uploaded": datetime.now().isoformat(),
        "status": status,               # Uploaded / Duplicate / Failed
        "is_duplicate": is_duplicate,
    }
    try:
        coll = get_mongo_collection()
        coll.replace_one({"asset_id": asset_id}, doc, upsert=True)
        print(f"[MONGO] Recorded {path.name} -> {asset_id}")
    except Exception as e:
        print(f"[MONGO-ERROR] Could not write {path.name}: {e}")


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
    body = r.json()
    if isinstance(body, list):
        item = body[0]
        is_dup = (not item.get("success", True)) or item.get("error") == "duplicate"
        return item.get("id"), is_dup
    is_dup = body.get("status") == "duplicate"
    return body.get("id"), is_dup


def add_to_album(album_id, asset_id):
    requests.put(f"{config.IMMICH_URL}/api/albums/{album_id}/assets",
                 headers=headers, json={"ids": [asset_id]})


def process_image(path, album_name, album_id):
    try:
        asset_id, is_dup = upload_image(path)
        if is_dup:
            print(f"{path.name}: ALREADY EXISTS (no album call)")
            save_to_mongo(path, asset_id, album_name, "Duplicate", True)
            return "Duplicate"
        add_to_album(album_id, asset_id)
        print(f"{path.name}: UPLOADED")
        save_to_mongo(path, asset_id, album_name, "Uploaded", False)
        return "Uploaded"
    except Exception as e:
        print(f"\nERROR {path}: {e}")
        save_to_mongo(path, None, album_name, "Failed", False)
        return "Failed"


def main():
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
