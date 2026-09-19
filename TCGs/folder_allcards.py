import os
import sys
import time
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from pymongo import UpdateOne

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Utilities"))
import config
import db


# ============================================================
# SETTINGS
# ============================================================

MAX_WORKERS = 5

# Seconds between card/image requests.
# Set to 1 for one second per card.
REQUEST_DELAY = 1

GAME_LANGUAGE = "english"

MENU_WIDTH = 78

DETAILED_LIVE_FEED = False

# New downloads go here
NEW_CARDS_ROOT = r"T:\Full Card Database\New Cards"

# Existing images may already be in either of these locations
EXISTING_IMAGE_ROOTS = [
    r"T:\Full Card Database\Folder Database",
    r"T:\Full Card Database\New Cards",
]

# Explicitly ignored
IGNORED_IMAGE_ROOT = os.path.normcase(
    os.path.abspath(r"T:\Full Card Database\Card Database")
)


# ============================================================
# TCGCSV
# ============================================================

TCGCSV_BASE = "https://tcgcsv.com/tcgplayer"

HEADERS = {
    "User-Agent": "CardDatabase-Harvester/1.0 (Seeyaflying)",
    "Accept": "application/json",
}


_thread_local = threading.local()
_print_lock = threading.Lock()
_db_lock = threading.Lock()


def get_session():
    """
    Each worker thread gets its own requests Session.
    """
    if not hasattr(_thread_local, "session"):
        session = requests.Session()
        session.headers.update(HEADERS)
        _thread_local.session = session

    return _thread_local.session


def tcgcsv_get(url):
    """
    GET JSON from TCGCSV with retries.
    """
    last_error = None

    for attempt in range(1, 4):
        try:
            response = requests.get(
                url,
                headers=HEADERS,
                timeout=60,
            )

            if response.status_code == 200:
                return response.json()

            last_error = (
                f"HTTP {response.status_code}: "
                f"{response.text[:200]}"
            )

        except Exception as exc:
            last_error = str(exc)

        if attempt < 3:
            time.sleep(5 * attempt)

    raise RuntimeError(
        f"TCGCSV request failed after 3 attempts: {last_error}"
    )


# ============================================================
# MONGO
# ============================================================

def harvester_collection():
    return db.get_db()["tcg_folder_harvester"]


def tcg_master_collection():
    return db.get_db()["tcg_master"]


def prepare_harvester_indexes():
    """
    Create indexes used by the harvester.
    """
    collection = harvester_collection()

    try:
        collection.create_index(
            [("record_type", 1), ("product_id", 1)],
            unique=True,
            partialFilterExpression={
                "record_type": "image",
                "product_id": {"$exists": True},
            },
            name="image_product_unique",
        )
    except Exception:
        pass

    try:
        collection.create_index(
            [("record_type", 1), ("game", 1), ("product_id", 1)],
            name="image_game_product",
        )
    except Exception:
        pass

    try:
        collection.create_index(
            [("record_type", 1), ("game", 1), ("group_id", 1)],
            name="group_game_group",
        )
    except Exception:
        pass

    try:
        collection.create_index(
            [("record_type", 1), ("status", 1)],
            name="record_status",
        )
    except Exception:
        pass

    try:
        collection.create_index(
            [("record_type", 1), ("HD", 1)],
            name="image_hd",
        )
    except Exception:
        pass

    try:
        collection.create_index(
            [("record_type", 1), ("run_id", 1)],
            name="run_id",
        )
    except Exception:
        pass


# ============================================================
# OLD IMAGE INDEX MIGRATION
# ============================================================

