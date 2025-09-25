import os
import csv
import re
import time
import requests
import sqlite3
from selenium.webdriver.common.by import By
from selenium import webdriver
from selenium.webdriver.firefox.service import Service as FirefoxService
from webdriver_manager.firefox import GeckoDriverManager
from concurrent.futures import ThreadPoolExecutor
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from tqdm import tqdm
import logging
from datetime import date

# --- Paths ---
DB_FILE = "skipped_images.sqlite"
TABLE_NAME = "jap_skipped_images"
LOG_DIR = "log"
CSV_DIR = "json"

# Ensure folders exist
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(CSV_DIR, exist_ok=True)

# --- Logging ---
today = date.today()
log_filename = os.path.join(LOG_DIR, f"{today.strftime('%Y-%m-%d')}_image_scraper.log")

logger = logging.getLogger("image_scraper")
logger.setLevel(logging.INFO)
if not logger.handlers:  # prevent duplicate handlers
    handler = logging.FileHandler(log_filename, encoding="utf-8")
    handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)

# --- SITES (all restored) ---
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
    "Godzilla Card Game": {"id": 99, "total_pages": 5},
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

# --- SQL SETUP ---
def init_db():
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

def read_skipped_image_ids():
    skipped_image_ids = set()
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(f"SELECT image_name FROM {TABLE_NAME}")
        skipped_image_ids = {row[0] for row in cursor.fetchall()}
        conn.close()
    except Exception as e:
        logger.error(f"Error reading skipped images: {e}")
    return skipped_image_ids

def add_skipped_image(image_name):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(f"INSERT OR IGNORE INTO {TABLE_NAME}(image_name) VALUES (?)", (image_name,))
        conn.commit()
        conn.close()
        logger.info(f"Added to skipped DB: {image_name}")
    except Exception as e:
        logger.error(f"Failed to insert {image_name} into DB: {e}")

# --- Selenium ---
def setup_driver():
    options = webdriver.FirefoxOptions()
    options.add_argument("--headless")
    return webdriver.Firefox(service=FirefoxService(GeckoDriverManager().install()), options=options)

# --- Scraping ---
def scrape_page(driver, site_name, site_data, page):
    url = f"https://tcgrepublic.com/category/category_page_{site_data['id']}.html?p={page}"
    driver.get(url)
    time.sleep(2)
    image_urls = set()
    for img in driver.find_elements(By.TAG_NAME, "img"):
        src = img.get_attribute("src")
        if src and re.match(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg", src):
            clean_url = src.replace(".l2_thumbnail.jpg", "")
            image_urls.add(clean_url)
    return image_urls

def scrape_images(site_name, site_data):
    driver = setup_driver()
    image_urls = set()
    for page in tqdm(range(1, site_data["total_pages"] + 1), desc=f"Scraping {site_name}", unit="page"):
        image_urls.update(scrape_page(driver, site_name, site_data, page))
    driver.quit()
    return image_urls

# --- Download ---
def download_image(url, skipped_image_ids, site_name, save_folder):
    image_name = url.split("/")[-1]

    if image_name in skipped_image_ids:
        logger.info(f"[{site_name}] Skipped (DB): {image_name}")
        return

    save_path = os.path.join(save_folder, image_name)
    if os.path.exists(save_path):
        logger.info(f"[{site_name}] Skipped (Already Exists): {image_name}")
        return

    session = requests.Session()
    retry = Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    try:
        response = session.get(url, headers={"User-Agent": "Mozilla/5.0"}, stream=True, timeout=5)
        if response.status_code == 200:
            with open(save_path, "wb") as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)
            logger.info(f"[{site_name}] Downloaded: {image_name}")
        else:
            logger.warning(f"[{site_name}] Failed: {url} [{response.status_code}]")
            add_skipped_image(image_name)
    except Exception as e:
        logger.error(f"[{site_name}] Error downloading {url}: {e}")
        add_skipped_image(image_name)

# --- Save CSV ---
def save_csv(data, filename):
    filepath = os.path.join(CSV_DIR, filename)
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for url in data:
            writer.writerow([url])
    logger.info(f"CSV saved: {filepath}")

# --- Main ---
def main():
    init_db()
    skipped_image_ids = read_skipped_image_ids()

    all_urls = set()
    for site_name, site_data in SITES.items():
        urls = scrape_images(site_name, site_data)
        all_urls.update(urls)

        save_folder = os.path.join("G:/My Drive/New Cards", site_name)
        os.makedirs(save_folder, exist_ok=True)

        with ThreadPoolExecutor(max_workers=10) as executor:
            list(executor.map(lambda u: download_image(u, skipped_image_ids, site_name, save_folder), urls))

    save_csv(all_urls, "image_links.csv")

if __name__ == "__main__":
    main()
