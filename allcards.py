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

# --- CONFIGURATION ---
DB_FILE = "skipped_images.sqlite"
TABLE_NAME = "skipped_images"
LANGUAGE_TYPE = "english"
SAVE_ROOT = "G:/My Drive/New Cards"
CHECK_ROOT = "G:/My Drive/Card Database"
LOG_FOLDER = "log"

os.makedirs(LOG_FOLDER, exist_ok=True)

# --- LOGGING SETUP ---
log_file_path = os.path.join(LOG_FOLDER, datetime.now().strftime('%Y-%m-%d_%H-%M-%S') + '.log')
logging.basicConfig(level=logging.INFO, format='%(message)s',
                    handlers=[logging.FileHandler(log_file_path), logging.StreamHandler()])
logger = logging.getLogger("downloader")

TCG_IDS = {
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


# --- DATABASE HELPERS ---
def load_skipped_image_ids(tcg_name):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        # READ ONLY: Checks for IDs banned for this specific game
        cursor.execute(f"SELECT image_name FROM {TABLE_NAME} WHERE language=? AND game_name=?",
                       (LANGUAGE_TYPE, tcg_name))
        result = {str(row[0]) for row in cursor.fetchall()}
        conn.close()
        return result
    except Exception as e:
        logger.error(f"Failed to read DB for {tcg_name}: {e}")
        return set()


# --- ASYNC CORE LOGIC ---
async def fetch_json(session, url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
        async with session.get(url, headers=headers, timeout=15) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get('results', [])
    except:
        return []
    return []


async def download_image(session, image_url, save_folder, image_name, skipped_ids, existing_filenames, semaphore):
    async with semaphore:
        # Check against DB skips
        id_match = re.search(r'(\d+)', image_name)
        if id_match:
            img_id = id_match.group(1)
            if img_id in skipped_ids or f"{img_id}_200w" in skipped_ids:
                return

        # Check against physical files
        if image_name in existing_filenames:
            return

        image_path = os.path.join(save_folder, image_name)
        try:
            async with session.get(image_url, timeout=20) as response:
                if response.status == 200:
                    data = await response.read()
                    async with aiofiles.open(image_path, 'wb') as f:
                        await f.write(data)
                    existing_filenames.add(image_name)
                    logger.info(f"Downloaded: {image_name}")
        except:
            pass


async def process_tcg(session, tcg_name, tcg_id):
    skipped_ids = load_skipped_image_ids(tcg_name)
    save_dir = os.path.join(SAVE_ROOT, tcg_name)
    check_dir = os.path.join(CHECK_ROOT, tcg_name)
    os.makedirs(save_dir, exist_ok=True)

    existing_files = set()
    for path in [save_dir, check_dir]:
        if os.path.exists(path): existing_files.update(os.listdir(path))

    semaphore = asyncio.Semaphore(15)
    api_url = f'https://tcgcsv.com/tcgplayer/{tcg_id}/groups'
    groups_data = await fetch_json(session, api_url)

    for group in tqdm(groups_data, desc=f" {tcg_name}", leave=False):
        group_id = group.get('groupId')
        if not group_id: continue
        products = await fetch_json(session, f'https://tcgcsv.com/tcgplayer/{tcg_id}/{group_id}/products')
        tasks = []
        for item in products:
            img_url = item.get('imageUrl')
            if img_url:
                img_name = img_url.split('/')[-1]
                tasks.append(
                    download_image(session, img_url, save_dir, img_name, skipped_ids, existing_files, semaphore))
        if tasks: await asyncio.gather(*tasks)


async def main_async():
    async with aiohttp.ClientSession() as session:
        for tcg_name, tcg_id in tqdm(TCG_IDS.items(), desc="Overall Progress"):
            await process_tcg(session, tcg_name, tcg_id)


if __name__ == '__main__':
    try:
        asyncio.run(main_async())
        print("\nSUCCESS: Processing complete.")
    except Exception:
        traceback.print_exc()
    finally:
        input("\nPress [Enter] to return to manager...")