import asyncio
import aiohttp
import aiofiles
import logging
import os
import re
from tqdm.asyncio import tqdm
from datetime import datetime
import json
import sqlite3

# ------------------------------
# Config
# ------------------------------
DB_FILE = "skipped_images.sqlite"
TABLE_NAME = "skipped_images"
LANGUAGE_TYPE = "english"  # Only English images
SAVE_ROOT = "G:/My Drive/New Cards"
CHECK_FOLDER = "G:/My Drive/Card Database"
LOG_FOLDER = "log"

os.makedirs(LOG_FOLDER, exist_ok=True)

# ------------------------------
# Logging
# ------------------------------
now = datetime.now()
log_file_path = os.path.join(LOG_FOLDER, now.strftime('%Y-%m-%d_%H-%M-%S') + '.log')

logger = logging.getLogger("english_downloader")
logger.setLevel(logging.INFO)
file_handler = logging.FileHandler(log_file_path)
file_handler.setFormatter(logging.Formatter('%(message)s'))
logger.addHandler(file_handler)
logger.addHandler(logging.StreamHandler())

# ------------------------------
# Database helpers
# ------------------------------
def ensure_table():
    """Create table if it doesn't exist."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            language TEXT NOT NULL,
            image_number TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def load_skipped_image_ids(language_type):
    """Read skipped images from DB for the given language."""
    ensure_table()
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(f"SELECT image_number FROM {TABLE_NAME} WHERE language=?", (language_type,))
        result = {f"{row[0]}_200w" for row in cursor.fetchall()}  # Append _200w for English
        conn.close()
        logger.info(f"Loaded {len(result)} skipped {language_type} images from database.")
        return result
    except Exception as e:
        logger.error(f"Failed to read skipped images: {e}")
        return set()

# ------------------------------
# TCG URLs (default)
# ------------------------------
BASE_URL = 'https://tcgcsv.com/tcgplayer'
DEFAULT_TCG_IDS = {
    'Akora': 75,
    "Alpha Clash": 78,
    'Argent Saga': 61,
    'Bakugan': 58,
    'Battle Spirits Saga': 72,
    'Cardfight Vanguard': 16,
    'Caster Chronicles': 37,
    "Chrono Clash System": 60,
    "Dice Masters": 18,
    "Digimon": 63,
    "DBZ TCG": 23,
    "DBZ Super": 27,
    "DBZ Super Fusion World": 80,
    "Dragoborne": 28,
    "Elestrals": 83,
    "Final Fantasy": 24,
    "Flesh and Blood": 62,
    "Force of Will": 17,
    "Future Card BuddyFight": 19,
    "Gate Ruler": 65,
    "Godzilla Card Game": 88,
    "Grand Archive": 74,
    "Gundam": 86,
    "Hololive": 87,
    "Kryptik": 76,
    "Lightseekers": 48,
    "Lorcana": 71,
    "MetaX": 30,
    "MetaZoo": 66,
    "Munchkin": 53,
    "One Piece": 68,
    "Pokemon": 3,
    "Riftbound": 89,
    "Shadowverse Evolve": 73,
    "Sorcery Contested Realm": 77,
    "Star Wars Destiny": 26,
    "Star Wars Unlimited": 79,
    "Transformers": 57,
    "Union Arena": 81,
    "UniVersus": 25,
    "Warhammer Age of Sigmar Champions": 54,
    "Weiss Schwarz": 20,
    "Wixoss": 67,
    "World of Warcraft": 13,
    "Yugioh": 2,
    "Zombie World Order": 36,
}

DEFAULT_TCG_URLS = {tcg: [f'{BASE_URL}/{tcg_id}/groups'] for tcg, tcg_id in DEFAULT_TCG_IDS.items()}

def load_tcg_urls():
    try:
        with open('json/tcg_urls.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return DEFAULT_TCG_URLS

tcg_urls = load_tcg_urls()

# ------------------------------
# Download helpers
# ------------------------------
async def fetch_json(session, url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
        async with session.get(url, headers=headers) as resp:
            resp.raise_for_status()
            if 'json' in resp.headers.get('Content-Type', '').lower():
                return (await resp.json()).get('results', [])
    except Exception:
        return []

async def download_image(session, image_url, folder_path, image_name, skipped_image_ids, existing_images, semaphore):
    async with semaphore:
        image_number = re.search(r'\d+', image_name)
        if image_number:
            check_number = f"{image_number.group(0)}_200w"
            if check_number in skipped_image_ids:
                logger.info(f"Skipped (DB): {image_name}")
                return
            if image_name in existing_images:
                logger.info(f"Skipped (Exists): {image_name}")
                return

        image_path = os.path.join(folder_path, image_name)
        os.makedirs(folder_path, exist_ok=True)
        try:
            async with session.get(image_url) as response:
                response.raise_for_status()
                data = await response.read()
                async with aiofiles.open(image_path, 'wb') as f:
                    await f.write(data)
                logger.info(f"Downloaded: {image_name}")
        except Exception as e:
            logger.error(f"Error downloading {image_name}: {e}")

async def process_tcg(session, tcg_name, urls, skipped_image_ids):
    semaphore = asyncio.Semaphore(10)
    check_folder = os.path.join(CHECK_FOLDER, tcg_name)
    save_folder = os.path.join(SAVE_ROOT, tcg_name)
    os.makedirs(save_folder, exist_ok=True)

    existing_check_images = set(os.listdir(check_folder)) if os.path.exists(check_folder) else set()
    existing_save_images = set(os.listdir(save_folder)) if os.path.exists(save_folder) else set()
    existing_images = existing_check_images.union(existing_save_images)

    for url in tqdm(urls, desc=f"{tcg_name}: URLs", unit="url"):
        groups_data = await fetch_json(session, url)
        for group in tqdm(groups_data, desc=f"{tcg_name}: Groups", unit="group"):
            group_id = group.get('groupId')
            category_id = group.get('categoryId')
            if group_id and category_id:
                group_details = await fetch_json(session, f'{BASE_URL}/{category_id}/{group_id}/products')
                tasks = []
                for item in group_details:
                    image_url = item.get('imageUrl')
                    if image_url:
                        image_name = image_url.split('/')[-1]
                        tasks.append(download_image(session, image_url, save_folder, image_name, skipped_image_ids, existing_images, semaphore))
                await asyncio.gather(*tasks)

# ------------------------------
# Main
# ------------------------------
async def main():
    skipped_image_ids = load_skipped_image_ids(LANGUAGE_TYPE)
    async with aiohttp.ClientSession() as session:
        for tcg_name, urls in tqdm(tcg_urls.items(), desc="Processing TCGs", unit="tcg"):
            await process_tcg(session, tcg_name, urls, skipped_image_ids)

if __name__ == '__main__':
    asyncio.run(main())
