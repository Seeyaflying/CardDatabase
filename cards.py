#!/usr/bin/env python
# coding: utf-8

# # Unified TCG Image Scraper Notebook
# 
# 
# This notebook contains two TCG scrapers:
# 1. Async TCG scraper (main sets)
# 2. Selenium scraper (Japan / TCG Republic)
# 
# 
# Both scrapers share a single SQLite database with two tables for skipped images.

# # Imports

# In[1]:


import asyncio
import aiohttp
import aiofiles
import re
from tqdm import tqdm
import json
import os
import time
import requests
import logging
from datetime import datetime, date
from selenium.webdriver.common.by import By
from selenium import webdriver
from selenium.webdriver.firefox.service import Service as FirefoxService
from webdriver_manager.firefox import GeckoDriverManager
from concurrent.futures import ThreadPoolExecutor
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import sqlite3


# # Logging Setup

# In[2]:


log_folder = 'log'
os.makedirs(log_folder, exist_ok=True)
now = datetime.now()
log_file_name = now.strftime('%Y-%m-%d_%H-%M-%S') + '.log'
log_file_path = os.path.join(log_folder, log_file_name)

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


# # SQL Database

# In[3]:


DB_FILE = 'skipped_images.sqlite'
REGULAR_TABLE = 'skipped_images'
JAP_TABLE = 'jap_skipped_images'

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(f'CREATE TABLE IF NOT EXISTS {REGULAR_TABLE} (id INTEGER PRIMARY KEY AUTOINCREMENT, image_name TEXT UNIQUE)')
    cursor.execute(f'CREATE TABLE IF NOT EXISTS {JAP_TABLE} (id INTEGER PRIMARY KEY AUTOINCREMENT, image_name TEXT UNIQUE)')
    conn.commit()
    conn.close()

def load_skipped_image_ids(table_name):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(f'SELECT image_name FROM {table_name}')
    rows = cursor.fetchall()
    conn.close()
    return {row[0] for row in rows}

def display_skipped_counts():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute(f"SELECT COUNT(*) FROM {REGULAR_TABLE}")
    regular_count = cursor.fetchone()[0]

    cursor.execute(f"SELECT COUNT(*) FROM {JAP_TABLE}")
    jap_count = cursor.fetchone()[0]

    conn.close()

    print(f"Skipped images in '{REGULAR_TABLE}': {regular_count}")
    print(f"Skipped images in '{JAP_TABLE}': {jap_count}")

# Call this before any scraper starts
display_skipped_counts()


# # English Scraper

# In[4]:
BASE_URL = 'https://tcgcsv.com/tcgplayer'
REGULAR_TABLE = "skipped_images"  # Table or JSON with skipped image IDs

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

