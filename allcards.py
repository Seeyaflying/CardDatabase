import asyncio
import aiohttp
import logging
import json
import os
import aiofiles
import csv
import re
from tqdm.asyncio import tqdm

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Default TCG URLs if JSON file is not found or invalid
DEFAULT_TCG_URLS = {
    'Akora': ['https://tcgcsv.com/tcgplayer/75/groups'],
    "Alpha Clash": ["https://tcgcsv.com/tcgplayer/78/groups"],
    'Argent Saga': ['https://tcgcsv.com/tcgplayer/61/groups'],
    'Bakugan': ['https://tcgcsv.com/tcgplayer/58/groups'],
    'Battle Spirits Saga': ['https://tcgcsv.com/tcgplayer/72/groups'],
    'Cardfight Vanguard': ['https://tcgcsv.com/tcgplayer/16/groups'],
    'Caster Chronicles': ["https://tcgcsv.com/tcgplayer/37/groups"],
    "Chrono Clash System":["https://tcgcsv.com/tcgplayer/60/groups"],
    "Dice Masters": ["https://tcgcsv.com/tcgplayer/18/groups"],
    "Digimon": ["https://tcgcsv.com/tcgplayer/63/groups"],
    "DBZ TCG": ["https://tcgcsv.com/tcgplayer/23/groups"],
    "DBZ Super": ["https://tcgcsv.com/tcgplayer/27/groups"],
    "DBZ Super Fusion World": ["https://tcgcsv.com/tcgplayer/80/groups"],
    "Dragoborne": ["https://tcgcsv.com/tcgplayer/28/groups"],
    "Elestrals": ["https://tcgcsv.com/tcgplayer/83/groups"],
    "Exodus": ["https://tcgcsv.com/tcgplayer/40/groups"],
    "Final Fantasy": ["https://tcgcsv.com/tcgplayer/24/groups"],
    "Flesh and Blood": ["https://tcgcsv.com/tcgplayer/62/groups"],
    "Force of Will": ["https://tcgcsv.com/tcgplayer/17/groups"],
    "Future Card BuddyFight": ["https://tcgcsv.com/tcgplayer/19/groups"],
    "Gate Ruler": ["https://tcgcsv.com/tcgplayer/65/groups"],
    "Grand Archive": ["https://tcgcsv.com/tcgplayer/74/groups"],
    "Gundam": ["https://tcgcsv.com/tcgplayer/86/groups"],
    "Kryptik": ["https://tcgcsv.com/tcgplayer/76/groups"],
    "Lightseekers": ["https://tcgcsv.com/tcgplayer/48/groups"],
    "Lorcana": ["https://tcgcsv.com/tcgplayer/71/groups"],
    "Magic the Gathering": ["https://tcgcsv.com/tcgplayer/1/groups"],
    "MetaX": ["https://tcgcsv.com/tcgplayer/30/groups"],
    "MetaZoo": ["https://tcgcsv.com/tcgplayer/66/groups"],
    "Munchkin": ["https://tcgcsv.com/tcgplayer/53/groups"],
    "One Piece": ["https://tcgcsv.com/tcgplayer/68/groups"],
    "Pokemon": ["https://tcgcsv.com/tcgplayer/3/groups"],
    "Pokemon Japan": ["https://tcgcsv.com/tcgplayer/85/groups"],
    "Shadowverse Evolve": ["https://tcgcsv.com/tcgplayer/73/groups"],
    "Sorcery Contested Realm": ["https://tcgcsv.com/tcgplayer/77/groups"],
    "Star Wars Destiny": ["https://tcgcsv.com/tcgplayer/26/groups"],
    "Star Wars Unlimited": ["https://tcgcsv.com/tcgplayer/79/groups"],
    "Transformers": ["https://tcgcsv.com/tcgplayer/57/groups"],
    "Union Arena": ["https://tcgcsv.com/tcgplayer/81/groups"],
    "UniVersus": ["https://tcgcsv.com/tcgplayer/25/groups"],
    "Warhammer Age of Sigmar Champions": ["https://tcgcsv.com/tcgplayer/54/groups"],
    "Weiss Schwarz": ["https://tcgcsv.com/tcgplayer/20/groups"],
    "Wixoss": ["https://tcgcsv.com/tcgplayer/67/groups"],
    "World of Warcraft": ["https://tcgcsv.com/tcgplayer/13/groups"],
    "Yugioh": ["https://tcgcsv.com/tcgplayer/2/groups"],
    "Zombie World Order": ["https://tcgcsv.com/tcgplayer/36/groups"]
    # Add other TCGs as needed...
}

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
        match = re.search(r'\d+', image_name)
        image_number = match.group(0) if match else None

        if image_number and image_number in skipped_image_ids:
            #logger.info(f"Skipping download for {image_name} (image number {image_number} is in skipped list).")
            return

        try:
            image_path = os.path.join(folder_path, image_name)
            if os.path.exists(image_path):
                #logger.info(f"Image {image_name} already exists. Skipping download.")
                return

            os.makedirs(folder_path, exist_ok=True)
            async with session.get(image_url) as response:
                response.raise_for_status()
                image_data = await response.read()
                async with aiofiles.open(image_path, 'wb') as image_file:
                    await image_file.write(image_data)
                logger.info(f"Downloaded {image_name} to {folder_path}")
        except Exception as e:
            #logger.error(f"Error downloading image from {image_url}: {e}")
            pass

def load_skipped_images(tcg_name):
    skipped_image_ids = set()
    skipped_csv_file = os.path.join('json', tcg_name,'skipped.csv')

    os.makedirs(os.path.dirname(skipped_csv_file), exist_ok=True)

    if not os.path.exists(skipped_csv_file):
        with open(skipped_csv_file, 'w', encoding='utf-8', newline='') as skipped_file:
            writer = csv.writer(skipped_file)
            writer.writerow(['image_number'])
        logger.info(f"Created skipped.csv for {tcg_name} at {skipped_csv_file}")
    else:
        with open(skipped_csv_file, 'r', encoding='utf-8') as skipped_file:
            skipped_csv_reader = csv.reader(skipped_file)
            next(skipped_csv_reader, None)
            for row in skipped_csv_reader:
                if not row or not row[0].strip():
                    continue
                skipped_image_ids.add(row[0].strip())

    return skipped_image_ids

async def process_tcg(session, tcg_name, urls, all_data):
    """
    Process a specific TCG by fetching data and downloading images.
    """
    logger.info(f"Processing TCG: {tcg_name}")
    tcg_folder = os.path.join('G:/My Drive/Card Database',
                              tcg_name if tcg_name != "Magic the Gathering" else "Magic the Gathering")
    os.makedirs(tcg_folder, exist_ok=True)

    skipped_image_ids = load_skipped_images(tcg_name)

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
    all_data = []

    async with aiohttp.ClientSession() as session:
        with tqdm(total=len(tcg_urls), desc="Processing TCGs", unit="tcg") as tcg_bar:
            for tcg_name, urls in tcg_urls.items():
                await process_tcg(session, tcg_name, urls, all_data)
                tcg_bar.update(1)

    try:
        with open('json/all_tcg_data.json', 'w', encoding='utf-8') as json_file:
            json.dump(all_data, json_file, ensure_ascii=False, indent=4)
        logger.info("Saved all TCG data to all_tcg_data.json")
    except Exception as e:
        logger.error(f"Error saving all TCG data: {e}")

if __name__ == '__main__':
    asyncio.run(main())
