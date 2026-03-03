import asyncio
import aiohttp
import aiofiles
import logging
import os
import re
import json
import sqlite3
import traceback
from tqdm.asyncio import tqdm
from datetime import datetime

# ------------------------------
# 1. CONFIGURATION & PATHS
# ------------------------------
DB_FILE = "skipped_images.sqlite"
TABLE_NAME = "skipped_images"
LANGUAGE_TYPE = "english"
SAVE_ROOT = "G:/My Drive/New Cards"
CHECK_ROOT = "G:/My Drive/Card Database"
LOG_FOLDER = "log"

# Ensure directories exist
os.makedirs(LOG_FOLDER, exist_ok=True)
os.makedirs(SAVE_ROOT, exist_ok=True)
os.makedirs(CHECK_ROOT, exist_ok=True)

# ------------------------------
# 2. LOGGING SETUP
# ------------------------------
log_file_path = os.path.join(LOG_FOLDER, datetime.now().strftime('%Y-%m-%d_%H-%M-%S') + '.log')
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    handlers=[logging.FileHandler(log_file_path), logging.StreamHandler()]
)
logger = logging.getLogger("downloader")

# ------------------------------
# 3. TCG DATA (DEFAULT FALLBACK)
# ------------------------------
BASE_API_URL = 'https://tcgcsv.com/tcgplayer'
DEFAULT_TCG_IDS = {
    'Akora': 75, "Alpha Clash": 78, 'Argent Saga': 61, 'Bakugan': 58,
    'Battle Spirits Saga': 72, 'Cardfight Vanguard': 16, 'Caster Chronicles': 37,
    "Chrono Clash System": 60, "Dice Masters": 18, "Digimon": 63, "DBZ TCG": 23,
    "DBZ Super": 27, "DBZ Super Fusion World": 80, "Dragoborne": 28, "Elestrals": 83,
    "Final Fantasy": 24, "Flesh and Blood": 62, "Force of Will": 17,
    "Future Card BuddyFight": 19, "Gate Ruler": 65, "Godzilla Card Game": 88,
    "Grand Archive": 74, "Gundam": 86, "Hololive": 87, "Kryptik": 76,
    "Lightseekers": 48, "Lorcana": 71, "MetaX": 30, "MetaZoo": 66,
    "Munchkin": 53, "One Piece": 68, "Pokemon": 3, "Riftbound": 89,
    "Shadowverse Evolve": 73, "Sorcery Contested Realm": 77, "Star Wars Destiny": 26,
    "Star Wars Unlimited": 79, "Transformers": 57, "Union Arena": 81,
    "UniVersus": 25, "Warhammer Age of Sigmar Champions": 54, "Weiss Schwarz": 20,
    "Wixoss": 67, "World of Warcraft": 13, "Yugioh": 2, "Zombie World Order": 36,
}


def load_tcg_urls():
    """Loads from JSON if available, otherwise builds from DEFAULT_TCG_IDS."""
    try:
        if os.path.exists('json/tcg_urls.json'):
            with open('json/tcg_urls.json', 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Could not load json/tcg_urls.json: {e}")

    # Fallback logic: Format matches what the script expects
    return {tcg: [f'{BASE_API_URL}/{tcg_id}/groups'] for tcg, tcg_id in DEFAULT_TCG_IDS.items()}


# ------------------------------
# 4. DATABASE HELPERS
# ------------------------------
def ensure_table():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            language TEXT NOT NULL,
            image_name TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def load_skipped_image_ids(language_type):
    ensure_table()
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(f"SELECT image_name FROM {TABLE_NAME} WHERE language=?", (language_type,))
        # Store as set for O(1) lookups
        result = {str(row[0]) for row in cursor.fetchall()}
        conn.close()
        logger.info(f"Loaded {len(result)} skipped IDs from database.")
        return result
    except Exception as e:
        logger.error(f"Failed to read DB: {e}")
        return set()


# ------------------------------
# 5. ASYNC CORE LOGIC
# ------------------------------
async def fetch_json(session, url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
        async with session.get(url, headers=headers, timeout=15) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get('results', [])
    except Exception:
        return []
    return []


async def download_image(session, image_url, save_folder, image_name, skipped_ids, existing_filenames, semaphore):
    async with semaphore:
        # A. Check Database via Regex ID extraction
        id_match = re.search(r'(\d+)', image_name)
        if id_match:
            img_id = id_match.group(1)
            # Match against raw ID or the _200w version used in your DB
            if img_id in skipped_ids or f"{img_id}_200w" in skipped_ids:
                return

        # B. Check Both Folders (The 'Existing' Set)
        if image_name in existing_filenames:
            return

        # C. Download Logic
        image_path = os.path.join(save_folder, image_name)
        try:
            async with session.get(image_url, timeout=20) as response:
                if response.status == 200:
                    data = await response.read()
                    async with aiofiles.open(image_path, 'wb') as f:
                        await f.write(data)
                    existing_filenames.add(image_name)  # Add to set to prevent dupe in same run
                    logger.info(f"Downloaded: {image_name}")
        except Exception as e:
            logger.error(f"Error downloading {image_name}: {e}")


async def process_tcg(session, tcg_name, urls, skipped_ids):
    semaphore = asyncio.Semaphore(15)

    local_save_dir = os.path.join(SAVE_ROOT, tcg_name)
    local_check_dir = os.path.join(CHECK_ROOT, tcg_name)
    os.makedirs(local_save_dir, exist_ok=True)

    # Scans both New Cards and Card Database for existing files
    existing_files = set()
    for path in [local_save_dir, local_check_dir]:
        if os.path.exists(path):
            existing_files.update(os.listdir(path))

    for url in urls:
        groups_data = await fetch_json(session, url)
        for group in tqdm(groups_data, desc=f" {tcg_name}", leave=False):
            group_id = group.get('groupId')
            cat_id = group.get('categoryId')
            if not group_id: continue

            # Fetch products in group
            products = await fetch_json(session, f'{BASE_API_URL}/{cat_id}/{group_id}/products')
            tasks = []
            for item in products:
                img_url = item.get('imageUrl')
                if img_url:
                    img_name = img_url.split('/')[-1]
                    tasks.append(download_image(session, img_url, local_save_dir, img_name, skipped_ids, existing_files,
                                                semaphore))

            if tasks:
                await asyncio.gather(*tasks)


# ------------------------------
# 6. MAIN EXECUTION WITH FREEZE-ON-FAIL
# ------------------------------
async def main_async():
    skipped_ids = load_skipped_image_ids(LANGUAGE_TYPE)
    tcg_config = load_tcg_urls()

    async with aiohttp.ClientSession() as session:
        for tcg_name, urls in tqdm(tcg_config.items(), desc="Overall Progress"):
            await process_tcg(session, tcg_name, urls, skipped_ids)


if __name__ == '__main__':
    try:
        asyncio.run(main_async())
        print("\n" + "=" * 50)
        print("SUCCESS: Processing complete.")
        print("=" * 50)
    except Exception:
        print("\n" + "!" * 50)
        print("CRITICAL ERROR DETECTED:")
        # This provides the full line-by-line breakdown of the crash
        traceback.print_exc()
        print("!" * 50)
    finally:
        # This keeps the terminal open so you can read the error before it returns to your manager
        input("\nPress [Enter] to close this script and return to manager...")