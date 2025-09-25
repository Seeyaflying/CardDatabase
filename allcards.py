import asyncio
import aiohttp
import logging
import os
import aiofiles
import re
from tqdm.asyncio import tqdm
from datetime import datetime
import json
import sqlite3  # ✅ SQLite instead of MongoDB

# Create a log folder if it doesn't exist
log_folder = 'log'
os.makedirs(log_folder, exist_ok=True)

# Get today's date and time
now = datetime.now()
log_file_name = now.strftime('%Y-%m-%d_%H-%M-%S') + '.log'
log_file_path = os.path.join(log_folder, log_file_name)

# Set up logging
new_download_logger = logging.getLogger('new_downloads')
new_download_logger.setLevel(logging.INFO)
file_handler = logging.FileHandler(log_file_path)
file_handler.setLevel(logging.INFO)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(message)s')
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)
new_download_logger.addHandler(file_handler)
new_download_logger.addHandler(console_handler)
logging.getLogger().setLevel(logging.CRITICAL)

# SQLite database setup
DB_FILE = "skipped_images.sqlite"
TABLE_NAME = "skipped_images"

def init_db():
    """Create the SQLite database and table if they don't exist."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image_name TEXT UNIQUE
        )
    """)
    conn.commit()
    conn.close()

def load_skipped_image_ids():
    """Load skipped image IDs from SQLite and print how many were loaded."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(f"SELECT image_name FROM {TABLE_NAME}")
    rows = cursor.fetchall()
    conn.close()

    skipped_image_ids = set()
    for row in rows:
        match = re.search(r'\d+', row[0])
        if match:
            skipped_image_ids.add(match.group(0))

    print(f"Skipped image IDs loaded from database: {len(skipped_image_ids)}")
    return skipped_image_ids

# Base URLs and TCG IDs
BASE_URL = 'https://tcgcsv.com/tcgplayer'
TCG_IDS = {
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
    "Magic the Gathering": 1,
    "MetaX": 30,
    "MetaZoo": 66,
    "Munchkin": 53,
    "One Piece": 68,
    "Pokemon": 3,
    "Pokemon Japan": 85,
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

DEFAULT_TCG_URLS = {tcg: [f'{BASE_URL}/{tcg_id}/groups'] for tcg, tcg_id in TCG_IDS.items()}
for key, value in list(DEFAULT_TCG_URLS.items()):
    if key == "Pokemon Japan":
        DEFAULT_TCG_URLS["Pokemon"].extend(value)
        del DEFAULT_TCG_URLS["Pokemon Japan"]

def load_tcg_urls():
    try:
        with open('json/tcg_urls.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return DEFAULT_TCG_URLS

tcg_urls = load_tcg_urls()

async def fetch_and_parse_data(session, url, tcg_name):
    try:
        headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json', 'Connection': 'keep-alive'}
        response = await session.get(url, headers=headers)
        response.raise_for_status()
        text = await response.text()
        if 'json' in response.headers.get('Content-Type', '').lower():
            return json.loads(text).get('results', [])
        return []
    except aiohttp.ClientError:
        return []

async def fetch_group_details(session, tcg_name, category_id, group_id):
    url = f'https://tcgcsv.com/tcgplayer/{category_id}/{group_id}/products'
    return await fetch_and_parse_data(session, url, tcg_name)

async def download_image(session, image_url, folder_path, image_name, skipped_image_ids, semaphore):
    async with semaphore:
        image_number = re.search(r'\d+', image_name)
        if image_number and image_number.group(0) in skipped_image_ids:
            return

        image_path = os.path.join(folder_path, image_name)
        if os.path.exists(image_path):
            return

        os.makedirs(folder_path, exist_ok=True)
        try:
            async with session.get(image_url) as response:
                response.raise_for_status()
                image_data = await response.read()
                async with aiofiles.open(image_path, 'wb') as image_file:
                    await image_file.write(image_data)
                new_download_logger.info(f"Downloaded {image_name} to {folder_path}")
        except Exception:
            pass

async def process_tcg(session, tcg_name, urls):
    semaphore = asyncio.Semaphore(10)
    skipped_image_ids = load_skipped_image_ids()

    check_folder = os.path.join("D:/Card Database", tcg_name)
    save_folder = os.path.join("G:/My Drive/New Cards", tcg_name)
    os.makedirs(save_folder, exist_ok=True)

    existing_image_names = set(os.listdir(check_folder)) if os.path.exists(check_folder) else set()

    for url in tqdm(urls, desc=f"{tcg_name}: URLs", unit="url"):
        groups_data = await fetch_and_parse_data(session, url, tcg_name)
        for group in tqdm(groups_data, desc=f"{tcg_name}: Groups", unit="group"):
            group_id = group.get('groupId')
            category_id = group.get('categoryId')
            if group_id and category_id:
                group_details = await fetch_group_details(session, tcg_name, category_id, group_id)
                if group_details:
                    tasks = []
                    for item in group_details:
                        image_url = item.get('imageUrl')
                        if image_url:
                            image_name = image_url.split('/')[-1]
                            if image_name in existing_image_names:
                                continue
                            tasks.append(download_image(session, image_url, save_folder, image_name, skipped_image_ids, semaphore))
                    await asyncio.gather(*tasks)

async def main():
    init_db()  # ✅ Initialize SQLite
    async with aiohttp.ClientSession() as session:
        for tcg_name, urls in tqdm(tcg_urls.items(), desc="Processing TCGs", unit="tcg"):
            await process_tcg(session, tcg_name, urls)

if __name__ == '__main__':
    asyncio.run(main())