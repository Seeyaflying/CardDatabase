import os
import sys
import json
import ijson
import aiohttp
import asyncio
import aiofiles
from tqdm import tqdm

# ==============================
# Configuration
# ==============================
JSON_FILE = "scryfall_all_cards.json"  # Path where the Scryfall bulk file will be saved
SCYFALL_BULK_DATA_URL = "https://api.scryfall.com/bulk-data"  # Scryfall API endpoint
OUTPUT_FOLDER = "G:/My Drive/New Cards/Magic the Gathering"  # Folder to save new downloads
CHECK_FOLDER = "G:/My Drive/New Cards/Card Database"  # Folder with already existing images
NUM_WORKERS = 30  # Number of async download workers
MAX_RETRIES = 3  # Retry downloads


# ==============================
# Async download worker
# ==============================
async def download_worker(session, queue, pbar):
    """Worker task to asynchronously download card images from the queue."""
    while True:
        task = await queue.get()
        if task is None:
            queue.task_done()
            break

        name, lang, url, filename = task
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                # Print the image being downloaded
                print(f"[DL] Downloading {name} ({lang}) -> {os.path.basename(filename)}", flush=True)
                async with session.get(url) as resp:
                    if resp.status == 200:
                        content = await resp.read()
                        async with aiofiles.open(filename, "wb") as f:
                            await f.write(content)
                        # Print download success
                        print(f"[OK] Finished {name} ({lang})", flush=True)
                        break
                    else:
                        print(f"[ERR] Failed {name} ({lang}) -> HTTP {resp.status}", flush=True)
            except Exception as e:
                if attempt == MAX_RETRIES:
                    print(f"[ERR] Exception downloading {name} ({lang}): {e}", flush=True)
                else:
                    print(f"[RETRY] {name} ({lang}) attempt {attempt} failed: {e}", flush=True)
                    await asyncio.sleep(1)

        pbar.update(1)
        queue.task_done()


# ==============================
# JSON file preparation
# ==============================
async def fetch_bulk_data_uri(session: aiohttp.ClientSession) -> str:
    """Fetches the current download URI for the 'All Cards' bulk data."""
    print(f"[JSON] Fetching Scryfall bulk data index from {SCYFALL_BULK_DATA_URL}...", flush=True)
    try:
        async with session.get(SCYFALL_BULK_DATA_URL) as resp:
            resp.raise_for_status()
            data = await resp.json()

            # Find the 'All Cards' data object
            all_cards_data = next(
                (item for item in data.get("data", []) if item.get("type") == "all_cards"),
                None
            )

            if all_cards_data and "download_uri" in all_cards_data:
                uri = all_cards_data["download_uri"]
                print(f"[JSON] Found download URI: {uri}", flush=True)
                return uri
            else:
                raise Exception("Could not find 'all_cards' download URI in API response.")

    except Exception as e:
        print(f"[FATAL] Failed to fetch bulk data URI: {e}", flush=True)
        sys.exit(1)


async def download_json_file(session: aiohttp.ClientSession, uri: str):
    """Downloads the JSON file and shows progress."""
    print(f"[JSON] Starting download of {JSON_FILE}...", flush=True)
    try:
        async with session.get(uri) as resp:
            resp.raise_for_status()
            total_size = int(resp.headers.get('content-length', 0))

            with tqdm(total=total_size, unit='B', unit_scale=True, desc=f"Downloading {JSON_FILE}") as pbar:
                async with aiofiles.open(JSON_FILE, 'wb') as f:
                    # Stream the download
                    async for chunk in resp.content.iter_chunked(8192):
                        await f.write(chunk)
                        pbar.update(len(chunk))

            print(f"[JSON] Successfully downloaded and saved {JSON_FILE}.", flush=True)

    except Exception as e:
        print(f"[FATAL] Failed to download {JSON_FILE}: {e}", flush=True)
        # Attempt to clean up corrupted file
        if os.path.exists(JSON_FILE):
            os.remove(JSON_FILE)
        sys.exit(1)


