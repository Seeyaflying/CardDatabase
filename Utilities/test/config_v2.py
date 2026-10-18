import os
from pathlib import Path

# MongoDB
MONGO_URI = os.getenv("MONGO_URI", "mongodb://card_manager:1369@100.80.179.119:27018/carddb")
DB_NAME   = os.getenv("DB_NAME", "carddb")

# Collections
PROGRESS_COLLECTION = "progress"        # OLD — being retired, do not write to
CARD_TRACKER_COLL   = "card_tracker"    # NEW — single source of truth
DRIVE_YES_DIR = r"T:\Full Card Database\Card Upload"   # uploader reads this
# Optional G: archive (not used right now):
# G_DRIVE_ARCHIVE = r"G:\My Drive\Card Database"
# Folders
NEW_CARDS_DIR       = r"T:\Full Card Database\New Cards"
CARD_UPLOAD_DIR     = r"T:\Full Card Database\Card Upload"
FOLDER_DATABASE_DIR = r"T:\Full Card Database\Folder Database"
SKIPPED_DIR         = r"T:\Full Card Database\Skipped Cards"

# G: drive — optional archive, not used right now
G_DRIVE_DIR         = r"G:\My Drive\Card Database"

from dotenv import load_dotenv

# ============ FOLDERS (the flow) ============
CARD_UPLOAD   = Path(os.getenv("CARD_UPLOAD",   r"T:\Card Upload"))
CARD_DATABASE = Path(os.getenv("CARD_DATABASE", r"T:\Card Database"))
G_DRIVE       = Path(os.getenv("G_DRIVE",       r"G:\My Drive\Card Database"))



# ============ IMMICH (keeps its own SQLite) ============
IMMICH_URL      = os.getenv("IMMICH_URL", "http://100.80.179.119:8081")
IMMICH_API_KEY  = os.getenv("IMMICH_API_KEY", "")
IMMICH_DB       = os.getenv("IMMICH_DB", "immich_uploads.db")
IMMICH_MAX_WORKERS = int(os.getenv("IMMICH_MAX_WORKERS", "12"))

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".tif", ".tiff"}

PROGRESS_COLLECTION = os.getenv("PROGRESS_COLLECTION", "progress")
RUN_HISTORY_COLLECTION = os.getenv("RUN_HISTORY_COLLECTION", "run_history")
TCG_MASTER_COLLECTION      = os.getenv("TCG_MASTER_COLLECTION", "tcg_master")
SKIPPED_IMAGES_COLLECTION  = os.getenv("SKIPPED_IMAGES_COLLECTION", "skipped_images")

# Old skipped-images collection
SKIPPED_IMAGES_COLLECTION = os.getenv(
    "SKIPPED_IMAGES_COLLECTION",
    "skipped_images"
)

# TCG image harvester collection
FOLDER_SKIPPED_IMAGES_COLLECTION = os.getenv(
    "FOLDER_SKIPPED_IMAGES_COLLECTION",
    "folder_skipped_images"
)

FOLDER_IMAGE_INDEX_COLLECTION = os.getenv(
    "FOLDER_IMAGE_INDEX_COLLECTION",
    "folder_image_index")
