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
JSON_FILE = "scryfall_all_cards.json"
SCYFALL_BULK_DATA_URL = "https://api.scryfall.com/bulk-data"

# Updated folder names per your request
OUTPUT_FOLDER = "G:/My Drive/New Cards/Magic the Gathering"
CHECK_FOLDER = "G:/My Drive/Card Database/Magic the Gathering"

NUM_WORKERS = 100
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
                # Print starting status
                print(f"[DL] Starting: {name} ({lang})", flush=True)
                async with session.get(url) as resp:
                    if resp.status == 200:
                        content = await resp.read()
                        async with aiofiles.open(filename, "wb") as f:
                            await f.write(content)
                        print(f"[OK] Finished: {name} ({lang})", flush=True)
                        break
                    else:
                        print(f"[ERR] HTTP {resp.status}: {name}", flush=True)
            except Exception as e:
                if attempt == MAX_RETRIES:
                    print(f"[ERR] Final failure for {name}: {e}", flush=True)
                else:
                    await asyncio.sleep(1)

        pbar.update(1)
        queue.task_done()


# ==============================
# Process JSON and queue tasks
# ==============================
async def process_cards(session: aiohttp.ClientSession):
    print("\n[PROCESS] Starting card image processing...", flush=True)

    os.makedirs(OUTPUT_FOLDER, exist_ok=True)

    # Define locations with user-friendly labels for the terminal
    search_locations = [
        {"path": OUTPUT_FOLDER, "label": "New Cards"},
        {"path": CHECK_FOLDER, "label": "Card Database"}
    ]

    # Filter to only paths that exist
    valid_locations = [loc for loc in search_locations if os.path.exists(loc["path"])]

    print(f"[INFO] Scanning for duplicates in: {[loc['label'] for loc in valid_locations]}\n", flush=True)

    queue = asyncio.Queue()
    total_queued = 0

    with open(JSON_FILE, "r", encoding="utf-8") as f:
        for idx, card in enumerate(ijson.items(f, "item"), 1):
            name = card.get("name", "N/A")
            lang = card.get("lang", "N/A")

            if "image_uris" not in card:
                continue

            url = card["image_uris"].get("large") or card["image_uris"].get("normal")
            if not url:
                continue

            # Clean name for Windows/G-Drive compatibility
            clean_name = name.replace("/", "_").replace(":", "_").replace("?", "").replace("*", "")
            filename = f"{clean_name}_{lang}.jpg"

            already_exists = False
            found_location_label = ""

            # Check both locations and identify which one has the file
            for loc in valid_locations:
                if os.path.exists(os.path.join(loc["path"], filename)):
                    already_exists = True
                    found_location_label = loc["label"]
                    break

            if already_exists:
                # Specify which folder it was found in
                print(f"[SKIP] {name} ({lang}) found in [{found_location_label}]", flush=True)
            else:
                # Print queueing status
                print(f"[QUEUE] {name} ({lang}) -> Adding to New Cards", flush=True)
                output_path = os.path.join(OUTPUT_FOLDER, filename)
                await queue.put((name, lang, url, output_path))
                total_queued += 1

    print(f"\n[SUMMARY] Total cards queued for download: {total_queued}\n", flush=True)

    # Setup progress bar and workers
    with tqdm(total=total_queued, desc="Downloading Images", unit="card") as pbar:
        workers = [asyncio.create_task(download_worker(session, queue, pbar)) for _ in range(NUM_WORKERS)]
        await queue.join()

        for _ in workers:
            await queue.put(None)
        await asyncio.gather(*workers)


# ==============================
# Main Orchestration & JSON helpers
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
                async for chunk in resp.content.iter_chunked(8192):
                    await f.write(chunk)
                    pbar.update(len(chunk))


async def main_async():
    async with aiohttp.ClientSession() as session:
        if not os.path.exists(JSON_FILE):
            print(f"[JSON] Fetching new Scryfall bulk file...", flush=True)
            uri = await fetch_bulk_data_uri(session)
            await download_json_file(session, uri)

        await process_cards(session)


if __name__ == "__main__":
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.", flush=True)
        sys.exit(0)