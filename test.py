import os
import sys
import ijson
import aiohttp
import asyncio
import aiofiles
from tqdm import tqdm

# ==============================
# Configuration
# ==============================
JSON_FILE = "scryfall_all_cards.json"   # Path to your downloaded Scryfall bulk file
OUTPUT_FOLDER = "foreign_cards"         # Folder to save new downloads
CHECK_FOLDER = "check_folder"           # Folder with already existing images
NUM_WORKERS = 10                        # Number of async download workers
MAX_RETRIES = 3                          # Retry downloads

# ==============================
# Async download worker
# ==============================
async def download_worker(session, queue, pbar):
    while True:
        task = await queue.get()
        if task is None:
            queue.task_done()
            break

        name, lang, url, filename = task
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                print(f"[DL] Downloading {name} ({lang}) -> {os.path.basename(filename)}", flush=True)
                async with session.get(url) as resp:
                    if resp.status == 200:
                        content = await resp.read()
                        async with aiofiles.open(filename, "wb") as f:
                            await f.write(content)
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
# Process JSON and queue tasks
# ==============================
async def process_cards():
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    os.makedirs(CHECK_FOLDER, exist_ok=True)

    queue = asyncio.Queue()
    total_queued = 0

    async with aiohttp.ClientSession() as session:
        # First, scan JSON and queue tasks
        with open(JSON_FILE, "r", encoding="utf-8") as f:
            for idx, card in enumerate(ijson.items(f, "item"), 1):
                # Only non-English cards with images
                if card.get("lang") != "en" and "image_uris" in card:
                    name = card["name"]
                    lang = card["lang"]
                    url = card["image_uris"].get("large") or card["image_uris"].get("normal")

                    if not url:
                        print(f"[SKIP] No image for {name} ({lang})", flush=True)
                        continue

                    filename = f"{name}_{lang}.jpg".replace("/", "_")
                    output_path = os.path.join(OUTPUT_FOLDER, filename)
                    check_path = os.path.join(CHECK_FOLDER, filename)

                    # Debug print for every foreign card
                    print(f"[CARD] #{idx}: {name} ({lang})", flush=True)

                    if os.path.exists(output_path) or os.path.exists(check_path):
                        print(f"    -> Skipped (already exists in folders)", flush=True)
                    else:
                        print(f"    -> Queued for download -> {filename}", flush=True)
                        await queue.put((name, lang, url, output_path))
                        total_queued += 1

        print(f"Total cards queued for download: {total_queued}", flush=True)

        # Setup progress bar and workers
        with tqdm(total=total_queued, desc="Downloading", unit="card") as pbar:
            workers = [asyncio.create_task(download_worker(session, queue, pbar)) for _ in range(NUM_WORKERS)]
            await queue.join()

            # Stop workers
            for _ in workers:
                await queue.put(None)
            await asyncio.gather(*workers)

# ==============================
# Entry point
# ==============================
if __name__ == "__main__":
    if not os.path.exists(JSON_FILE):
        print(f"Error: {JSON_FILE} not found")
        sys.exit(1)

    asyncio.run(process_cards())
    print("Done downloading foreign card images!", flush=True)
