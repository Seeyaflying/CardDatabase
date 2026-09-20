"""
Card Database Harvester
=======================
Downloads TCG card images from TCGCSV into the New Cards folder tree,
organized as {Game}/{Set}/{CardId}.jpg.

Cross-platform: runs on Linux (paths under /storage/Tera/...) or
Windows (paths under T:\\...). Existing records written by the other
OS are translated automatically, so whichever machine harvests a card
first, the other machine skips it (HD=1 means already downloaded).

Requires config.py and db.py in a Utilities folder one level up.
"""

import os
import platform
import sys
import time
import traceback
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import requests
from pymongo import UpdateOne

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "Utilities",
    ),
)
import config
import db


# ============================================================
# CONFIGURATION
# ============================================================

MAX_WORKERS = 3
REQUEST_DELAY = 1          # seconds between card/image requests
GAME_LANGUAGE = "english"
MENU_WIDTH = 78

# --- Debug output -------------------------------------------------
DEBUG = False              # master switch for all debug lines
DEBUG_HTTP = False        # every HTTP request with timing
DEBUG_THREADS = False       # worker thread dispatch/completion
DETAILED_LIVE_FEED = True  # per-product result lines
WATCHDOG_SECONDS = 30      # warn if a worker is stuck this long (0 = off)

# --- Paths (platform-aware) ---------------------------------------
LOGICAL_ROOT = "Full Card Database"

if platform.system() == "Windows":
    NEW_CARDS_ROOT = os.path.join("T:\\", LOGICAL_ROOT, "New Cards")
    EXISTING_IMAGE_ROOTS = [
        os.path.join("T:\\", LOGICAL_ROOT, "Folder Database"),
        NEW_CARDS_ROOT,
    ]
    IGNORED_IMAGE_ROOT = os.path.normcase(
        os.path.abspath(os.path.join("T:\\", LOGICAL_ROOT, "Card Database"))
    )
else:
    NEW_CARDS_ROOT = os.path.join("/storage/Tera", LOGICAL_ROOT, "New Cards")
    EXISTING_IMAGE_ROOTS = [
        os.path.join("/storage/Tera", LOGICAL_ROOT, "Folder Database"),
        NEW_CARDS_ROOT,
    ]
    IGNORED_IMAGE_ROOT = os.path.normcase(
        os.path.abspath(
            os.path.join("/storage/Tera", LOGICAL_ROOT, "Card Database")
        )
    )

# --- TCGCSV ---------------------------------------------------------
TCGCSV_BASE = "https://tcgcsv.com/tcgplayer"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://www.tcgplayer.com/",
}



# ============================================================
# SHARED STATE & HELPERS
# ============================================================

_thread_local = threading.local()
_print_lock = threading.Lock()
_db_lock = threading.Lock()


def get_session():
    if not hasattr(_thread_local, "session"):
        session = requests.Session()
        session.headers.update(HEADERS)
        _thread_local.session = session
    return _thread_local.session


def debug_log(message):
    if DEBUG:
        with _print_lock:
            print(f"[DEBUG] {message}", flush=True)


def http_log(message):
    if DEBUG_HTTP:
        with _print_lock:
            print(f"[HTTP] {message}", flush=True)


def thread_log(message):
    if DEBUG_THREADS:
        with _print_lock:
            print(f"[THREAD] {message}", flush=True)


def print_safe(message):
    with _print_lock:
        print(message, flush=True)


def print_detailed(message):
    if DETAILED_LIVE_FEED:
        print_safe(message)


# ============================================================
# PATH TRANSLATION (cross-platform)
# ============================================================

def translate_path_for_current_os(path):
    """
    Convert a stored path to this platform's format.

    Records written on Linux use /storage/Tera/...; records written
    on Windows use T:\\.... This lets either machine resolve the
    other's records so the HD-skip works across platforms.
    """
    if not path:
        return None

    if platform.system() == "Windows":
        if path.startswith("/storage/Tera/"):
            relative = path[len("/storage/Tera/"):]
            return os.path.join("T:\\", relative)
    else:
        if path.startswith("T:\\") or path.startswith("T:/"):
            relative = path[3:].lstrip("\\/")
            return os.path.join("/storage/Tera", relative)

    return path