# ---------- LOAD SAVED URLS ----------
def load_tcg_urls():
    try:
        with open('json/tcg_urls.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return DEFAULT_TCG_URLS

tcg_urls = load_tcg_urls()

# ---------- HELPER FUNCTIONS ----------
def load_skipped_image_ids(table_name):
    """
    Load skipped image IDs from a JSON file or database.
    Returns a set of strings.
    """
    try:
        with open(f'json/{table_name}.json', 'r', encoding='utf-8') as f:
            return set(json.load(f))
    except Exception:
        return set()

async def fetch_and_parse_data(session, url, tcg_name):
    """
    Fetch JSON data from a URL and parse it.
    """
    try:
        headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
        async with session.get(url, headers=headers) as response:
            response.raise_for_status()
            text = await response.text()
            if 'json' in response.headers.get('Content-Type', '').lower():
                return json.loads(text).get('results', [])
        return []
    except Exception as e:
        print(f"[ERROR] Failed to fetch {url} for {tcg_name}: {e}")
        return []

async def download_image(session, image_url, folder_path, image_name, skipped_image_ids, existing_image_names, semaphore):
    """
    Download a single image if it doesn't exist in main folder, skipped DB, or new folder.
    Only prints when actually downloaded into the new folder.
    """
    async with semaphore:
        # Skip images in skipped database
        image_number_match = re.search(r'\d+', image_name)
        if image_number_match and image_number_match.group(0) in skipped_image_ids:
            print(f"[SKIPPED] {image_name} is in skipped database")
            return

        # Skip images in the main folder
        if image_name in existing_image_names:
            print(f"[SKIPPED] {image_name} already exists in the main folder")
            return

        # Skip images already in the new folder
        new_image_path = os.path.join(folder_path, image_name)
        if os.path.exists(new_image_path):
            print(f"[SKIPPED] {image_name} already exists in the new folder")
            return

        # Actually download the image
        os.makedirs(folder_path, exist_ok=True)
        try:
            async with session.get(image_url) as response:
                response.raise_for_status()
                data = await response.read()
                async with aiofiles.open(new_image_path, 'wb') as f:
                    await f.write(data)
                print(f"[INFO] Downloaded {image_name} to {folder_path}")
        except Exception as e:
            print(f"[ERROR] Failed to download {image_url}: {e}")

# ---------- PROCESS SINGLE TCG ----------
async def process_tcg(session, tcg_name, urls):
    """
    Process all URLs for a single TCG.
    """
    semaphore = asyncio.Semaphore(10)
    skipped_image_ids = load_skipped_image_ids(REGULAR_TABLE)

    check_folder = os.path.join("D:/Card Database", tcg_name)
    save_folder = os.path.join("G:/My Drive/New Cards", tcg_name)
    os.makedirs(save_folder, exist_ok=True)

    existing_image_names = set(os.listdir(check_folder)) if os.path.exists(check_folder) else set()

    for url in tqdm(urls, desc=f'{tcg_name}: URLs'):
        groups = await fetch_and_parse_data(session, url, tcg_name)
        for group in groups:
            group_id = group.get('groupId')
            category_id = group.get('categoryId')
            if group_id and category_id:
                url2 = f'{BASE_URL}/{category_id}/{group_id}/products'
                items = await fetch_and_parse_data(session, url2, tcg_name)
                tasks = []
                for item in items:
                    if 'imageUrl' in item:
                        image_name = item['imageUrl'].split('/')[-1]
                        if image_name in existing_image_names:
                            continue
                        tasks.append(
                            download_image(
                                session,
                                item['imageUrl'],
                                save_folder,
                                image_name,
                                skipped_image_ids,
                                existing_image_names,
                                semaphore
                            )
                        )
                await asyncio.gather(*tasks)

# ---------- MAIN ASYNC RUNNER ----------
async def run_async_scraper():
    """
    Run the scraper for all TCGs.
    """
    skipped_image_ids = load_skipped_image_ids(REGULAR_TABLE)
    print(f"Starting Async TCG Scraper. Skipped images: {len(skipped_image_ids)}")

    async with aiohttp.ClientSession() as session:
        for tcg_name, urls in tqdm(tcg_urls.items(), desc="Processing TCGs"):
            await process_tcg(session, tcg_name, urls)

# ---------- ENTRY POINT ----------
if __name__ == "__main__":
    asyncio.run(run_async_scraper())

# # Japanese Scraper

# In[5]:


BASE_URL_PATTERN = 'https://tcgrepublic.com/category/category_page_{}.html'
IMAGE_PATTERN = re.compile(r'https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg')

SITES = {
    "Battle Spirits": {"id": 79, "total_pages": 145},
    "Buddy Fight": {"id": 71, "total_pages": 233},
    "Build Divide": {"id": 61, "total_pages": 176},
    "Cardfight Vanguard": {"id": 44, "total_pages": 554},
    "Chaos": {"id": 50, "total_pages": 433},
    "Detective Conan": {"id": 84, "total_pages": 26},
    "DB Heroes": {"id": 73, "total_pages": 202},
    "DB Super Divers": {"id": 93, "total_pages": 13},
    "DBZ Super Fusion World": {"id": 82, "total_pages": 29},
    "Digimon": {"id": 37, "total_pages": 118},
    "Duel Masters": {"id": 36, "total_pages": 464},
    "Fate-Grand Order Arcade": {"id": 39, "total_pages": 42},
    "Final Fantasy": {"id": 56, "total_pages": 233},
    "Fire Emblem Cipher": {"id": 33, "total_pages": 74},
    "Godzilla Card Game": {"id": 99, "total_pages":5},
    "Gundam": {"id": 94, "total_pages": 10},
    "Hololive": {"id": 88, "total_pages": 29},
    "Kamen Rider Battle Ganba Legends": {"id": 86, "total_pages": 28},
    "Kamen Rider Battle Ganbarizing": {"id": 85, "total_pages": 99},
    "Kantai Collection Kancolle Arcade": {"id": 60, "total_pages": 1},
    "Love Live": {"id": 95, "total_pages": 23},
    "Lycee Over Ture": {"id": 48, "total_pages": 185},
    "One Piece": {"id": 67, "total_pages": 88},
    "Osica": {"id": 68, "total_pages": 68},
    "Pokemon": {"id": 35, "total_pages": 629},
    "Precious Memories": {"id": 41, "total_pages": 416},
    "Prism Connect": {"id": 59, "total_pages": 89},
    "Rebirth for you": {"id": 38, "total_pages": 402},
    "Shadowverse Evolve": {"id": 62, "total_pages": 110},
    "Takashi Murakami Jellyfish Eyes": {"id": 91, "total_pages": 3},
    "The Quintessential Quintuplets": {"id": 87, "total_pages": 20},
    "Trails Series": {"id": 92, "total_pages": 8},
    "Ultraman": {"id": 90, "total_pages": 14},
    "Union Arena": {"id": 74, "total_pages": 166},
    "Vividz": {"id": 70, "total_pages": 12},
    "Weiss Schwarz": {"id": 31, "total_pages": 1324},
    "Weiss Schwarz Blau": {"id": 72, "total_pages": 97},
    "Weiss Schwarz Rose": {"id": 96, "total_pages": 22},
    "Wixoss": {"id": 43, "total_pages": 344},
    "Xross Stars": {"id": 98, "total_pages": 5},
    "Yugioh": {"id": 34, "total_pages": 797},
    "Yugioh Rush Duel": {"id": 49, "total_pages": 116},
    "Z-X Zillions over enemy X": {"id": 42, "total_pages": 441},
}

# Selenium setup
def setup_driver():
    options = webdriver.FirefoxOptions()
    options.add_argument('--headless')
    return webdriver.Firefox(service=FirefoxService(GeckoDriverManager().install()), options=options)

def scrape_page(driver, site_data, page):
    image_urls = set()
    url = f'{BASE_URL_PATTERN.format(site_data["id"])}?p={page}'
    driver.get(url)
    time.sleep(1)
    for img in driver.find_elements(By.TAG_NAME, 'img'):
        src = img.get_attribute('src')
        if src and IMAGE_PATTERN.match(src):
            image_urls.add(src.replace('.l2_thumbnail.jpg',''))
    return image_urls

def scrape_images(site_data):
    driver = setup_driver()
    image_urls = set()
    for page in tqdm(range(1, site_data['total_pages']+1), desc=f'Scraping pages'):
        image_urls.update(scrape_page(driver, site_data, page))
    driver.quit()
    return image_urls

# Download function with check folder
def download_image_sync(url, skipped_image_ids, check_folder, save_folder):
    """
    Download image synchronously.
    Skips images if they exist in skipped DB, main folder, or new folder.
    Prints debug info for skipped or downloaded images.
    """
    image_name = url.split('/')[-1]

    # Load existing images in main folder
    existing_main = set(os.listdir(check_folder)) if os.path.exists(check_folder) else set()

    # Skip if in skipped database
    if image_name in skipped_image_ids:
        print(f"[SKIPPED] {image_name} is in skipped database")
        return

    # Skip if in main folder
    if image_name in existing_main:
        print(f"[SKIPPED] {image_name} already exists in main folder")
        return

    # Skip if already in new folder
    new_image_path = os.path.join(save_folder, image_name)
    if os.path.exists(new_image_path):
        print(f"[SKIPPED] {image_name} already exists in new folder")
        return

    # Download image
    os.makedirs(save_folder, exist_ok=True)
    try:
        session = requests.Session()
        retry = Retry(total=5, backoff_factor=1)
        session.mount('https://', HTTPAdapter(max_retries=retry))
        response = session.get(url, stream=True, timeout=5)
        if response.status_code == 200:
            with open(new_image_path, 'wb') as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)
            print(f"[INFO] Downloaded {image_name} to {save_folder}")
    except Exception as e:
        print(f"[ERROR] Failed to download {url}: {e}")

def run_selenium_scraper():
    init_db()
    skipped_image_ids = load_skipped_image_ids(JAP_TABLE)
    print(f"Starting Selenium Japan Scraper. Skipped images already in database: {len(skipped_image_ids)}")

    for site_name, site_data in SITES.items():
        urls = scrape_images(site_data)
        check_folder = os.path.join("D:/Card Database", site_name)  # Main folder
        save_folder = os.path.join('G:/My Drive/New Cards', site_name)  # New folder

        for url in tqdm(urls, desc=f'{site_name} downloads'):
            download_image_sync(url, skipped_image_ids, check_folder, save_folder)


run_selenium_scraper() # Japanese

