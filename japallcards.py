import os
import csv
import re
import time
import requests
import concurrent.futures
from selenium.webdriver.common.by import By
from selenium import webdriver
from selenium.webdriver.edge.service import Service as EdgeService
from webdriver_manager.microsoft import EdgeChromiumDriverManager
from concurrent.futures import ThreadPoolExecutor
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from tqdm import tqdm
import logging
from datetime import date
from pymongo import MongoClient

# Base URL pattern and image pattern
BASE_URL_PATTERN = "https://tcgrepublic.com/category/category_page_{}.html"
IMAGE_PATTERN = re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")

# Site configurations
SITES = {
    "Battle Spirits": {"id": 79, "total_pages": 145},
    "Buddy Fight": {"id": 71, "total_pages": 233},
    "Build Divide": {"id": 61, "total_pages": 169},
    "Cardfight Vanguard": {"id": 44, "total_pages": 525},
    "Chaos": {"id": 50, "total_pages": 433},
    "Detective Conan": {"id": 84, "total_pages": 23},
    "DB Heroes": {"id": 73, "total_pages": 202},
    "DB Super Divers": {"id": 93, "total_pages": 11},
    "DBZ Super Fusion World": {"id": 82, "total_pages": 29},
    "Digimon": {"id": 37, "total_pages": 111},
    "Duel Masters": {"id": 36, "total_pages": 460},
    "Fate-Grand Order Arcade": {"id": 39, "total_pages": 42},
    "Final Fantasy": {"id": 56, "total_pages": 227},
    "Fire Emblem Cipher": {"id": 33, "total_pages": 74},
    "Godzilla Card Game": {"id": 99, "total_pages":5},
    "Gundam": {"id": 94, "total_pages": 3},
    "Hololive": {"id": 88, "total_pages": 23},
    "Kamen Rider Battle Ganba Legends": {"id": 86, "total_pages": 25},
    "Kamen Rider Battle Ganbarizing": {"id": 85, "total_pages": 99},
    "Kantai Collection Kancolle Arcade": {"id": 60, "total_pages": 1},
    "Love Live": {"id": 95, "total_pages": 16},
    "Lycee Over Ture": {"id": 48, "total_pages": 180},
    "One Piece": {"id": 67, "total_pages": 74},
    "Osica": {"id": 68, "total_pages": 65},
    "Pokemon": {"id": 35, "total_pages": 612},
    "Precious Memories": {"id": 41, "total_pages": 416},
    "Prism Connect": {"id": 59, "total_pages": 89},
    "Rebirth for you": {"id": 38, "total_pages": 397},
    "Shadowverse Evolve": {"id": 62, "total_pages": 101},
    "Takashi Murakami Jellyfish Eyes": {"id": 91, "total_pages": 3},
    "The Quintessential Quintuplets": {"id": 87, "total_pages": 15},
    "Trails Series": {"id": 92, "total_pages": 6},
    "Ultraman": {"id": 90, "total_pages": 10},
    "Union Arena": {"id": 74, "total_pages": 156},
    "Vividz": {"id": 70, "total_pages": 12},
    "Weiss Schwarz": {"id": 31, "total_pages": 1295},
    "Weiss Schwarz Blau": {"id": 72, "total_pages": 93},
    "Weiss Schwarz Rose": {"id": 96, "total_pages": 17},
    "Wixoss": {"id": 43, "total_pages": 338},
    "Yugioh": {"id": 34, "total_pages": 784},
    "Yugioh Rush Duel": {"id": 49, "total_pages": 110},
    "Z-X Zillions over enemy X": {"id": 42, "total_pages": 435},
}

def setup_driver():
    """Setup headless Edge WebDriver."""
    print("Setting up driver...")
    options = webdriver.EdgeOptions()  # Create Edge options
    options.add_argument("--headless")
    print("Driver setup complete.")
    return webdriver.Edge(service=EdgeService(EdgeChromiumDriverManager().install()), options=options)  # Initialize Edge driver

def read_skipped_image_ids(mongo_client):
    """Reads skipped image IDs from MongoDB database."""
    print("Reading skipped image IDs...")
    skipped_image_ids = set()
    try:
        for doc in mongo_client["tcg_database"]["jap_skipped_images"].find():
            skipped_image_ids.add(doc["image_name"])
        print(f"Skipped image IDs read: {len(skipped_image_ids)}")
    except Exception as e:
        print(f"Error reading skipped image IDs: {e}")
    return skipped_image_ids

def scrape_page(driver, site_name, site_data, page):
    """Scrape image URLs from a single page."""
    image_urls = set()

    url = f"{BASE_URL_PATTERN.format(site_data['id'])}?p={page}"
    driver.get(url)
    time.sleep(2)

    images = driver.find_elements(By.TAG_NAME, "img")
    for img in images:
        src = img.get_attribute("src")
        if src and IMAGE_PATTERN.match(src):
            clean_url = src.replace(".l2_thumbnail.jpg", "")
            image_urls.add(clean_url)
            print(f"[{site_name}] Found: {clean_url}")

    return image_urls