def normalize_path(path):
    if not path:
        return None
    return os.path.normcase(os.path.abspath(str(path)))


def is_ignored_path(path):
    normalized = normalize_path(path)
    if not normalized:
        return False
    return (
        normalized == IGNORED_IMAGE_ROOT
        or normalized.startswith(IGNORED_IMAGE_ROOT + os.sep)
    )


def valid_image_file(path):
    if not path:
        return False
    if is_ignored_path(path):
        return False
    if not os.path.isfile(path):
        return False
    if os.path.getsize(path) <= 0:
        return False
    return os.path.splitext(path)[1].lower() in (".jpg", ".jpeg")


# ============================================================
# TCGCSV HTTP
# ============================================================

def tcgcsv_get(url):
    """GET JSON from TCGCSV with retries and debug timing."""
    last_error = None
    http_log(f"GET {url}")

    for attempt in range(1, 4):
        t0 = time.time()
        try:
            http_log(f"  attempt {attempt}/3 ...")
            response = requests.get(url, headers=HEADERS, timeout=60)
            elapsed = time.time() - t0
            http_log(
                f"  attempt {attempt} -> HTTP {response.status_code} "
                f"in {elapsed:.1f}s"
            )

            if response.status_code == 200:
                data = response.json()
                http_log(f"  parsed JSON, {len(data) if isinstance(data, list) else 'dict'} items")
                return data

            last_error = f"HTTP {response.status_code}: {response.text[:200]}"

        except Exception as exc:
            elapsed = time.time() - t0
            last_error = str(exc)
            http_log(f"  attempt {attempt} FAILED after {elapsed:.1f}s: {exc}")

        if attempt < 3:
            http_log(f"  retrying in {5 * attempt}s...")
            time.sleep(5 * attempt)

    raise RuntimeError(f"TCGCSV request failed after 3 attempts: {last_error}")


# ============================================================
# MONGO COLLECTIONS
# ============================================================

def harvester_collection():
    return db.get_db()["tcg_folder_harvester"]


def tcg_master_collection():
    return db.get_db()[config.TCG_MASTER_COLLECTION]


# ============================================================
# INDEXES
# ============================================================

def prepare_harvester_indexes():
    collection = harvester_collection()
    debug_log("Creating indexes...")

    index_specs = [
        (
            [("record_type", 1), ("product_id", 1)],
            {
                "unique": True,
                "partialFilterExpression": {
                    "record_type": "image",
                    "product_id": {"$exists": True},
                },
                "name": "image_product_unique",
            },
        ),
        (
            [("record_type", 1), ("game", 1), ("product_id", 1)],
            {"name": "image_game_product"},
        ),
        (
            [("record_type", 1), ("game", 1), ("group_id", 1)],
            {"name": "group_game_group"},
        ),
        (
            [("record_type", 1), ("status", 1)],
            {"name": "record_status"},
        ),
        (
            [("record_type", 1), ("HD", 1)],
            {"name": "image_hd"},
        ),
        (
            [("record_type", 1), ("run_id", 1)],
            {"name": "run_id"},
        ),
    ]

    for keys, kwargs in index_specs:
        try:
            collection.create_index(keys, **kwargs)
        except Exception as exc:
            debug_log(f"Index {kwargs.get('name', '?')}: {exc}")

    debug_log("Indexes done.")


# ============================================================
# MIGRATIONS
# ============================================================

def migrate_old_image_index():
    target = harvester_collection()
    source = db.get_db()["folder_image_index"]

    existing_count = target.count_documents({"record_type": "image"})
    debug_log(f"migrate_old_image_index: {existing_count} existing image records")
    if existing_count > 0:
        return

    try:
        old_count = source.count_documents({})
        debug_log(f"Old folder_image_index count: {old_count}")
        if old_count == 0:
            return

        print(f" Migrating {old_count} old image records...")
        operations = []

        for old in source.find({}):
            product_id = old.get("product_id")
            if product_id is None:
                continue

            hd = old.get("HD", old.get("hd", 0))
            operations.append(
                UpdateOne(
                    {"record_type": "image", "product_id": str(product_id)},
                    {
                        "$setOnInsert": {
                            "record_type": "image",
                            "product_id": str(product_id),
                            "game": old.get("game"),
                            "group_name": old.get("group_name"),
                            "path": old.get("path"),
                            "HD": 1 if hd else 0,
                            "confirmed": old.get("confirmed", True),
                            "status": old.get("status", "available"),
                            "updated_at": datetime.now().isoformat(),
                        }
                    },
                    upsert=True,
                )
            )

            if len(operations) >= 500:
                target.bulk_write(operations, ordered=False)
                operations = []

        if operations:
            target.bulk_write(operations, ordered=False)

        print(" Migration complete.")
        print()

    except Exception as exc:
        print(f" Warning: old image migration failed: {exc}")
        debug_log(traceback.format_exc())


