import os
import sys
import asyncio
import aiohttp
import aiofiles
from datetime import datetime, timedelta
from tqdm import tqdm
from pymongo import MongoClient

# ==============================================================
# 1. PLATFORM DETECTION & CONFIGURATION
# ==============================================================
IS_WINDOWS = os.name == 'nt'

SCYFALL_SEARCH_URL = "https://api.scryfall.com/cards/search"

# T drive: where existing MTG card images live (dedup source)
T_DRIVE_FOLDER = r"T:\Full Card Database\Card Database\Magic the Gathering"

# T drive: where new MTG card images get written (destination)
NEW_CARDS_FOLDER = r"T:\Full Card Database\New Cards\Magic the Gathering"

# MongoDB (same database as your card_manager tools)
MONGO_URI = "mongodb://card_manager:1369@100.80.179.119:27018/carddb"
DB_NAME = "carddb"
CARDS_COLLECTION = "scryfall_cards"   # tracks downloaded card IDs
SYNC_COLLECTION = "scryfall_sync"     # tracks last sync date

# How far back to look if we have no stored sync date (days)
DEFAULT_LOOKBACK_DAYS = 30

# Performance Tuning
NUM_WORKERS = 20
MAX_RETRIES = 3


# ==============================
# MongoDB helpers
# ==============================
_client = None

def get_db():
    global _client
    if _client is None:
        _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    return _client[DB_NAME]


def get_last_sync_date():
    """Return the last sync date as YYYY-MM-DD, or a default lookback window."""
    doc = get_db()[SYNC_COLLECTION].find_one({"_id": "last_sync"})
    if doc and doc.get("date"):
        return doc["date"]
    return (datetime.now() - timedelta(days=DEFAULT_LOOKBACK_DAYS)).strftime("%Y-%m-%d")


def save_last_sync_date(date_str):
    get_db()[SYNC_COLLECTION].update_one(
        {"_id": "last_sync"},
        {"$set": {"date": date_str, "synced_at": datetime.now().isoformat()}},
        upsert=True,
    )


def card_already_done(card_id):
    return get_db()[CARDS_COLLECTION].find_one({"_id": card_id}) is not None


def mark_card_done(card_id, name, lang, filename):
    get_db()[CARDS_COLLECTION].update_one(
        {"_id": card_id},
        {"$set": {
            "name": name,
            "lang": lang,
            "filename": filename,
            "downloaded_at": datetime.now().isoformat(),
        }},
        upsert=True,
    )


# ==============================
# Fetch new cards from Scryfall API
# ==============================
async def fetch_new_cards(session, since_date):
    """Return list of (card_id, name, lang, image_url) for cards released since since_date."""
    page_url = f"{SCYFALL_SEARCH_URL}?q=date%3E%3D{since_date}&order=released&dir=asc&page=1"
    cards = []

    while page_url:
        async with session.get(page_url) as resp:
            if resp.status == 429:
                await asyncio.sleep(2)
                continue
            resp.raise_for_status()
            data = await resp.json()

        if data.get("object") == "error":
            print(f"[!] API error: {data.get('details', 'unknown')}")
            break

        for card in data.get("data", []):
            card_id = card.get("id")
            name = card.get("name", "N/A")
            lang = card.get("lang", "N/A")

            if not card_id:
                continue
            if card_already_done(card_id):
                continue
            if "image_uris" not in card:
                continue

            url = card["image_uris"].get("large") or card["image_uris"].get("normal")
            if not url:
                continue

            cards.append((card_id, name, lang, url))

        page_url = data.get("next_page")

    return cards


# ==============================
# Async download worker
# ==============================
async def download_worker(session, queue, pbar):
    """Worker task to asynchronously download card images."""
    while True:
        task = await queue.get()
        if task is None:
            queue.task_done()
            break

        card_id, name, lang, url, filename = task
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                os.makedirs(os.path.dirname(filename), exist_ok=True)

                async with session.get(url, timeout=30) as resp:
                    if resp.status == 200:
                        content = await resp.read()
                        async with aiofiles.open(filename, "wb") as f:
                            await f.write(content)
                        mark_card_done(card_id, name, lang, os.path.basename(filename))
                        tqdm.write(f"[OK] {name} ({lang})")
                        break
                    elif resp.status == 429:  # Rate limited
                        await asyncio.sleep(2 ** attempt)
                    else:
                        tqdm.write(f"[ERR] HTTP {resp.status}: {name}")
            except Exception as e:
                if attempt == MAX_RETRIES:
                    tqdm.write(f"[ERR] Final failure for {name}: {e}")
                else:
                    await asyncio.sleep(1)

        pbar.update(1)
        queue.task_done()


# ==============================
# Main processing (live)
# ==============================
async def run_sync(session):
    print("\n[SYNC] Checking for new MTG cards...\n", flush=True)

    since_date = get_last_sync_date()
    print(f"[INFO] Looking for cards released since {since_date}\n", flush=True)

    # Verify the dedup source exists
    if not os.path.exists(T_DRIVE_FOLDER):
        print(f"[!] WARNING: Dedup source NOT found: {T_DRIVE_FOLDER}")
        print(f"    Existing-image check will not work.\n")
    else:
        print(f"[INFO] Checking existing images in: {T_DRIVE_FOLDER}\n")

    os.makedirs(NEW_CARDS_FOLDER, exist_ok=True)
    print(f"[INFO] Downloading new images to: {NEW_CARDS_FOLDER}\n")

    cards = await fetch_new_cards(session, since_date)

    print(f"[INFO] {len(cards)} candidate card(s) from Scryfall API.\n")

    queue = asyncio.Queue()
    total_queued = 0
    already_on_t = 0

    for card_id, name, lang, url in cards:
        clean_name = name.replace("/", "_").replace(":", "_").replace("?", "").replace("*", "").replace('"', "")
        filename = f"{clean_name}_{lang}.jpg"

        # Check dedup source (Card Database) for existing image
        on_t = os.path.exists(os.path.join(T_DRIVE_FOLDER, filename))

        if on_t:
            already_on_t += 1
            print(f"  [EXISTS]  Already in Card Database: {name} ({lang})")
            continue

        # Queue for download
        output_path = os.path.join(NEW_CARDS_FOLDER, filename)
        await queue.put((card_id, name, lang, url, output_path))
        total_queued += 1

    print(f"\n[SUMMARY] Already in Card DB: {already_on_t}   To download: {total_queued}\n")

    if total_queued == 0:
        print("[DONE] Nothing new to download. Everything is up to date!")
        # Still save today's date so next run doesn't re-scan
        save_last_sync_date(datetime.now().strftime("%Y-%m-%d"))
        return

    with tqdm(total=total_queued, desc="Downloading", unit="card") as pbar:
        workers = [asyncio.create_task(download_worker(session, queue, pbar))
                   for _ in range(NUM_WORKERS)]
        await queue.join()
        for _ in workers:
            await queue.put(None)
        await asyncio.gather(*workers)

    # Save today's date as the new sync point
    save_last_sync_date(datetime.now().strftime("%Y-%m-%d"))
    print("\n[SYNC COMPLETE] All new cards downloaded.")


async def main_async():
    timeout = aiohttp.ClientTimeout(total=None, connect=60, sock_read=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        await run_sync(session)


if __name__ == "__main__":
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n[!] Shutdown requested. Cleaning up...", flush=True)
        sys.exit(0)