def scrape_images(site_name, site_data):
    """Scrape image URLs from the given site."""
    print(f"Scraping {site_name}...")
    driver = setup_driver()
    image_urls = set()

    max_pages = site_data["total_pages"]
    print(f"[{site_name}] Total pages: {max_pages}")

    for page in tqdm(range(1, max_pages + 1), desc=f"Scraping {site_name}", unit="page"):
        image_urls.update(scrape_page(driver, site_name, site_data, page))
        time.sleep(1)  # Add a delay between requests

    driver.quit()
    print(f"Scraping {site_name} complete.")
    return image_urls

def download_image(url, skipped_image_ids, site_name, save_folder):
    """Download a single image and skip if already exists or listed in skipped database."""
    image_name = url.split("/")[-1]
    if image_name in skipped_image_ids:
        print(f"[{site_name}] Skipped (Listed in database): {image_name}")
        return
    if image_name in os.listdir(save_folder):
        print(f"[{site_name}] Skipped (Already Exists): {image_name}")
        return

    print(f"Downloading {url}...")
    session = requests.Session()
    retry = Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    try:
        response = session.get(url, headers=headers, stream=True, timeout=5)
        if response.status_code == 200:
            with open(os.path.join(save_folder, image_name), "wb") as file:
                for chunk in response.iter_content(1024):
                    file.write(chunk)
            print(f"[{site_name}] Downloaded: {image_name}")
        else:
            print(f"[{site_name}] Failed to download: {url}, Status Code: {response.status_code}")
    except requests.RequestException as e:
        print(f"[{site_name}] Error downloading {url}: {e}")

def download_images(image_urls, skipped_image_ids, site_name):
    """Downloads new images into 'Card Database New', checks against 'Card Database'."""
    print(f"Downloading images from {site_name}...")

    # Base folders
    base_folder = "D:/Card Database"       # reference only
    new_base_folder = "D:/New Cards"  # download target

    # Site-specific folders
    check_folder = os.path.join(base_folder, site_name)   # only check here
    new_save_folder = os.path.join(new_base_folder, site_name)  # save here

    # Ensure "new" path exists
    os.makedirs(new_save_folder, exist_ok=True)

    # Get already existing images in the main folder (for skipping)
    existing_image_names = set()
    if os.path.exists(check_folder):
        existing_image_names = set(os.listdir(check_folder))

    # Skip already existing and skipped IDs
    image_set = image_urls - existing_image_names - skipped_image_ids

    def worker(url):
        try:
            image_name = url.split("/")[-1]

            # Download only into "new" folder
            download_image(url, skipped_image_ids, site_name, new_save_folder)

        except Exception as e:
            print(f"Failed to download {url}: {e}")

    with ThreadPoolExecutor(max_workers=10) as executor:
        list(tqdm(executor.map(worker, image_set), total=len(image_set), desc=f"Downloading {site_name}", unit="image"))

def save_csv(data, filename):
    """Saves a set of data to a CSV file."""
    print("Saving CSV...")
    os.makedirs("json", exist_ok=True)
    filepath = os.path.join("json", filename)

    with open(filepath, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        for url in data:
            writer.writerow([url])
    print("CSV saved.")

def main():
    """Main function to start the scraping."""
    global logger
    os.makedirs("json", exist_ok=True)
    os.makedirs("logs", exist_ok=True)

    # Create a logger
    today = date.today()
    log_filename = f"{today.strftime('%Y-%m-%d')}_image_scraper.log"
    logger = logging.getLogger('image_scraper')
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(os.path.join("logs", log_filename))
    handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)

    print("Connecting to MongoDB...")
    MONGO_URI ='mongodb+srv://seeyaflying:Riversong1969@cluster0.7fugd.mongodb.net/?ssl=true&tlsAllowInvalidCertificates=true'

    try:
        mongo_client = MongoClient(MONGO_URI)
        print("Connected to MongoDB")
    except Exception as e:
        print(f"Failed to connect to MongoDB: {e}")
        return

    try:
        db = mongo_client["tcg_database"]
        print("Connected to database")
    except Exception as e:
        print(f"Failed to connect to database: {e}")
        return

    try:
        collection = db["jap_skipped_images"]
        print("Connected to collection")
    except Exception as e:
        print(f"Failed to connect to collection: {e}")
        return

    site_names = list(SITES.keys())
    skipped_image_ids = read_skipped_image_ids(mongo_client)

    for site_name, site_data in SITES.items():
        print(f"Starting to scrape {site_name}...")
        image_urls = scrape_images(site_name, site_data)
        download_images(image_urls, skipped_image_ids, site_name)

    save_csv({url for site_name, site_data in SITES.items() for url in scrape_images(site_name, site_data)}, "image_links.csv")
    print(f"Scraping complete.")

    # Check for duplicate image names
    image_names = {url.split("/")[-1]  for site_name, site_data in SITES.items() for url in scrape_images(site_name, site_data)}
    duplicate_image_names = {name for name in image_names if list(image_names).count(name) > 1}

    if duplicate_image_names:
        print(f"Found {len(duplicate_image_names)} duplicate image names:")
        for name in duplicate_image_names:
            print(name)
    else:
        print(f"No duplicate image names found.")

if __name__ == "__main__":
    main()