def migrate_old_image_index():
    """
    Migrate confirmed records from the old folder_image_index
    collection into tcg_folder_harvester.

    The old collection is preserved.
    """
    target = harvester_collection()
    source = db.get_db()["folder_image_index"]

    existing_count = target.count_documents(
        {"record_type": "image"}
    )

    if existing_count > 0:
        return

    try:
        old_count = source.count_documents({})

        if old_count == 0:
            return

        print(
            f" Migrating {old_count} old image records..."
        )

        operations = []

        for old in source.find({}):
            product_id = old.get("product_id")

            if product_id is None:
                continue

            product_id = str(product_id)

            hd = old.get("HD", old.get("hd", 0))

            record = {
                "record_type": "image",
                "product_id": product_id,
                "game": old.get("game"),
                "group_name": old.get("group_name"),
                "path": old.get("path"),
                "HD": 1 if hd else 0,
                "confirmed": old.get("confirmed", True),
                "status": old.get(
                    "status",
                    "available",
                ),
                "updated_at": datetime.now().isoformat(),
            }

            operations.append(
                UpdateOne(
                    {
                        "record_type": "image",
                        "product_id": product_id,
                    },
                    {
                        "$setOnInsert": record,
                    },
                    upsert=True,
                )
            )

            if len(operations) >= 500:
                target.bulk_write(
                    operations,
                    ordered=False,
                )
                operations = []

        if operations:
            target.bulk_write(
                operations,
                ordered=False,
            )

        print(" Migration complete.")
        print()

    except Exception as exc:
        print(
            f" Warning: old image migration failed: {exc}"
        )


def prepare_image_index():
    """
    Migrate old records and return confirmed image records
    indexed by product ID.
    """
    migrate_old_image_index()

    collection = harvester_collection()

    index = {}

    for record in collection.find(
        {
            "record_type": "image",
            "confirmed": True,
        }
    ):
        product_id = record.get("product_id")

        if product_id is not None:
            index[str(product_id)] = record

    return index


# ============================================================
# FILE HELPERS
# ============================================================

def normalize_path(path):
    if not path:
        return None

    return os.path.normcase(
        os.path.abspath(str(path))
    )


def is_ignored_path(path):
    normalized = normalize_path(path)

    if not normalized:
        return False

    return (
        normalized == IGNORED_IMAGE_ROOT
        or normalized.startswith(
            IGNORED_IMAGE_ROOT + os.sep
        )
    )


def valid_image_file(path):
    """
    Basic file validation.

    This checks:
    - file exists
    - file is a file
    - file has non-zero size
    - jpg/jpeg extension

    It does not fully decode the JPEG.
    """
    if not path:
        return False

    if is_ignored_path(path):
        return False

    if not os.path.isfile(path):
        return False

    if os.path.getsize(path) <= 0:
        return False

    extension = os.path.splitext(path)[1].lower()

    return extension in (".jpg", ".jpeg")


def find_existing_product_image(
    product_id,
    image_index,
):
    """
    Find an existing image using Mongo first, then filesystem scan.

    Returns:
        {
            "path": ...,
            "HD": 0/1,
            "record": ...
        }

    or None.
    """

    product_id = str(product_id)

    # --------------------------------------------------------
    # Mongo path
    # --------------------------------------------------------

    record = image_index.get(product_id)

    if record:
        path = record.get("path")

        if valid_image_file(path):
            return {
                "path": path,
                "HD": 1 if record.get("HD") else 0,
                "record": record,
            }

    # --------------------------------------------------------
    # Filesystem search
    # --------------------------------------------------------

    target_filename = f"{product_id}.jpg"

    for root in EXISTING_IMAGE_ROOTS:

        if not os.path.isdir(root):
            continue

        for current_root, dirs, files in os.walk(root):

            # Do not search ignored database directory
            dirs[:] = [
                d
                for d in dirs
                if not is_ignored_path(
                    os.path.join(current_root, d)
                )
            ]

            if target_filename not in files:
                continue

            candidate = os.path.join(
                current_root,
                target_filename,
            )

            if not valid_image_file(candidate):
                continue

            # We found it.
            #
            # If Mongo knows it is HD, trust that.
            # Otherwise treat it as 200w until HD is tested.
            hd = 0

            if record:
                hd = 1 if record.get("HD") else 0

            return {
                "path": candidate,
                "HD": hd,
                "record": record,
            }

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
            {
                "record_type": "image",
                "product_id": product_id,
            },
            {
                "$set": record,
            },
            upsert=True,
        )


