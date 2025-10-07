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
TABLE_NAME = "skipped_images"
LANGUAGE_TYPE = "japanese"
LOG_DIR = "log"
CSV_DIR = "json"
BASE_SAVE_DIR = "G:/My Drive/New Cards"
CHECK_FOLDER = "G:/My Drive/Card Database"

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(CSV_DIR, exist_ok=True)
os.makedirs(BASE_SAVE_DIR, exist_ok=True)
os.makedirs(CHECK_FOLDER, exist_ok=True)

# --- Logging ---
today = date.today()
log_filename = os.path.join(LOG_DIR, f"{today.strftime('%Y-%m-%d')}_jap_image_scraper.log")

logger = logging.getLogger("japanese_downloader")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.FileHandler(log_filename, encoding="utf-8")
    handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)

# --- SQL ---
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

def load_skipped_image_ids():
    """Read Japanese skipped images from DB."""
    ensure_table()
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(f"SELECT image_number FROM {TABLE_NAME} WHERE language=?", (LANGUAGE_TYPE,))
        result = {str(row[0]) for row in cursor.fetchall()}
        conn.close()
        logger.info(f"Loaded {len(result)} skipped Japanese images from database.")
        return result
    except Exception as e:
        logger.error(f"Error reading skipped images: {e}")
        return set()

# --- Selenium ---
def setup_driver():
    options = webdriver.FirefoxOptions()
    options.add_argument("--headless")
    return webdriver.Firefox(service=FirefoxService(GeckoDriverManager().install()), options=options)

# --- Scraping ---
def scrape_page(driver, site_name, site_id, page):
    url = f"https://tcgrepublic.com/category/category_page_{site_id}.html?p={page}"
    driver.get(url)
    time.sleep(1.5)
    image_urls = set()
    for img in driver.find_elements(By.TAG_NAME, "img"):
        src = img.get_attribute("src")
        if src and re.match(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg", src):
            image_urls.add(src.replace(".l2_thumbnail.jpg", ""))
    return image_urls

def scrape_images(site_name, site_data):
    driver = setup_driver()
    all_urls = set()
    for page in tqdm(range(1, site_data["total_pages"] + 1), desc=f"Scraping {site_name}", unit="page"):
        urls = scrape_page(driver, site_name, site_data["id"], page)
        all_urls.update(urls)
    driver.quit()
    return all_urls

# --- Download ---
def download_image(url, skipped_image_ids, existing_images, site_name, save_folder):
    image_name = url.split("/")[-1]
    image_number = re.search(r'\d+', image_name)
    if image_number:
        if image_number.group(0) in skipped_image_ids:
            logger.info(f"[{site_name}] Skipped (DB): {image_name}")
            return
    if image_name in existing_images:
        logger.info(f"[{site_name}] Skipped (Exists): {image_name}")
        return

    save_path = os.path.join(save_folder, image_name)

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
            logger.warning(f"[{site_name}] Failed ({response.status_code}): {url}")
    except Exception as e:
        logger.error(f"[{site_name}] Error downloading {url}: {e}")

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
    skipped_image_ids = load_skipped_image_ids()

    # --- Sites ---
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

    existing_check_images = set(os.listdir(CHECK_FOLDER))

    for site_name, site_data in SITES.items():
        save_folder = os.path.join(BASE_SAVE_DIR, site_name)
        os.makedirs(save_folder, exist_ok=True)
        existing_site_images = set(os.listdir(save_folder))
        combined_existing_images = existing_check_images.union(existing_site_images)

        urls = scrape_images(site_name, site_data)

        with ThreadPoolExecutor(max_workers=10) as executor:
            executor.map(
                lambda u: download_image(u, skipped_image_ids, combined_existing_images, site_name, save_folder),
                urls
            )

        save_csv(urls, f"{site_name}_image_links.csv")

if __name__ == "__main__":
    main()