# ==============================
# Process JSON and queue tasks
# ==============================
async def process_cards(session: aiohttp.ClientSession):
    """Reads the local JSON file and queues image downloads."""
    print("\n[PROCESS] Starting card image processing...", flush=True)

    # Ensure output folder exists
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)

    # Check if CHECK_FOLDER exists, but do not create it
    check_folder_exists = os.path.exists(CHECK_FOLDER)
    if not check_folder_exists:
        print(f"[INFO] Check folder '{CHECK_FOLDER}' not found. Skipping file existence checks against it.", flush=True)

    queue = asyncio.Queue()
    total_queued = 0

    # ijson allows streaming access to the large JSON file
    with open(JSON_FILE, "r", encoding="utf-8") as f:
        for idx, card in enumerate(ijson.items(f, "item"), 1):
            name = card.get("name", "N/A")
            lang = card.get("lang", "N/A")

            # --- MODIFIED: Debug print for every card being checked ---
            print(f"[CHECK] #{idx}: {name} ({lang})", flush=True)

            if "image_uris" not in card:
                print(f"    -> [SKIP] No 'image_uris' data for this card.", flush=True)
                continue

            # Use "large" image URI if available, otherwise "normal"
            url = card["image_uris"].get("large") or card["image_uris"].get("normal")

            if not url:
                print(f"    -> [SKIP] No valid image URL found.", flush=True)
                continue

            filename = f"{name}_{lang}.jpg".replace("/", "_")
            output_path = os.path.join(OUTPUT_FOLDER, filename)

            already_exists = False

            # Check 1: Output Folder (always check)
            if os.path.exists(output_path):
                already_exists = True

            # Check 2: Check Folder (only check if the folder exists)
            if not already_exists and check_folder_exists:
                check_path = os.path.join(CHECK_FOLDER, filename)
                if os.path.exists(check_path):
                    already_exists = True

            if already_exists:
                # --- MODIFIED: Debug print for skipped card ---
                print(f"    -> [SKIP] File already exists in OUTPUT or CHECK folder.", flush=True)
            else:
                # --- MODIFIED: Debug print for queued card ---
                print(f"    -> [QUEUE] Queued for download: {filename}", flush=True)
                await queue.put((name, lang, url, output_path))
                total_queued += 1

    print(f"Total cards queued for download: {total_queued}", flush=True)

    # Setup progress bar and workers
    with tqdm(total=total_queued, desc="Downloading Images", unit="card") as pbar:
        workers = [asyncio.create_task(download_worker(session, queue, pbar)) for _ in range(NUM_WORKERS)]
        await queue.join()

        # Stop workers
        for _ in workers:
            await queue.put(None)
        await asyncio.gather(*workers)

    print("\n[PROCESS] Done downloading card images for all languages!", flush=True)


# ==============================
# Main orchestration
# ==============================
async def main_async():
    """Main entry point that handles JSON download and card processing and cleanup."""

    # Use a single session for all HTTP requests
    async with aiohttp.ClientSession() as session:
        json_downloaded_in_this_run = False

        # 1. Check and download JSON file
        if not os.path.exists(JSON_FILE):
            print(f"[JSON] Required file {JSON_FILE} not found. Starting download sequence.")
            # Get the download URI for the bulk data
            download_uri = await fetch_bulk_data_uri(session)
            # Download the JSON file
            await download_json_file(session, download_uri)
            json_downloaded_in_this_run = True  # Track that we created the file
        else:
            print(f"[JSON] Found existing file {JSON_FILE}. Skipping download.")

        # 2. Process the cards in the downloaded JSON file
        await process_cards(session)

        # 3. Cleanup: Delete JSON file if it was downloaded in this run
        if json_downloaded_in_this_run and os.path.exists(JSON_FILE):
            try:
                print(f"[CLEANUP] Deleting temporary bulk data file: {JSON_FILE}", flush=True)
                os.remove(JSON_FILE)
            except OSError as e:
                print(f"[CLEANUP ERROR] Failed to delete {JSON_FILE}: {e}", flush=True)
        elif os.path.exists(JSON_FILE):
            print(f"[CLEANUP] Keeping existing bulk data file: {JSON_FILE} (was not downloaded in this run).",
                  flush=True)


# ==============================
# Entry point
# ==============================
if __name__ == "__main__":
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.", flush=True)
        sys.exit(0)