def migrate_jupyter_records():
    collection = harvester_collection()
    debug_log("Checking for Jupyter-version records...")

    try:
        cursor = collection.find({
            "record_type": {"$exists": False},
            "product_id": {"$exists": True},
        })

        operations = []
        count = 0

        for record in cursor:
            product_id = str(record.get("product_id"))
            hd = record.get("HD", record.get("hd", 0))
            path = record.get("path")

            if not path and record.get("filename"):
                game = record.get("game")
                group = record.get("group_name")
                filename = record.get("filename")
                if game and group and filename:
                    candidate = os.path.join(
                        NEW_CARDS_ROOT, game, group, filename
                    )
                    if os.path.isfile(candidate):
                        path = candidate

            operations.append(
                UpdateOne(
                    {"record_type": "image", "product_id": product_id},
                    {
                        "$set": {
                            "record_type": "image",
                            "product_id": product_id,
                            "game": record.get("game"),
                            "group_name": record.get("group_name"),
                            "path": path,
                            "HD": 1 if hd else 0,
                            "confirmed": record.get("confirmed", True),
                            "status": record.get("status", "available"),
                            "updated_at": datetime.now().isoformat(),
                        }
                    },
                    upsert=True,
                )
            )

            count += 1
            if len(operations) >= 500:
                collection.bulk_write(operations, ordered=False)
                operations = []

        if operations:
            collection.bulk_write(operations, ordered=False)

        debug_log(f"Migrated {count} Jupyter-version records.")

    except Exception as exc:
        print(f" Warning: Jupyter record migration failed: {exc}")
        debug_log(traceback.format_exc())


def prepare_image_index():
    migrate_old_image_index()
    migrate_jupyter_records()

    collection = harvester_collection()
    index = {}

    for record in collection.find({
        "record_type": "image",
        "confirmed": True,
    }):
        product_id = record.get("product_id")
        if product_id is not None:
            index[str(product_id)] = record

    debug_log(f"Image index loaded: {len(index)} confirmed records")
    return index


# ============================================================
# EXISTING IMAGE LOOKUP
# ============================================================

def find_existing_product_image(product_id, image_index):
    """
    Look up a product in the Mongo index. Returns a dict with the
    local (translated) path and HD flag, or None if the card should
    be downloaded fresh.

    The stored path is translated to this platform's format so a
    record written by the other OS resolves correctly here.
    """
    product_id = str(product_id)
    record = image_index.get(product_id)

    if record:
        stored_path = record.get("path")
        path = translate_path_for_current_os(stored_path)
        debug_log(
            f"find_existing[{product_id}]: stored={stored_path!r} "
            f"translated={path!r}"
        )

        if valid_image_file(path):
            return {
                "path": path,
                "HD": 1 if record.get("HD") else 0,
                "record": record,
            }

        debug_log(
            f"find_existing[{product_id}]: translated path invalid, "
            f"will download new"
        )

    debug_log(f"find_existing[{product_id}]: no valid record, will download new")
    return None


# ============================================================
# MONGO IMAGE RECORDS
# ============================================================

def save_image_record(
    product_id,
    game,
    group_name,
    path,
    hd,
    confirmed,
    status,
    extra=None,
):
    collection = harvester_collection()
    product_id = str(product_id)

    record = {
        "record_type": "image",
        "product_id": product_id,
        "game": game,
        "group_name": group_name,
        "path": str(path) if path else None,
        "HD": 1 if hd else 0,
        "confirmed": bool(confirmed),
        "status": status,
        "updated_at": datetime.now().isoformat(),
    }

    if path and os.path.isfile(path):
        record["file_size"] = os.path.getsize(path)

    if extra:
        record.update(extra)

    with _db_lock:
        collection.update_one(
            {"record_type": "image", "product_id": product_id},
            {"$set": record},
            upsert=True,
        )

    debug_log(
        f"save_image_record[{product_id}]: status={status}, "
        f"HD={record['HD']}, confirmed={confirmed}, path={path!r}"
    )