# ============================================================
# DOWNLOAD
# ============================================================

def download_to_file(
    url,
    destination,
):
    """
    Download directly to destination using a .tmp file
    in the same directory.

    Returns:
        (success, http_status, error)
    """

    os.makedirs(
        os.path.dirname(destination),
        exist_ok=True,
    )

    temporary = destination + ".tmp"

    try:
        session = get_session()

        response = session.get(
            url,
            timeout=60,
            stream=True,
        )

        status = response.status_code

        if status != 200:
            try:
                response.close()
            except Exception:
                pass

            if os.path.exists(temporary):
                try:
                    os.remove(temporary)
                except Exception:
                    pass

            return False, status, None

        with open(
            temporary,
            "wb",
        ) as output:

            for chunk in response.iter_content(
                chunk_size=1024 * 64
            ):
                if chunk:
                    output.write(chunk)

        response.close()

        if not os.path.isfile(temporary):
            return False, status, "temporary file missing"

        if os.path.getsize(temporary) <= 0:
            try:
                os.remove(temporary)
            except Exception:
                pass

            return False, status, "empty file"

        os.replace(
            temporary,
            destination,
        )

        return True, status, None

    except Exception as exc:

        if os.path.exists(temporary):
            try:
                os.remove(temporary)
            except Exception:
                pass

        return False, None, str(exc)


# ============================================================
# IMAGE URLS
# ============================================================

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
# OUTPUT
# ============================================================

def print_safe(message):
    with _print_lock:
        print(message, flush=True)


