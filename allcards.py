import asyncio
import aiohttp
import logging
import json
import os
import aiofiles
import csv
import re
from tqdm.asyncio import tqdm
from pymongo import MongoClient

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

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
            logger.info("Loaded TCG URLs from tcg_urls.json")
            return json.load(f)
    except FileNotFoundError:
        logger.warning("tcg_urls.json not found. Using default TCG URLs.")
        return DEFAULT_TCG_URLS
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding tcg_urls.json: {e}")
        return DEFAULT_TCG_URLS

tcg_urls = load_tcg_urls()

def parse_json_data(text):
    """
    Parse JSON data from a text response.
    """
    try:
        parsed_json = json.loads(text)
        return parsed_json.get('results', [])
    except Exception as e:
        logger.error(f"Error parsing JSON data: {e}")
        return []

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
        logger.debug(f"Fetching data from {url} for {tcg_name}...")
        response = await session.get(url, headers=headers)
        response.raise_for_status()

        content_type = response.headers.get('Content-Type', '').lower()
        text = await response.text()

        if 'json' in content_type:
            return parse_json_data(text)
        else:
            logger.error(f"Unsupported content type: {content_type} for {url}")
            return []
    except aiohttp.ClientError as e:
        logger.error(f"Error fetching data from {url} for {tcg_name}: {e}")
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
            logger.info(f"Skipping download for {image_name} (image number {image_number} is in skipped list).")
            return

        try:
            image_path = os.path.join(folder_path, image_name)
            if os.path.exists(image_path):
                logger.info(f"Image {image_name} already exists. Skipping download.")
                return

            os.makedirs(folder_path, exist_ok=True)
            async with session.get(image_url) as response:
                response.raise_for_status()
                image_data = await response.read()
                async with aiofiles.open(image_path, 'wb') as image_file:
                    await image_file.write(image_data)
                logger.info(f"Downloaded {image_name} to {folder_path}")
        except Exception as e:
            logger.error(f"Error downloading image from {image_url}: {e}")
            pass

async def load_skipped_images(mongo_client):
    db = mongo_client['tcg_database']
    if'skipped_images' not in db.list_collection_names():
        db.create_collection('skipped_images')
        logger.info('Created skipped_images collection in MongoDB')
    collection = db['skipped_images']
    skipped_image_ids = set()
    for document in collection.find():
        image_name = document.get('image_name', '')
        match = re.search(r'\d+', image_name)
        if match:
            skipped_image_ids.add(match.group(0))
    return skipped_image_ids

async def process_tcg(session, mongo_client, tcg_name, urls, all_data):
    """
    Process a specific TCG by fetching data and downloading images.
    """
    logger.info(f"Processing TCG: {tcg_name}")
    tcg_folder = os.path.join('G:/My Drive/Card Database',
                              tcg_name if tcg_name!= "Magic the Gathering" else "Magic the Gathering")
    os.makedirs(tcg_folder, exist_ok=True)

    skipped_image_ids = await load_skipped_images(mongo_client)

    semaphore = asyncio.Semaphore(10)  # Limit to 10 concurrent downloads

    with tqdm(total=len(urls), desc=f"{tcg_name}: URLs", unit="url") as url_bar:
        for url in urls:
            groups_data = await fetch_and_parse_data(session, url, tcg_name)

            if groups_data:
                all_data.append({'tcg_name': tcg_name, 'groups': groups_data})

                with tqdm(total=len(groups_data), desc=f"{tcg_name}: Groups", unit="group") as group_bar:
                    for group in groups_data:
                        group_id = group.get('groupId')
                        category_id = group.get('categoryId')
                        if group_id and category_id:
                            group_details = await fetch_group_details(session, tcg_name, category_id, group_id)
                            if group_details:
                                all_data[-1].setdefault('group_details', []).append({
                                    'group_id': group_id,
                                    'details': group_details
                                })

                                # Concurrently download images
                                download_tasks = []
                                for item in group_details:
                                    image_url = item.get('imageUrl')
                                    if image_url:
                                        image_name = image_url.split('/')[-1]
                                        download_tasks.append(
                                            download_image(session, image_url, tcg_folder, image_name, skipped_image_ids, semaphore)
                                        )
                                await asyncio.gather(*download_tasks)

                        group_bar.update(1)
            url_bar.update(1)

    tcg_json_file = os.path.join('json', tcg_name, f'{tcg_name}.json')
    try:
        os.makedirs(os.path.dirname(tcg_json_file), exist_ok=True)
        with open(tcg_json_file, 'w', encoding='utf-8') as json_file:
            json.dump(all_data, json_file, ensure_ascii=False, indent=4)
        logger.info(f"Saved {tcg_name} data to {tcg_json_file}")
    except Exception as e:
        logger.error(f"Error saving {tcg_name} data to JSON: {e}")

async def main():
    # MongoDB Compass connection string
    MONGO_URI = "mongodb+srv://seeyaflying:Riversong1969@cluster0.7fugd.mongodb.net/"
    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client['tcg_database']  # Access the database directly
    all_data = []

    async with aiohttp.ClientSession() as session:
        with tqdm(total=len(tcg_urls), desc="Processing TCGs", unit="tcg") as tcg_bar:
            for tcg_name, urls in tcg_urls.items():
                await process_tcg(session, mongo_client, tcg_name, urls, all_data)
                tcg_bar.update(1)

    try:
        with open('json/all_tcg_data.json', 'w', encoding='utf-8') as json_file:
            json.dump(all_data, json_file, ensure_ascii=False, indent=4)
        logger.info("Saved all TCG data to all_tcg_data.json")
    except Exception as e:
        logger.error(f"Error saving all TCG data: {e}")

if __name__ == '__main__':
    asyncio.run(main())