# ============================================================
# DOWNLOAD
# ============================================================

def download_to_file(url, destination):
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    temporary = destination + ".tmp"
    t0 = time.time()

    try:
        session = get_session()
        http_log(f"DOWNLOAD {url}")

        response = session.get(url, timeout=60, stream=True)
        status = response.status_code
        http_log(
            f"  {url.split('/')[-1]} -> HTTP {status} "
            f"in {time.time() - t0:.1f}s"
        )

        if status != 200:
            response.close()
            if os.path.exists(temporary):
                os.remove(temporary)
            return False, status, None

        with open(temporary, "wb") as output:
            for chunk in response.iter_content(chunk_size=1024 * 64):
                if chunk:
                    output.write(chunk)

        response.close()

        if not os.path.isfile(temporary):
            return False, status, "temporary file missing"

        if os.path.getsize(temporary) <= 0:
            os.remove(temporary)
            return False, status, "empty file"

        os.replace(temporary, destination)
        http_log(
            f"  saved {os.path.basename(destination)} "
            f"({os.path.getsize(destination)} bytes) "
            f"in {time.time() - t0:.1f}s"
        )
        return True, status, None

    except Exception as exc:
        http_log(f"  DOWNLOAD FAILED after {time.time() - t0:.1f}s: {exc}")
        if os.path.exists(temporary):
            os.remove(temporary)
        return False, None, str(exc)


def hd_url(product_id):
    return (
        "https://tcgplayer-cdn.tcgplayer.com/product/"
        f"{product_id}_in_1000x1000.jpg"
    )


def fallback_url(product_id):
    return (
        "https://tcgplayer-cdn.tcgplayer.com/product/"
        f"{product_id}_200w.jpg"
    )


