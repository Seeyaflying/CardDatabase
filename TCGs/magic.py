import os
import sys
import json
import ijson
import aiohttp
import asyncio
import aiofiles
from tqdm import tqdm

# ==============================================================
# 1. PLATFORM DETECTION & CONFIGURATION
# ==============================================================
IS_WINDOWS = os.name == 'nt'

# The JSON bulk data file remains in the script directory
JSON_FILE = "scryfall_all_cards.json"
SCYFALL_BULK_DATA_URL = "https://api.scryfall.com/bulk-data"

if IS_WINDOWS:
    # Windows Native Google Drive Paths
    OUTPUT_FOLDER = r"G:\My Drive\New Cards\Magic the Gathering"
    CHECK_FOLDER = r"G:\My Drive\Card Database\Magic the Gathering"
else:
    # Ubuntu Paths (Assumes rclone mount at ~/Desktop/GDrive)
    # Note: Using .expanduser ensures the path works regardless of your Ubuntu username
    OUTPUT_FOLDER = os.path.expanduser("~/Desktop/GDrive/New Cards/Magic the Gathering")
    CHECK_FOLDER = os.path.expanduser("~/Desktop/GDrive/Card Database/Magic the Gathering")

# Performance Tuning
NUM_WORKERS = 50  # Slightly lowered for Linux stability over rclone
MAX_RETRIES = 3


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

        name, lang, url, filename = task
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                # Ensure the directory exists (important if rclone mount flickers)
                os.makedirs(os.path.dirname(filename), exist_ok=True)

                async with session.get(url, timeout=30) as resp:
                    if resp.status == 200:
                        content = await resp.read()
                        async with aiofiles.open(filename, "wb") as f:
                            await f.write(content)
                        # Use tqdm.write instead of print to avoid breaking the progress bar
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
# Process JSON and queue tasks
# ==============================
async def process_cards(session: aiohttp.ClientSession):
    print("\n[PROCESS] Starting card image processing...", flush=True)

    search_locations = [
        {"path": OUTPUT_FOLDER, "label": "New Cards"},
        {"path": CHECK_FOLDER, "label": "Card Database"}
    ]

    # Pre-check valid locations
    valid_locations = [loc for loc in search_locations if os.path.exists(loc["path"])]

    if not valid_locations and not IS_WINDOWS:
        print(f"[!] WARNING: No Google Drive folders found. Is rclone mounted?")

    print(f"[INFO] Scanning for duplicates in: {[loc['label'] for loc in valid_locations]}\n", flush=True)

    queue = asyncio.Queue()
    total_queued = 0

    # We use ijson to stream the large Scryfall file without crashing RAM
    try:
        with open(JSON_FILE, "rb") as f:  # Opened in binary for ijson
            for card in ijson.items(f, "item"):
                name = card.get("name", "N/A")
                lang = card.get("lang", "N/A")

                if "image_uris" not in card:
                    continue

                url = card["image_uris"].get("large") or card["image_uris"].get("normal")
                if not url:
                    continue

                # Cross-platform filename cleaning
                # Linux is lenient, but we keep the Windows cleaning so the G-Drive sync remains valid
                clean_name = name.replace("/", "_").replace(":", "_").replace("?", "").replace("*", "").replace('"', "")
                filename = f"{clean_name}_{lang}.jpg"

                already_exists = False
                found_location_label = ""

                # Check folders
                for loc in valid_locations:
                    if os.path.exists(os.path.join(loc["path"], filename)):
                        already_exists = True
                        found_location_label = loc["label"]
                        break

                if already_exists:
                    # Skip logged for clarity
                    continue
                else:
                    output_path = os.path.join(OUTPUT_FOLDER, filename)
                    await queue.put((name, lang, url, output_path))
                    total_queued += 1
    except FileNotFoundError:
        print(f"[!] Error: {JSON_FILE} not found.")
        return

    print(f"\n[SUMMARY] Total cards queued for download: {total_queued}\n", flush=True)

    if total_queued == 0:
        print("[DONE] Everything is already up to date!")
        return

    # Setup progress bar and workers
    with tqdm(total=total_queued, desc="MTG Sync Progress", unit="card") as pbar:
        # Create pool of worker tasks
        workers = [asyncio.create_task(download_worker(session, queue, pbar)) for _ in range(NUM_WORKERS)]

        # Wait for all items in the queue to be processed
        await queue.join()

        # Stop workers
        for _ in workers:
            await queue.put(None)
        await asyncio.gather(*workers)


# ==============================
# Scryfall Bulk Data Helpers
# ==============================
async def fetch_bulk_data_uri(session: aiohttp.ClientSession) -> str:
    async with session.get(SCYFALL_BULK_DATA_URL) as resp:
        resp.raise_for_status()
        data = await resp.json()
        all_cards_data = next((item for item in data.get("data", []) if item.get("type") == "all_cards"), None)
        return all_cards_data["download_uri"]


async def download_json_file(session: aiohttp.ClientSession, uri: str):
    async with session.get(uri) as resp:
        resp.raise_for_status()
        total_size = int(resp.headers.get('content-length', 0))
        with tqdm(total=total_size, unit='B', unit_scale=True, desc=f"Downloading {JSON_FILE}") as pbar:
            async with aiofiles.open(JSON_FILE, 'wb') as f:
                async for chunk in resp.content.iter_chunked(64 * 1024):  # Larger chunks for faster I/O
                    await f.write(chunk)
                    pbar.update(len(chunk))


async def main_async():
    # Use a custom timeout for the whole session
    timeout = aiohttp.ClientTimeout(total=None, connect=60, sock_read=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        if not os.path.exists(JSON_FILE):
            print(f"[JSON] Fetching new Scryfall bulk file...", flush=True)
            uri = await fetch_bulk_data_uri(session)
            await download_json_file(session, uri)

        await process_cards(session)


if __name__ == "__main__":
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n[!] Shutdown requested. Cleaning up...", flush=True)
        sys.exit(0)