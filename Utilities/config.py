import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ============ FOLDERS (the flow) ============
CARD_UPLOAD   = Path(os.getenv("CARD_UPLOAD",   r"T:\Card Upload"))
CARD_DATABASE = Path(os.getenv("CARD_DATABASE", r"T:\Card Database"))
G_DRIVE       = Path(os.getenv("G_DRIVE",       r"G:\My Drive\Card Database"))

# ============ DATABASE (everything except Immich) ============
MONGO_URI  = os.getenv("MONGO_URI", "mongodb://card_manager:1369@100.80.179.119:27018/carddb")
DB_NAME    = os.getenv("DB_NAME", "carddb")
COLLECTION = os.getenv("COLLECTION", "card_index")

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