# ============================================================
# CARD PROCESSING
# ============================================================
def process_product(
    product,
    game,
    group_name,
    game_folder,
    group_folder,
    image_index,
    card_number,
    total_cards,
):
    thread_log(
        f"start product {card_number}/{total_cards} on "
        f"thread {threading.get_ident()}"
    )

    product_id = str(
        product.get("productId")
        or product.get("product_id")
        or ""
    )
    name = (
        product.get("name")
        or product.get("productName")
        or f"Product {product_id}"
    )

    if not product_id:
        thread_log(f"product {card_number}: INVALID ID")
        return {
            "status": "invalid",
            "message": (
                f"[{card_number:03d}/{total_cards}] "
                f"{name} | INVALID PRODUCT ID"
            ),
        }

    debug_log(
        f"process_product[{product_id}] {name} "
        f"(card {card_number}/{total_cards})"
    )

    existing = find_existing_product_image(product_id, image_index)

    # --- Already have HD: skip -----------------------------------
    if existing and existing["HD"] == 1:
        debug_log(f"process_product[{product_id}]: existing HD, skip")
        save_image_record(
            product_id=product_id,
            game=game,
            group_name=group_name,
            path=existing["path"],
            hd=1,
            confirmed=True,
            status="available",
        )
        thread_log(f"done product {card_number} (skipped)")
        return {
            "status": "skipped",
            "message": (
                f"[{card_number:03d}/{total_cards}] "
                f"{name} | {product_id} | EXISTING HD — skipped"
            ),
        }

    # --- Have 200w: try to upgrade to HD -------------------------
    if existing:
        existing_path = existing["path"]
        debug_log(
            f"process_product[{product_id}]: existing 200w, testing HD"
        )
        if REQUEST_DELAY > 0:
            time.sleep(REQUEST_DELAY)

        success, status, error = download_to_file(
            hd_url(product_id), existing_path
        )

        if success and valid_image_file(existing_path):
            save_image_record(
                product_id=product_id,
                game=game,
                group_name=group_name,
                path=existing_path,
                hd=1,
                confirmed=True,
                status="available",
                extra={"upgraded_from": "200w", "hd_http_status": status},
            )
            image_index[product_id] = {
                "record_type": "image",
                "product_id": product_id,
                "game": game,
                "group_name": group_name,
                "path": existing_path,
                "HD": 1,
                "confirmed": True,
                "status": "available",
            }
            thread_log(f"done product {card_number} (upgraded)")
            return {
                "status": "upgraded",
                "message": (
                    f"[{card_number:03d}/{total_cards}] "
                    f"{name} | {product_id} | 200w → HD ✓"
                ),
            }

        save_image_record(
            product_id=product_id,
            game=game,
            group_name=group_name,
            path=existing_path,
            hd=0,
            confirmed=True,
            status="available",
            extra={"hd_http_status": status, "hd_error": error},
        )
        thread_log(f"done product {card_number} (kept 200w)")
        return {
            "status": "kept",
            "message": (
                f"[{card_number:03d}/{total_cards}] "
                f"{name} | {product_id} | EXISTING 200w — "
                f"HD {status if status is not None else 'ERR'}, kept"
            ),
        }

    # --- New download: try HD, then 200w -------------------------
    destination = os.path.join(
        NEW_CARDS_ROOT, game_folder, group_folder, f"{product_id}.jpg"
    )
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    debug_log(f"process_product[{product_id}]: new download -> {destination}")

    if REQUEST_DELAY > 0:
        time.sleep(REQUEST_DELAY)

    success_hd, hd_status, hd_error = download_to_file(
        hd_url(product_id), destination
    )

    if success_hd and valid_image_file(destination):
        save_image_record(
            product_id=product_id,
            game=game,
            group_name=group_name,
            path=destination,
            hd=1,
            confirmed=True,
            status="available",
            extra={"hd_http_status": hd_status},
        )
        image_index[product_id] = {
            "record_type": "image",
            "product_id": product_id,
            "game": game,
            "group_name": group_name,
            "path": destination,
            "HD": 1,
            "confirmed": True,
            "status": "available",
        }
        thread_log(f"done product {card_number} (HD)")
        return {
            "status": "hd",
            "message": (
                f"[{card_number:03d}/{total_cards}] "
                f"{name} | {product_id} | HD ✓"
            ),
        }

    debug_log(
        f"process_product[{product_id}]: HD failed ({hd_status}), "
        f"trying 200w"
    )

    if REQUEST_DELAY > 0:
        time.sleep(REQUEST_DELAY)

    success_fallback, fallback_status, fallback_error = download_to_file(
        fallback_url(product_id), destination
    )

    if success_fallback and valid_image_file(destination):
        save_image_record(
            product_id=product_id,
            game=game,
            group_name=group_name,
            path=destination,
            hd=0,
            confirmed=True,
            status="available",
            extra={
                "hd_http_status": hd_status,
                "fallback_http_status": fallback_status,
            },
        )
        image_index[product_id] = {
            "record_type": "image",
            "product_id": product_id,
            "game": game,
            "group_name": group_name,
            "path": destination,
            "HD": 0,
            "confirmed": True,
            "status": "available",
        }
        thread_log(f"done product {card_number} (200w)")
        return {
            "status": "fallback",
            "message": (
                f"[{card_number:03d}/{total_cards}] "
                f"{name} | {product_id} | 200w ✓"
            ),
        }

    # --- Both failed: record as unavailable -----------------------
    debug_log(
        f"process_product[{product_id}]: both failed "
        f"(HD={hd_status}, 200w={fallback_status})"
    )
    save_image_record(
        product_id=product_id,
        game=game,
        group_name=group_name,
        path=destination,
        hd=0,
        confirmed=False,
        status="unavailable",
        extra={
            "hd_http_status": hd_status,
            "fallback_http_status": fallback_status,
            "hd_error": hd_error,
            "fallback_error": fallback_error,
        },
    )

    try:
        if os.path.exists(destination):
            os.remove(destination)
    except Exception:
        pass

    thread_log(f"done product {card_number} (unavailable)")
    return {
        "status": "unavailable",
        "message": (
            f"[{card_number:03d}/{total_cards}] "
            f"{name} | {product_id} | N/A — skipped"
        ),
    }


# ============================================================
# GROUP & RUN RECORDS
# ============================================================

