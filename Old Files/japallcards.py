import os
import requests
import platform
import sqlite3
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm

# Selenium Imports
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- CONFIGURATION: Paths ---
UTILS_DIR = "../utils"
CHROME_DRIVER_PATH = os.path.join(UTILS_DIR, "chromedriver.exe" if platform.system() == "Windows" else "chromedriver")

# --- USER CONFIGURATION ---
BASE_SAVE_DIR = "G:/My Drive/New Cards"
CHECK_FOLDER = "G:/My Drive/Card Database"
DB_FILE = "../skipped_images.sqlite"

# --- SETTINGS ---
MAX_DOWNLOAD_WORKERS = 40
PAGE_LOAD_TIMEOUT = 15
TARGET_CHROME_VERSION = "145.0.7632.117"

# --- LOGGING SETUP ---
LOG_DIR = "../log"
os.makedirs(LOG_DIR, exist_ok=True)
now = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
log_filename = os.path.join(LOG_DIR, f"{now}.log")

logging.basicConfig(
    filename=log_filename,
    level=logging.INFO,
    format='%(message)s',
    encoding='utf-8'
)


# --- DATABASE LOGIC ---
def load_db_skips():
    if not os.path.exists(DB_FILE):
        return set()
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT image_name FROM skipped_images WHERE language='japanese'")
        results = {str(row[0]) for row in cursor.fetchall()}
        conn.close()
        return results
    except Exception as e:
        tqdm.write(f"⚠️ Database Error: {e}")
        return set()


# --- FILE SYSTEM SCAN ---
def get_all_files_recursive(directory):
    file_set = set()
    if not os.path.exists(directory):
        return file_set
    pbar = tqdm(desc=f"🔍 Scanning {os.path.basename(directory)}", unit=" folders")
    for root, _, files in os.walk(directory):
        for file in files:
            file_set.add(file)
        pbar.update(1)
    pbar.close()
    return file_set


# --- SELENIUM ENGINE ---
def setup_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_experimental_option("excludeSwitches", ["enable-logging"])
    service = ChromeService(executable_path=CHROME_DRIVER_PATH)
    return webdriver.Chrome(service=service, options=options)


def scrape_site(site_name, site_data):
    all_urls = set()
    driver = None
    try:
        driver = setup_driver()
        # Clean progress bar only - no extra text during scrape
        for page in tqdm(range(1, site_data["total_pages"] + 1), desc=f"🌐 Scraping {site_name}"):
            url = f"https://tcgrepublic.com/category/category_page_{site_data['id']}.html?p={page}"
            driver.get(url)
            WebDriverWait(driver, PAGE_LOAD_TIMEOUT).until(EC.presence_of_element_located((By.TAG_NAME, "img")))

            for img in driver.find_elements(By.TAG_NAME, "img"):
                src = img.get_attribute("src")
                if src and "l2_thumbnail" in src:
                    clean_url = src.replace(".l2_thumbnail.jpg", "")
                    all_urls.add(clean_url)
    except Exception as e:
        tqdm.write(f"❌ Scrape Error: {e}")
    finally:
        if driver: driver.quit()
    return all_urls


# --- DOWNLOAD LOGIC ---
def download_logic(url, skip_list, site_name, save_folder):
    image_name = url.split("/")[-1]

    if image_name in skip_list:
        tqdm.write(f"  [-] SKIP: {image_name}")
        return

    save_path = os.path.join(save_folder, image_name)
    try:
        r = requests.get(url, stream=True, timeout=10)
        if r.status_code == 200:
            with open(save_path, "wb") as f:
                for chunk in r.iter_content(1024): f.write(chunk)
            tqdm.write(f"  [+] NEW: {image_name}")
            logging.info(f"Downloaded: {image_name}")
        else:
            tqdm.write(f"  [!] FAIL: {image_name} ({r.status_code})")
    except Exception:
        tqdm.write(f"  [!] ERROR: {image_name}")


