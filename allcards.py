import asyncio
import aiohttp
import logging
import os
import aiofiles
import re
from tqdm.asyncio import tqdm
from pymongo import MongoClient
from datetime import datetime
import json

# Create a log folder if it doesn't exist
log_folder = 'log'
if not os.path.exists(log_folder):
    os.makedirs(log_folder)

# Get today's date and time
now = datetime.now()
log_file_name = now.strftime('%Y-%m-%d_%H-%M-%S') + '.log'
log_file_path = os.path.join(log_folder, log_file_name)

# Set up logging
new_download_logger = logging.getLogger('new_downloads')
new_download_logger.setLevel(logging.INFO)

# Create a file handler
file_handler = logging.FileHandler(log_file_path)
file_handler.setLevel(logging.INFO)

# Create a console handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

# Create a formatter
formatter = logging.Formatter('%(message)s')
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

# Add the handlers to the logger
new_download_logger.addHandler(file_handler)
new_download_logger.addHandler(console_handler)

# Disable logging for the root logger
logging.getLogger().setLevel(logging.CRITICAL)

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
    "Grand Archive": 74,
    "Gundam": 86,
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

DEFAULT_TCG_URLS = {
    tcg: [f'{BASE_URL}/{tcg_id}/groups']
    for tcg, tcg_id in TCG_IDS.items()
}

# To use the Pokemon folder for both Pokemon and Pokemon Japan
for key, value in list(DEFAULT_TCG_URLS.items()):
    if key == "Pokemon Japan":
        DEFAULT_TCG_URLS["Pokemon"].extend(value)
        del DEFAULT_TCG_URLS["Pokemon Japan"]

def load_tcg_urls():
    """
    Load TCG URLs from a JSON file. If not found or invalid, fall back to defaults.
    """
    try:
        with open('json/tcg_urls.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return DEFAULT_TCG_URLS
    except json.JSONDecodeError as e:
        return DEFAULT_TCG_URLS

tcg_urls = load_tcg_urls()

async def fetch_and_parse_data(session, url, tcg_name):
    """
    Fetch and parse data from a given URL.
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/json',
            'Connection': 'keep-alive',
        }
        response = await session.get(url, headers=headers)
        response.raise_for_status()

        content_type = response.headers.get('Content-Type', '').lower()
        text = await response.text()

        if 'json' in content_type:
            return json.loads(text).get('results', [])
        else:
            return []
    except aiohttp.ClientError as e:
        return []

async def fetch_group_details(session, tcg_name, category_id, group_id):
    """
    Fetch details for a specific group.
    """
    url = f'https://tcgcsv.com/tcgplayer/{category_id}/{group_id}/products'
    return await fetch_and_parse_data(session, url, tcg_name)

async def download_image(session, image_url, folder_path, image_name, skipped_image_ids, semaphore):
    """
    Download an image if not in the skipped list and if it doesn't already exist.
    """
    async with semaphore:
        image_number = None
        match = re.search(r'\d+', image_name)
        if match:
            image_number = match.group(0)

        if image_number and image_number in skipped_image_ids:
            return

        try:
            image_path = os.path.join(folder_path, image_name)
            if os.path.exists(image_path):
                return  # already in "new" folder

            os.makedirs(folder_path, exist_ok=True)
            async with session.get(image_url) as response:
                response.raise_for_status()
                image_data = await response.read()
                async with aiofiles.open(image_path, 'wb') as image_file:
                    await image_file.write(image_data)
                new_download_logger.info(f"Downloaded {image_name} to {folder_path}")
        except Exception:
            pass

async def load_skipped_images(mongo_client):
    db = mongo_client['tcg_database']
    if'skipped_images' not in db.list_collection_names():
        db.create_collection('skipped_images')
    collection = db['skipped_images']
    pipeline = [
        {"$group": {"_id": None, "image_names": {"$push": "$image_name"}}}
    ]
    result = collection.aggregate(pipeline)
    skipped_image_ids = set()
    for document in result:
        for image_name in document.get('image_names', []):
            match = re.search(r'\d+', image_name)
            if match:
                skipped_image_ids.add(match.group(0))
    return skipped_image_ids

async def process_tcg(session, mongo_client, tcg_name, urls):
    """
    Process a specific TCG by fetching data and downloading images.
    """
    semaphore = asyncio.Semaphore(10)  # Limit to 10 concurrent downloads
    skipped_image_ids = await load_skipped_images(mongo_client)

    # 👇 check in the main folder, save only in the new folder
    check_folder = os.path.join("D:/Card Database",
                                tcg_name if tcg_name != "Magic the Gathering" else "Magic the Gathering")
    save_folder = os.path.join("G:/My Drive/New Cards",
                               tcg_name if tcg_name != "Magic the Gathering" else "Magic the Gathering")

    os.makedirs(save_folder, exist_ok=True)

    existing_image_names = set()
    if os.path.exists(check_folder):
        existing_image_names = set(os.listdir(check_folder))

    for url in tqdm(urls, desc=f"{tcg_name}: URLs", unit="url"):
        groups_data = await fetch_and_parse_data(session, url, tcg_name)

        for group in tqdm(groups_data, desc=f"{tcg_name}: Groups", unit="group"):
            group_id = group.get('groupId')
            category_id = group.get('categoryId')
            if group_id and category_id:
                group_details = await fetch_group_details(session, tcg_name, category_id, group_id)
                if group_details:
                    # Concurrently download images
                    download_tasks = []
                    for item in group_details:
                        image_url = item.get('imageUrl')
                        if image_url:
                            image_name = image_url.split('/')[-1]

                            # 👇 Skip if image already exists in main folder
                            if image_name in existing_image_names:
                                continue

                            download_tasks.append(
                                download_image(session, image_url, save_folder, image_name, skipped_image_ids, semaphore)
                            )
                    await asyncio.gather(*download_tasks)

async def main():
    # MongoDB Compass connection string
    MONGO_URI = "mongodb+srv://seeyaflying:Riversong1969@cluster0.7fugd.mongodb.net/"
    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client['tcg_database']  # Access the database directly

    async with aiohttp.ClientSession() as session:
        for tcg_name, urls in tqdm(tcg_urls.items(), desc="Processing TCGs", unit="tcg"):
            await process_tcg(session, mongo_client, tcg_name, urls)

if __name__ == '__main__':
    asyncio.run(main())