def save_group_record(
    run_id, game, site_id, group_id, group_name, status,
    product_count=0, error=None,
):
    collection = harvester_collection()
    record = {
        "record_type": "group",
        "run_id": run_id,
        "game": game,
        "site_id": site_id,
        "group_id": group_id,
        "group_name": group_name,
        "status": status,
        "product_count": product_count,
        "updated_at": datetime.now().isoformat(),
    }
    if error:
        record["error"] = error

    with _db_lock:
        collection.update_one(
            {"record_type": "group", "game": game, "group_id": group_id},
            {"$set": record},
            upsert=True,
        )

    debug_log(f"save_group_record[{group_name}]: status={status}, products={product_count}")


def start_run(game, site_id):
    run_id = f"{game}-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"
    collection = harvester_collection()
    collection.insert_one({
        "record_type": "run",
        "run_id": run_id,
        "game": game,
        "site_id": site_id,
        "status": "running",
        "started_at": datetime.now().isoformat(),
    })
    debug_log(f"Run started: {run_id}")
    return run_id


def finish_run(run_id, status, totals):
    collection = harvester_collection()
    collection.update_one(
        {"record_type": "run", "run_id": run_id},
        {
            "$set": {
                "status": status,
                "finished_at": datetime.now().isoformat(),
                "totals": totals,
            }
        },
    )
    debug_log(f"Run finished: {run_id} status={status}")


# ============================================================
# TCG MASTER / GAMES
# ============================================================

def load_games():
    collection = tcg_master_collection()
    games = []

    debug_log(f"[LOAD] querying {collection.name}")

    cursor = collection.find(
        {
            "language": "english",
            "site_id": {"$gt": 0},
        },
        {
            "_id": 0,
            "tcg_display_name": 1,
            "language": 1,
            "folder_name": 1,
            "site_id": 1,
            "last_run": 1,
            "total_pages": 1,
        },
    ).sort("site_id", 1)

    count = 0
    for doc in cursor:
        count += 1
        debug_log(f"[LOAD] doc {count}: {doc.get('tcg_display_name')} | site_id={doc.get('site_id')}")
        games.append({
            "name": doc.get("tcg_display_name", "Unknown TCG"),
            "language": doc.get("language", "english"),
            "folder_name": doc.get("folder_name", doc.get("tcg_display_name", "Unknown TCG")),
            "site_id": doc.get("site_id", 0),
            "last_run": doc.get("last_run"),
            "total_pages": doc.get("total_pages", 0),
        })

    debug_log(f"[LOAD] total games: {len(games)}")
    debug_log(f"[LOAD] first game name: {games[0]['name'] if games else 'NONE'}")
    return games

# ============================================================
# MENU DISPLAY
# ============================================================

def format_last_run(value):
    return str(value) if value else "Never"


def print_centered(text):
    text = str(text)
    if len(text) > MENU_WIDTH:
        text = text[:MENU_WIDTH]
    padding = MENU_WIDTH - len(text)
    left = padding // 2
    right = padding - left
    print("║" + (" " * left) + text + (" " * right) + "║")


def print_menu_line(number, name, site_id, last_run):
    number_text = str(number).rjust(2)
    site_text = str(site_id).center(8)
    last_text = format_last_run(last_run)
    name_text = str(name)[:38].ljust(38)
    last_text = last_text[:18].ljust(18)
    print(
        f"║ {number_text} ║ {name_text} ║ "
        f"{site_text} ║ {last_text} ║"
    )


def show_main_menu(games):
    os.system("cls")
    print()
    print("╔" + "═" * MENU_WIDTH + "╗")
    print_centered("CARD DATABASE HARVESTER")
    print_centered("TCG IMAGE COLLECTION")
    print("╠════╦" + "═" * 40 + "╦══════════╦════════════════════╗")
    print(
        "║ #  ║ " + "TCG".ljust(40) + " ║"
        + " SITE ID ".center(10) + "║"
        + " LAST RUN ".ljust(20) + "║"
    )
    print("╠════╬" + "═" * 40 + "╬══════════╬════════════════════╣")

    for index, game in enumerate(games, start=1):
        print_menu_line(
            index, game["name"], game["site_id"], game["last_run"]
        )

    print("╚════╩" + "═" * 40 + "╩══════════╩════════════════════╝")
    print()
    print("                     [ A ]  ALL TCGs")
    print("                     [ Q ]  QUIT")
    print()


