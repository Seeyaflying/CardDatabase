import os
import csv
import re
import time
import requests
import concurrent.futures
from selenium.webdriver.common.by import By
from selenium import webdriver
from selenium.webdriver.firefox.service import Service as FirefoxService
from webdriver_manager.firefox import GeckoDriverManager
from concurrent.futures import ThreadPoolExecutor
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from tqdm import tqdm
from collections import Counter

# Base URL pattern and image pattern
BASE_URL_PATTERN = "https://tcgrepublic.com/category/category_page_{}.html"
IMAGE_PATTERN = re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")

# Site configurations
SITES = {
    "Battle Spirits": {"id": 79, "total_pages": 142},
    "Buddy Fight": {"id": 71, "total_pages": 233},
    "Build Divide": {"id": 61, "total_pages": 158},
    "Cardfight Vanguard": {"id": 44, "total_pages": 505},
    "Chaos": {"id": 50, "total_pages": 432},
    "Detective Conan": {"id": 84, "total_pages": 14},
    "DB Heroes": {"id": 73, "total_pages": 202},
    "DB Super Divers": {"id": 93, "total_pages": 4},
    "DBZ Super Fusion World": {"id": 82, "total_pages": 21},
    "Duel Masters": {"id": 36, "total_pages": 448},
    "Fate-Grand Order Arcade": {"id": 39, "total_pages": 42},
    "Final Fantasy": {"id": 56, "total_pages": 217},
    "Fire Emblem Cipher": {"id": 33, "total_pages": 74},
    "Hololive": {"id": 88, "total_pages": 11},
    "Kamen Rider Battle Ganba Legends": {"id": 86, "total_pages": 21},
    "Kamen Rider Battle Ganbarizing": {"id": 85, "total_pages": 99},
    "Kantai Collection Kancolle Arcade": {"id": 60, "total_pages": 1},
    "Love Live": {"id": 95, "total_pages": 5},
    "Lycee Over Ture": {"id": 48, "total_pages": 172},
    "One Piece": {"id": 67, "total_pages": 64},
    "Osica": {"id": 68, "total_pages": 64},
    "Pokemon": {"id": 35, "total_pages": 592},
    "Precious Memories": {"id": 41, "total_pages": 415},
    "Prism Connect": {"id": 59, "total_pages": 89},
    "Rebirth for you": {"id": 38, "total_pages": 372},
    "Shadowverse Evolve": {"id": 62, "total_pages": 95},
    "Takashi Murakami Jellyfish Eyes": {"id": 91, "total_pages": 3},
    "The Quintessential Quintuplets": {"id": 87, "total_pages": 11},
    "Trails Series": {"id": 92, "total_pages": 3},
    "Ultraman": {"id": 90, "total_pages": 8},
    "Union Arena": {"id": 74, "total_pages": 133},
    "Vividz": {"id": 70, "total_pages": 12},
    "Weiss Schwarz": {"id": 31, "total_pages": 1235},
    "Weiss Schwarz Blau": {"id": 72, "total_pages": 79},
    "Wixoss": {"id": 43, "total_pages": 331},
    "Yugioh": {"id": 34, "total_pages": 761},
    "Yugioh Rush Duel": {"id": 49, "total_pages": 103},
    "Z-X Zillions over enemy X": {"id": 42, "total_pages": 418},
}

def setup_driver():
    """Setup headless Selenium WebDriver."""
    options = webdriver.FirefoxOptions()  # Create Firefox options
    options.add_argument("--headless")
    return webdriver.Firefox(service=FirefoxService(GeckoDriverManager().install()), options=options)  # Initialize Firefox driver

def read_skipped_csv():
    """Reads a CSV file of skipped image numbers and returns a list of filenames with '.jpg' appended.
    If the file does not exist, it is created as an empty file.

    Returns:
        list: A list of skipped image filenames (e.g., '001.jpg').
    """
    csv_filepath = os.path.join("json", "japskipped.csv")

    try:
        if not os.path.exists(csv_filepath):
            with open(csv_filepath, 'w') as file:
                pass  # Create an empty file
    except Exception as e:
        print(f"Error creating skipped images file: {e}")
        return []

    try:
        with open(csv_filepath, mode='r', encoding='utf-8') as file:
            reader = csv.reader(file)
            skipped_images = []
            for row in reader:
                if row and len(row) > 0:
                    number = row[0].strip()
                    skipped_images.append(number + ".jpg")
            return skipped_images
    except Exception as e:
        print(f"Error reading skipped images file: {e}")
        return []

def scrape_page(driver, site_name, site_data, page):
    """Scrape image URLs from a single page."""
    image_urls = []

    url = f"{BASE_URL_PATTERN.format(site_data['id'])}?p={page}"
    driver.get(url)
    time.sleep(2)

    images = driver.find_elements(By.TAG_NAME, "img")
    for img in images:
        src = img.get_attribute("src")
        if src and IMAGE_PATTERN.match(src):
            clean_url = src.replace(".l2_thumbnail.jpg", "")
            image_urls.append(clean_url)
            print(f"[{site_name}] Found: {clean_url}")

    return image_urls