# --- MAIN SITES LIST ---
SITES = {
    "Battle Spirits": {"id": 79, "total_pages": 145},
    "Buddy Fight": {"id": 71, "total_pages": 233},
    "Build Divide": {"id": 61, "total_pages": 196},
    "Cardfight Vanguard": {"id": 44, "total_pages": 582},
    "Chaos": {"id": 50, "total_pages": 434},
    "Detective Conan": {"id": 84, "total_pages": 34},
    "DB Heroes": {"id": 73, "total_pages": 202},
    "DB Super Divers": {"id": 93, "total_pages": 18},
    "DBZ Super Fusion World": {"id": 82, "total_pages": 36},
    "Digimon": {"id": 37, "total_pages": 128},
    "Duel Masters": {"id": 36, "total_pages": 482},
    "Fate-Grand Order Arcade": {"id": 39, "total_pages": 42},
    "Final Fantasy": {"id": 56, "total_pages": 241},
    "Fire Emblem Cipher": {"id": 33, "total_pages": 74},
    "Godzilla Card Game": {"id": 99, "total_pages": 10},
    "Gundam": {"id": 94, "total_pages": 23},
    "Haikyuu!! Vobaca!! BREAK": {"id": 102, "total_pages": 7},
    "Hololive": {"id": 88, "total_pages": 43},
    "Kamen Rider Battle Ganba Legends": {"id": 86, "total_pages": 34},
    "Kamen Rider Battle Ganbarizing": {"id": 85, "total_pages": 99},
    "Kantai Collection Kancolle Arcade": {"id": 60, "total_pages": 1},
    "Love Live": {"id": 95, "total_pages": 42},
    "Lycee Over Ture": {"id": 48, "total_pages": 195},
    "Nivel Arena": {"id": 101, "total_pages": 10},
    "One Piece": {"id": 67, "total_pages": 102},
    "Osica": {"id": 68, "total_pages": 65},
    "Pokemon": {"id": 35, "total_pages": 657},
    "Precious Memories": {"id": 41, "total_pages": 416},
    "Prism Connect": {"id": 59, "total_pages": 89},
    "Rebirth for you": {"id": 38, "total_pages": 441},
    "Shadowverse Evolve": {"id": 62, "total_pages": 128},
    "Takashi Murakami Jellyfish Eyes": {"id": 91, "total_pages": 3},
    "The Quintessential Quintuplets": {"id": 87, "total_pages": 29},
    "Trails Series": {"id": 92, "total_pages": 11},
    "Ultraman": {"id": 90, "total_pages": 21},
    "Union Arena": {"id": 74, "total_pages": 197},
    "Vividz": {"id": 70, "total_pages": 12},
    "Weiss Schwarz": {"id": 31, "total_pages": 1398},
    "Weiss Schwarz Blau": {"id": 72, "total_pages": 117},
    "Weiss Schwarz Rose": {"id": 96, "total_pages": 41},
    "Wixoss": {"id": 43, "total_pages": 360},
    "Xross Stars": {"id": 98, "total_pages": 7},
    "Yugioh": {"id": 34, "total_pages": 829},
    "Yugioh Rush Duel": {"id": 49, "total_pages": 130},
    "Z-X Zillions over enemy X": {"id": 42, "total_pages": 458},
}


def main():
    print("🚀 Initializing Scraper...")
    os.makedirs(BASE_SAVE_DIR, exist_ok=True)

    print("📂 Syncing Database and Folders...")
    db_skips = load_db_skips()
    database_files = get_all_files_recursive(CHECK_FOLDER)
    new_cards_files = get_all_files_recursive(BASE_SAVE_DIR)
    master_skip_list = db_skips.union(database_files).union(new_cards_files)
    print(f"✅ Total collection size: {len(master_skip_list)} (Skipping duplicates)")

    for site_name, site_data in SITES.items():
        print(f"\n--- {site_name.upper()} ---")
        scraped_urls = scrape_site(site_name, site_data)
        if not scraped_urls: continue

        site_save_dir = os.path.join(BASE_SAVE_DIR, site_name)
        os.makedirs(site_save_dir, exist_ok=True)

        download_tasks = [(u, master_skip_list, site_name, site_save_dir) for u in scraped_urls]

        with ThreadPoolExecutor(max_workers=MAX_DOWNLOAD_WORKERS) as executor:
            list(tqdm(executor.map(lambda p: download_logic(*p), download_tasks),
                      total=len(download_tasks), desc=f"📥 {site_name}"))

        master_skip_list.update(set(os.listdir(site_save_dir)))

    print("\n✨ Finished. Check your 'log' folder for results.")


if __name__ == "__main__":
    input("Please have your vpn running for this. Press Enter to continue: ")
    main()