def print_detailed(message):
    if DETAILED_LIVE_FEED:
        print_safe(message)


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
    """
    Process one product.

    Behavior:

    Existing HD:
        skip with no HTTP request.

    Existing 200w:
        test HD only.
        If HD works -> replace file.
        If HD fails -> keep 200w.

    No existing image:
        HD first.
        Then 200w.

    Both fail:
        record unavailable.
    """

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
        return {
            "status": "invalid",
            "message": (
                f"[{card_number:03d}/{total_cards}] "
                f"{name} | INVALID PRODUCT ID"
            ),
        }

    # --------------------------------------------------------
    # Existing image lookup
    # --------------------------------------------------------

    existing = find_existing_product_image(
        product_id,
        image_index,
    )

    if existing:

        existing_path = existing["path"]
        existing_hd = existing["HD"]

        # ----------------------------------------------------
        # Existing confirmed HD
        # ----------------------------------------------------

        if existing_hd == 1:
            save_image_record(
                product_id=product_id,
                game=game,
                group_name=group_name,
                path=existing_path,
                hd=1,
                confirmed=True,
                status="available",
            )

            return {
                "status": "skipped",
                "message": (
                    f"[{card_number:03d}/{total_cards}] "
                    f"{name} | {product_id} | "
                    f"EXISTING HD — skipped"
                ),
            }

        # ----------------------------------------------------
        # Existing 200w: test HD only
        # ----------------------------------------------------

        if REQUEST_DELAY > 0:
            time.sleep(REQUEST_DELAY)

        success, status, error = download_to_file(
            hd_url(product_id),
            existing_path,
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
                extra={
                    "upgraded_from": "200w",
                    "hd_http_status": status,
                },
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

            return {
                "status": "upgraded",
                "message": (
                    f"[{card_number:03d}/{total_cards}] "
                    f"{name} | {product_id} | "
                    f"200w → HD ✓"
                ),
            }

        # HD failed.
        # Keep the existing 200w.
        save_image_record(
            product_id=product_id,
            game=game,
            group_name=group_name,
            path=existing_path,
            hd=0,
            confirmed=True,
            status="available",
            extra={
                "hd_http_status": status,
                "hd_error": error,
            },
        )

        return {
            "status": "kept",
            "message": (
                f"[{card_number:03d}/{total_cards}] "
                f"{name} | {product_id} | "
                f"EXISTING 200w — HD "
                f"{status if status is not None else 'ERR'}, kept"
            ),
        }

    # --------------------------------------------------------
    # New image
    # --------------------------------------------------------

    destination = os.path.join(
        NEW_CARDS_ROOT,
        game_folder,
        group_folder,
        f"{product_id}.jpg",
    )

    os.makedirs(
        os.path.dirname(destination),
        exist_ok=True,
    )

    # --------------------------------------------------------
    # HD
    # --------------------------------------------------------

    if REQUEST_DELAY > 0:
        time.sleep(REQUEST_DELAY)

    success_hd, hd_status, hd_error = download_to_file(
        hd_url(product_id),
        destination,
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
            extra={
                "hd_http_status": hd_status,
            },
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

        return {
            "status": "hd",
            "message": (
                f"[{card_number:03d}/{total_cards}] "
                f"{name} | {product_id} | HD ✓"
            ),
        }

    # --------------------------------------------------------
    # Fallback 200w
    # --------------------------------------------------------

    if REQUEST_DELAY > 0:
        time.sleep(REQUEST_DELAY)

    success_fallback, fallback_status, fallback_error = (
        download_to_file(
            fallback_url(product_id),
            destination,
        )
    )

    if (
        success_fallback
        and valid_image_file(destination)
    ):

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

        return {
            "status": "fallback",
            "message": (
                f"[{card_number:03d}/{total_cards}] "
                f"{name} | {product_id} | 200w ✓"
            ),
        }

    # --------------------------------------------------------
    # Both failed
    # --------------------------------------------------------

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

    hd_result = (
        str(hd_status)
        if hd_status is not None
        else "ERR"
    )

    fallback_result = (
        str(fallback_status)
        if fallback_status is not None
        else "ERR"
    )

    return {
        "status": "unavailable",
        "message": (
            f"[{card_number:03d}/{total_cards}] "
            f"{name} | {product_id} | "
            f"HD {hd_result} → "
            f"200w {fallback_result} — skipped"
        ),
    }


# ============================================================
# GROUP RECORDS
# ============================================================

def save_group_record(
    run_id,
    game,
    site_id,
    group_id,
    group_name,
    status,
    product_count=0,
    error=None,
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
            {
                "record_type": "group",
                "game": game,
                "group_id": group_id,
            },
            {
                "$set": record,
            },
            upsert=True,
        )


# ============================================================
# RUN RECORDS
# ============================================================

def start_run(
    game,
    site_id,
):
    run_id = (
        f"{game}-"
        f"{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"
    )

    collection = harvester_collection()

    collection.insert_one(
        {
            "record_type": "run",
            "run_id": run_id,
            "game": game,
            "site_id": site_id,
            "status": "running",
            "started_at": datetime.now().isoformat(),
        }
    )

    return run_id


def finish_run(
    run_id,
    status,
    totals,
):
    collection = harvester_collection()

    collection.update_one(
        {
            "record_type": "run",
            "run_id": run_id,
        },
        {
            "$set": {
                "status": status,
                "finished_at": datetime.now().isoformat(),
                "totals": totals,
            }
        },
    )


# ============================================================
# TCG MASTER
# ============================================================

def load_games():
    """
    Load all English TCGs with site_id > 0.

    Uses the actual tcg_master fields:
        tcg_display_name
        language
        folder_name
        site_id
        last_run
        total_pages
    """

    collection = tcg_master_collection()

    games = []

    cursor = collection.find(
        {
            "language": GAME_LANGUAGE,
            "site_id": {
                "$gt": 0,
            },
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
    ).sort(
        "site_id",
        1,
    )

    for doc in cursor:

        games.append(
            {
                "name": doc.get(
                    "tcg_display_name",
                    "Unknown TCG",
                ),
                "language": doc.get(
                    "language",
                    GAME_LANGUAGE,
                ),
                "folder_name": doc.get(
                    "folder_name",
                    doc.get(
                        "tcg_display_name",
                        "Unknown TCG",
                    ),
                ),
                "site_id": doc.get(
                    "site_id",
                    0,
                ),
                "last_run": doc.get(
                    "last_run"
                ),
                "total_pages": doc.get(
                    "total_pages",
                    0,
                ),
            }
        )

    return games


# ============================================================
# MENU DISPLAY
# ============================================================

def format_last_run(value):
    if not value:
        return "Never"

    return str(value)


def print_centered(text):
    text = str(text)

    if len(text) > MENU_WIDTH:
        text = text[:MENU_WIDTH]

    padding = MENU_WIDTH - len(text)

    left = padding // 2
    right = padding - left

    print(
        "║"
        + (" " * left)
        + text
        + (" " * right)
        + "║"
    )


def print_menu_line(
    number,
    name,
    site_id,
    last_run,
):
    number_text = str(number).rjust(2)
    site_text = str(site_id).center(8)
    last_text = format_last_run(last_run)

    # Available width:
    #
    # ║  1 ║ TCG NAME ...                 ║ SITE ID ║ LAST RUN         ║
    #

    name_width = 38
    last_width = 18

    name_text = str(name)[:name_width].ljust(
        name_width
    )

    last_text = last_text[:last_width].ljust(
        last_width
    )

    print(
        f"║ {number_text} ║ "
        f"{name_text} ║ "
        f"{site_text} ║ "
        f"{last_text} ║"
    )


def show_main_menu(games):
    os.system("cls")

    print()
    print("╔" + "═" * MENU_WIDTH + "╗")

    print_centered(
        "CARD DATABASE HARVESTER"
    )

    print_centered(
        "TCG IMAGE COLLECTION"
    )

    print(
        "╠════╦"
        + "═" * 40
        + "╦══════════╦════════════════════╗"
    )

    print(
        "║ #  ║ "
        + "TCG".ljust(40)
        + " ║"
        + " SITE ID ".center(10)
        + "║"
        + " LAST RUN ".ljust(20)
        + "║"
    )

    print(
        "╠════╬"
        + "═" * 40
        + "╬══════════╬════════════════════╣"
    )

    for index, game in enumerate(
        games,
        start=1,
    ):
        print_menu_line(
            index,
            game["name"],
            game["site_id"],
            game["last_run"],
        )

    print(
        "╚════╩"
        + "═" * 40
        + "╩══════════╩════════════════════╝"
    )

    print()
    print(
        "                     [ A ]  ALL TCGs"
    )
    print(
        "                     [ Q ]  QUIT"
    )
    print()


# ============================================================
# GAME HEADER
# ============================================================

def show_game_header(game):
    print()
    print("╔" + "═" * MENU_WIDTH + "╗")
    print_centered("STARTING TCG")
    print("╠" + "═" * MENU_WIDTH + "╣")
    print_centered(game["name"])
    print("╠" + "═" * MENU_WIDTH + "╣")

    print_centered(
        f'SITE ID: {game["site_id"]}   |   '
        f"WORKERS: {MAX_WORKERS}"
    )

    print_centered(
        f'LAST RUN: {format_last_run(game.get("last_run"))}'
    )

    print("╚" + "═" * MENU_WIDTH + "╝")
    print()


# ============================================================
# GAME SELECTION
# ============================================================

def choose_games(games):
    """
    Number:
        Immediately start selected TCG.

    A:
        Immediately start all TCGs.

    Q:
        Quit.

    There is deliberately no confirmation prompt.
    """

    while True:

        choice = input(
            "                     Select: "
        ).strip().lower()

        # ----------------------------------------------------
        # Quit
        # ----------------------------------------------------

        if choice == "q":
            return []

        # ----------------------------------------------------
        # All TCGs
        # ----------------------------------------------------

        if choice == "a":

            os.system("cls")

            print()
            print(
                "╔"
                + "═" * MENU_WIDTH
                + "╗"
            )

            print_centered(
                "STARTING ALL TCGs"
            )

            print(
                "╚"
                + "═" * MENU_WIDTH
                + "╝"
            )

            print()

            return games

        # ----------------------------------------------------
        # Individual TCG
        # ----------------------------------------------------

        if choice.isdigit():

            number = int(choice)

            if 1 <= number <= len(games):

                selected = games[
                    number - 1
                ]

                os.system("cls")

                show_game_header(
                    selected
                )

                return [selected]

        # ----------------------------------------------------
        # Invalid
        # ----------------------------------------------------

        print()
        print(
            " Invalid selection. "
            "Choose a number, A, or Q."
        )
        print()


# ============================================================
# GROUP / PRODUCT FETCHING
# ============================================================

def get_groups(site_id):
    """
    Fetch all groups for a TCG.
    """

    url = (
        f"{TCGCSV_BASE}/"
        f"{site_id}/groups"
    )

    data = tcgcsv_get(url)

    if isinstance(data, dict):
        return data.get(
            "results",
            data.get(
                "groups",
                [],
            ),
        )

    if isinstance(data, list):
        return data

    return []


def get_products(
    site_id,
    group_id,
):
    """
    Fetch products for one group.
    """

    url = (
        f"{TCGCSV_BASE}/"
        f"{site_id}/"
        f"{group_id}/products"
    )

    data = tcgcsv_get(url)

    if isinstance(data, dict):
        return data.get(
            "results",
            data.get(
                "products",
                [],
            ),
        )

    if isinstance(data, list):
        return data

    return []


# ============================================================
# GAME PROCESSING
# ============================================================

def process_game(game):
    """
    Harvest one TCG.
    """

    game_name = game["name"]
    site_id = game["site_id"]
    game_folder = game["folder_name"]

    show_game_header(game)

    run_id = start_run(
        game_name,
        site_id,
    )

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

        # ----------------------------------------------------
        # Prepare image index
        # ----------------------------------------------------

        image_index = prepare_image_index()

        # ----------------------------------------------------
        # Fetch groups
        # ----------------------------------------------------

        try:
            groups = get_groups(
                site_id
            )

        except Exception as exc:

            print_safe(
                f" Failed to fetch groups for "
                f"{game_name}: {exc}"
            )

            finish_run(
                run_id,
                "failed",
                totals,
            )

            return

        total_groups = len(groups)

        print_safe(
            f" Found {total_groups} groups."
        )
        print()

        # ----------------------------------------------------
        # Process groups serially
        # ----------------------------------------------------

        for group_number, group in enumerate(
            groups,
            start=1,
        ):

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

            print_safe(
                f"[GROUP {group_number}/{total_groups}] "
                f"{group_name}"
            )

            # ------------------------------------------------
            # Fetch products
            # ------------------------------------------------

            try:

                products = get_products(
                    site_id,
                    group_id,
                )

            except Exception as exc:

                totals["groups_failed"] += 1

                save_group_record(
                    run_id=run_id,
                    game=game_name,
                    site_id=site_id,
                    group_id=group_id,
                    group_name=group_name,
                    status="failed",
                    error=str(exc),
                )

                print_safe(
                    f"    → FAILED: {exc}"
                )
                print()

                continue

            product_count = len(products)

            totals["groups"] += 1
            totals["cards"] += product_count

            save_group_record(
                run_id=run_id,
                game=game_name,
                site_id=site_id,
                group_id=group_id,
                group_name=group_name,
                status="completed",
                product_count=product_count,
            )

            print_safe(
                f"    → {product_count} products | "
                f"{MAX_WORKERS} workers"
            )

            if not products:
                print()
                continue

            # ------------------------------------------------
            # Group folder
            # ------------------------------------------------

            safe_group_folder = (
                str(group_name)
                .replace("\\", "_")
                .replace("/", "_")
                .replace(":", "_")
                .replace("*", "_")
                .replace("?", "_")
                .replace('"', "_")
                .replace("<", "_")
                .replace(">", "_")
                .replace("|", "_")
            )

            group_folder = safe_group_folder

            # ------------------------------------------------
            # Concurrent image processing
            # ------------------------------------------------

            futures = {}

            with ThreadPoolExecutor(
                max_workers=MAX_WORKERS
            ) as executor:

                for index, product in enumerate(
                    products,
                    start=1,
                ):

                    future = executor.submit(
                        process_product,
                        product,
                        game_name,
                        group_name,
                        game_folder,
                        group_folder,
                        image_index,
                        index,
                        product_count,
                    )

                    futures[future] = index

                for future in as_completed(
                    futures
                ):

                    try:

                        result = future.result()

                        status = result.get(
                            "status"
                        )

                        if status in totals:
                            totals[status] += 1

                        print_safe(
                            "    "
                            + result.get(
                                "message",
                                "",
                            )
                        )

                    except Exception as exc:

                        print_safe(
                            f"    Worker error: {exc}"
                        )

            print()

        # ----------------------------------------------------
        # Finished
        # ----------------------------------------------------

        finish_run(
            run_id,
            "completed",
            totals,
        )

        print()
        print("╔" + "═" * MENU_WIDTH + "╗")
        print_centered(
            f"FINISHED: {game_name}"
        )
        print("╠" + "═" * MENU_WIDTH + "╣")

        print_centered(
            f'Groups: {totals["groups"]}'
        )

        print_centered(
            f'Cards: {totals["cards"]}'
        )

        print_centered(
            f'HD: {totals["hd"]}'
        )

        print_centered(
            f'200w: {totals["fallback"]}'
        )

        print_centered(
            f'Upgraded: {totals["upgraded"]}'
        )

        print_centered(
            f'Skipped: {totals["skipped"]}'
        )

        print_centered(
            f'Kept 200w: {totals["kept"]}'
        )

        print_centered(
            f'Unavailable: {totals["unavailable"]}'
        )

        print("╚" + "═" * MENU_WIDTH + "╝")
        print()

    except KeyboardInterrupt:

        finish_run(
            run_id,
            "interrupted",
            totals,
        )

        print()
        print(
            " Harvest interrupted by user."
        )

        raise

    except Exception as exc:

        finish_run(
            run_id,
            "failed",
            {
                **totals,
                "error": str(exc),
            },
        )

        print()
        print(
            f" Game failed: {exc}"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    # --------------------------------------------------------
    # Initialize Mongo indexes
    # --------------------------------------------------------

    try:
        db.init_db()
        prepare_harvester_indexes()

    except Exception as exc:

        print()
        print(
            "MongoDB initialization failed:"
        )
        print(exc)
        print()

        return

    # --------------------------------------------------------
    # Load TCGs
    # --------------------------------------------------------

    try:
        games = load_games()

    except Exception as exc:

        print()
        print(
            "Could not load tcg_master:"
        )
        print(exc)
        print()

        return

    # --------------------------------------------------------
    # No games
    # --------------------------------------------------------

    if not games:

        os.system("cls")

        print()
        print(
            "╔"
            + "═" * MENU_WIDTH
            + "╗"
        )

        print_centered(
            "CARD DATABASE HARVESTER"
        )

        print(
            "╠"
            + "═" * MENU_WIDTH
            + "╣"
        )

        print_centered(
            "No English TCGs with site_id > 0"
        )

        print_centered(
            "were found in tcg_master."
        )

        print(
            "╚"
            + "═" * MENU_WIDTH
            + "╝"
        )

        print()

        return

    # --------------------------------------------------------
    # SHOW MENU
    # --------------------------------------------------------

    show_main_menu(
        games
    )

    # --------------------------------------------------------
    # USER SELECTION
    # --------------------------------------------------------

    selected_games = choose_games(
        games
    )

    # --------------------------------------------------------
    # Quit
    # --------------------------------------------------------

    if not selected_games:

        os.system("cls")

        print()
        print(
            " CARD DATABASE HARVESTER"
        )
        print(
            " Goodbye."
        )
        print()

        return

    # --------------------------------------------------------
    # START IMMEDIATELY
    # --------------------------------------------------------

    for game in selected_games:

        process_game(
            game
        )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()