def show_game_header(game):
    print()
    print("╔" + "═" * MENU_WIDTH + "╗")
    print_centered("STARTING TCG")
    print("╠" + "═" * MENU_WIDTH + "╣")
    print_centered(game["name"])
    print("╠" + "═" * MENU_WIDTH + "╣")
    print_centered(
        f'SITE ID: {game["site_id"]}   |   WORKERS: {MAX_WORKERS}'
    )
    print_centered(f'LAST RUN: {format_last_run(game.get("last_run"))}')
    print("╚" + "═" * MENU_WIDTH + "╝")
    print()


# ============================================================
# GAME SELECTION
# ============================================================

def choose_games(games):
    while True:
        choice = input("                     Select: ").strip().lower()

        if choice == "q":
            return []

        if choice == "a":
            os.system("cls")
            print()
            print("╔" + "═" * MENU_WIDTH + "╗")
            print_centered("STARTING ALL TCGs")
            print("╚" + "═" * MENU_WIDTH + "╝")
            print()
            return games

        if choice.isdigit():
            number = int(choice)
            if 1 <= number <= len(games):
                selected = games[number - 1]
                os.system("cls")
                show_game_header(selected)
                return [selected]

        print()
        print(" Invalid selection. Choose a number, A, or Q.")
        print()


# ============================================================
# GROUP / PRODUCT FETCHING
# ============================================================

def get_groups(site_id):
    url = f"{TCGCSV_BASE}/{site_id}/groups"
    data = tcgcsv_get(url)
    if isinstance(data, dict):
        return data.get("results", data.get("groups", []))
    if isinstance(data, list):
        return data
    return []


def get_products(site_id, group_id):
    url = f"{TCGCSV_BASE}/{site_id}/{group_id}/products"
    data = tcgcsv_get(url)
    if isinstance(data, dict):
        return data.get("results", data.get("products", []))
    if isinstance(data, list):
        return data
    return []


# ============================================================
# WATCHDOG
# ============================================================

def watchdog_thread(stop_event, futures, label):
    if WATCHDOG_SECONDS <= 0:
        return

    start = time.time()
    while not stop_event.is_set():
        time.sleep(5)
        elapsed = time.time() - start
        pending = [f for f in futures if not f.done()]
        if pending:
            print_safe(
                f"[WATCHDOG] {label}: {len(pending)} futures "
                f"still pending after {elapsed:.0f}s"
            )


# ============================================================
# GAME PROCESSING
# ============================================================