def scrape_images(site_name, site_data, site_folder):
    """Scrape image URLs from the given site."""
    driver = setup_driver()
    image_urls = []
    skipped_image_ids = read_skipped_csv()

    max_pages = site_data["total_pages"]
    print(f"[{site_name}] Total pages: {max_pages}")

    for page in tqdm(range(1, max_pages + 1), desc=f"Scraping {site_name}", unit="page"):
        url = f"{BASE_URL_PATTERN.format(site_data['id'])}?p={page}"
        driver.get(url)
        time.sleep(2)

        images = driver.find_elements(By.TAG_NAME, "img")
        for img in images:
            src = img.get_attribute("src")
            if src and IMAGE_PATTERN.match(src):
                clean_url = src.replace(".l2_thumbnail.jpg", "")
                image_urls.append(clean_url)
                print(f"[{site_name}] Found: {clean_url}")

    driver.quit()

    image_urls = list(set(image_urls))
    image_urls = [url for url in image_urls if url.split("/")[-1] not in skipped_image_ids]

    save_csv(image_urls, site_folder, "image_links.csv")
    print(f"[{site_name}] Scraping complete. {len(image_urls)} images saved.")

    # Check for duplicate image names
    image_names = [url.split("/")[-1] for url in image_urls]
    duplicate_image_names = [name for name, count in Counter(image_names).items() if count > 1]

    if duplicate_image_names:
        print(f"[{site_name}] Found {len(duplicate_image_names)} duplicate image names:")
        for name in duplicate_image_names:
            print(name)
    else:
        print(f"[{site_name}] No duplicate image names found.")

    # Check if max page is higher than total pages
    try:
        last_page_url = f"{BASE_URL_PATTERN.format(site_data['id'])}?p={max_pages + 1}"
        driver = setup_driver()
        driver.get(last_page_url)
        time.sleep(2)
        if driver.title!= "404 Not Found":
            print(f"[{site_name}] Warning: Max page ({max_pages}) might be lower than the total pages. Consider updating the total pages.")
        driver.quit()
    except Exception as e:
        print(f"[{site_name}] Error checking max page: {e}")

    download_images(image_urls, skipped_image_ids, site_name, site_folder)

def save_csv(data, site_folder, filename):
    """Saves a list of data to a CSV file inside its site-specific directory."""
    os.makedirs(site_folder, exist_ok=True)
    filepath = os.path.join(site_folder, filename) # Changed this line

    with open(filepath, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        for row in data:
            writer.writerow([row])

def sanitize_filename(filename):
    return ''.join(filter(str.isalnum, filename.split('.')[0]))

def download_image(url, skipped_image_ids, site_name, site_folder):
    """Download a single image and skip if already exists or listed in skipped CSV."""
    save_folder = os.path.join("G:/My Drive/Card Database", site_name)
    os.makedirs(save_folder, exist_ok=True)

    image_name = url.split("/")[-1] + ".jpg"
    image_path = os.path.join(save_folder, image_name)

    if image_name in skipped_image_ids:
        print(f"[{site_name}] Skipped (Listed in CSV): {image_name}")
        return
    if os.path.exists(image_path):
        print(f"[{site_name}] Skipped (Already Exists): {image_name}")
        return

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
            with open(image_path, "wb") as file:
                for chunk in response.iter_content(1024):
                    file.write(chunk)
            print(f"[{site_name}] Downloaded: {image_name}")
        else:
            print(f"[{site_name}] Failed to download: {url}, Status Code: {response.status_code}")
    except requests.RequestException as e:
        print(f"[{site_name}] Error downloading {url}: {e}")

def download_images(image_urls, skipped_image_ids, site_name, site_folder):
    """Downloads images concurrently using ThreadPoolExecutor."""
    image_list = [{'url': url, 'destination': (skipped_image_ids, site_name, site_folder)} for url in image_urls]

    def worker(image_info):
        try:
            download_image(image_info['url'], *image_info['destination'])
        except Exception as e:
            print(f"Failed to download {image_info['url']}: {e}")

    with ThreadPoolExecutor(max_workers=10) as executor:
        list(tqdm(executor.map(worker, image_list), total=len(image_list), desc=f"Downloading {site_name} images", unit="image"))

def main():
    """Main function to start the scraping."""
    csv_logs_dir = "json"
    os.makedirs(csv_logs_dir, exist_ok=True)

    for site_name, site_data in SITES.items():
        site_folder = os.path.join(csv_logs_dir, site_name)
        os.makedirs(site_folder, exist_ok=True)
        os.makedirs(os.path.join("G:/My Drive/Card Database", site_name), exist_ok=True)

        print(f"Starting to scrape {site_name}...")
        scrape_images(site_name, site_data, site_folder)

if __name__ == "__main__":
    main()