def process_game(game):
    game_name = game["name"]
    site_id = game["site_id"]
    game_folder = game["folder_name"]

    show_game_header(game)
    run_id = start_run(game_name, site_id)

    totals = {
        "groups": 0,
        "groups_failed": 0,
        "cards": 0,
        "hd": 0,
        "fallback": 0,
        "upgraded": 0,
        "skipped": 0,
        "kept": 0,
        "unavailable": 0,
        "invalid": 0,
    }

    try:
        image_index = prepare_image_index()

        debug_log(f"Fetching groups for {game_name} (site_id={site_id})")

        try:
            groups = get_groups(site_id)
        except Exception as exc:
            print_safe(f" Failed to fetch groups for {game_name}: {exc}")
            debug_log(traceback.format_exc())
            finish_run(run_id, "failed", totals)
            return

        total_groups = len(groups)
        print_safe(f" Found {total_groups} groups.")
        print()

        for group_number, group in enumerate(groups, start=1):
            group_id = (
                group.get("groupId")
                or group.get("group_id")
                or group.get("id")
            )
            group_name = (
                group.get("name")
                or group.get("groupName")
                or f"Group {group_id}"
            )

            debug_log(
                f"Group {group_number}/{total_groups}: "
                f"{group_name} (id={group_id})"
            )

            if not group_id:
                print_safe(
                    f" [{group_number}/{total_groups}]: {group_name} "
                    f"| INVALID GROUP ID"
                )
                totals["groups_failed"] += 1
                continue

            try:
                products = get_products(site_id, group_id)
            except Exception as exc:
                print_safe(
                    f" [{group_number}/{total_groups}] "
                    f"{group_name} | FAILED: {exc}"
                )
                totals["groups_failed"] += 1
                save_group_record(
                    run_id, game_name, site_id, group_id,
                    group_name, "error", error=str(exc),
                )
                continue

            total_cards = len(products)
            print_safe(
                f"[GROUP {group_number}/{total_groups}] "
                f"{group_name}"
            )
            print_safe(f"  {total_cards} products.")
            totals["groups"] += 1
            totals["cards"] += total_cards

            if total_cards == 0:
                save_group_record(
                    run_id, game_name, site_id, group_id,
                    group_name, "complete", product_count=0,
                )
                continue

            group_folder = group_name
            futures = []

            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                for card_number, product in enumerate(products, start=1):
                    future = executor.submit(
                        process_product,
                        product,
                        game_name,
                        group_name,
                        game_folder,
                        group_folder,
                        image_index,
                        card_number,
                        total_cards,
                    )
                    futures.append(future)

                stop_event = threading.Event()
                watch = threading.Thread(
                    target=watchdog_thread,
                    args=(stop_event, futures, group_name),
                    daemon=True,
                )
                watch.start()

                for future in as_completed(futures):
                    try:
                        result = future.result()
                        status = result.get("status")
                        if status in totals:
                            totals[status] += 1
                        print_detailed(result.get("message", ""))
                    except Exception as exc:
                        print_safe(f" Worker error: {exc}")
                        debug_log(traceback.format_exc())
                        totals["unavailable"] += 1

                stop_event.set()
                watch.join(timeout=1)

            save_group_record(
                run_id, game_name, site_id, group_id,
                group_name, "complete", product_count=total_cards,
            )

        finish_run(run_id, "complete", totals)

    except Exception as exc:
        print_safe(f" Error processing {game_name}: {exc}")
        debug_log(traceback.format_exc())
        finish_run(run_id, "failed", totals)


# ============================================================
# SUMMARY
# ============================================================

def print_summary(totals):
    print()
    print("╔" + "═" * MENU_WIDTH + "╗")
    print_centered("SUMMARY")
    print("╠" + "═" * MENU_WIDTH + "╣")
    print_centered(f"Groups: {totals['groups']}  "
                   f"(failed: {totals['groups_failed']})")
    print_centered(f"Cards: {totals['cards']}")
    print_centered(f"  HD: {totals['hd']}")
    print_centered(f"  200w: {totals['fallback']}")
    print_centered(f"  Upgraded: {totals['upgraded']}")
    print_centered(f"  Skipped (existing HD): {totals['skipped']}")
    print_centered(f"  Kept (existing 200w): {totals['kept']}")
    print_centered(f"  Unavailable: {totals['unavailable']}")
    print_centered(f"  Invalid: {totals['invalid']}")
    print("╚" + "═" * MENU_WIDTH + "╝")
    print()


# ============================================================
# MAIN
# ============================================================

def main():
    print()
    print("╔" + "═" * MENU_WIDTH + "╗")
    print_centered("CARD DATABASE HARVESTER")
    print_centered("TCG IMAGE COLLECTION")
    print("╚" + "═" * MENU_WIDTH + "╝")
    print()

    prepare_harvester_indexes()

    games = load_games()
    if not games:
        print(" No games found in tcg_master. Exiting.")
        return

    show_main_menu(games)              # ← ADD THIS LINE
    selected = choose_games(games)
    if not selected:
        print(" Exiting.")
        return

    all_totals = {
        "groups": 0,
        "groups_failed": 0,
        "cards": 0,
        "hd": 0,
        "fallback": 0,
        "upgraded": 0,
        "skipped": 0,
        "kept": 0,
        "unavailable": 0,
        "invalid": 0,
    }

    for game in selected:
        process_game(game)
        all_totals["groups"] += totals_from_run(game["name"])

    print_summary(all_totals)

def totals_from_run(game_name):
    """Aggregate totals for a game from its most recent run record."""
    collection = harvester_collection()
    latest = collection.find_one(
        {"record_type": "run", "game": game_name},
        sort=[("started_at", -1)],
    )
    if latest and latest.get("totals"):
        return latest["totals"]
    return {}


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        print(" Interrupted by user. Exiting.")
    except Exception as exc:
        print(f" Fatal error: {exc}")
        debug_log(traceback.format_exc())
