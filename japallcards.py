import os
import csv
import re
import time
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from tqdm import tqdm  # Progress bar library

# Define sites to scrape
SITES = {
    "Battle Spirits": {
        "base_url": "https://tcgrepublic.com/category/category_page_79.html?p={}",
        "total_pages": 142,  # Adjust as needed
        "pattern": re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")
    },
    "Buddy Fight": {
        "base_url": "https://tcgrepublic.com/category/category_page_71.html?p={}",
        "total_pages": 233,
        "pattern": re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")
    },
    "Build Divide": {
        "base_url": "https://tcgrepublic.com/category/category_page_61.html?p={}",
        "total_pages": 158,
        "pattern": re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")
    },
    "Cardfight Vanguard": {
        "base_url": "https://tcgrepublic.com/category/category_page_44.html?p={}",
        "total_pages": 505,
        "pattern": re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")
    },
    "Chaos": {
        "base_url": "https://tcgrepublic.com/category/category_page_50.html?p={}",
        "total_pages": 432,
        "pattern": re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")
    },
    "Detective Conan": {
        "base_url": "https://tcgrepublic.com/category/category_page_84.html?p={}",
        "total_pages": 14,  # Adjust as needed
        "pattern": re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")
    },
    "DB Heroes": {
        "base_url": "https://tcgrepublic.com/category/category_page_73.html?p={}",
        "total_pages": 202,  # Adjust as needed
        "pattern": re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")
    },
    "DB Super Divers": {
        "base_url": "https://tcgrepublic.com/category/category_page_93.html?p={}",
        "total_pages": 4,  # Adjust as needed
        "pattern": re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")
    },
    "DBZ Super Fusion World": {
        "base_url": "https://tcgrepublic.com/category/category_page_82.html?p={}",
        "total_pages": 21,  # Adjust as needed
        "pattern": re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")
    },
    "Duel Masters": {
        "base_url": "https://tcgrepublic.com/category/category_page_36.html?p={}",
        "total_pages": 448,  # Adjust as needed
        "pattern": re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")
    },
    "Fate-Grand Order Arcade": {
        "base_url": "https://tcgrepublic.com/category/category_page_39.html?p={}",
        "total_pages": 42,  # Adjust as needed
        "pattern": re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")
    },
    "Final Fantasy TCG": {
        "base_url": "https://tcgrepublic.com/category/category_page_56.html?p={}",
        "total_pages": 217,  # Adjust as needed
        "pattern": re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")
    },
    "Fire Emblem Cipher": {
        "base_url": "https://tcgrepublic.com/category/category_page_33.html?p={}",
        "total_pages": 74,  # Adjust as needed
        "pattern": re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")
    },
    "Gundam Card Game": {
        "base_url": "https://tcgrepublic.com/category/category_page_94.html?p={}",
        "total_pages": 2,  # Adjust as needed
        "pattern": re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")
    },
    "Hololive": {
        "base_url": "https://tcgrepublic.com/category/category_page_88.html?p={}",
        "total_pages": 11,  # Adjust as needed
        "pattern": re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")
    },
    "Kamen Rider Battle Ganba Legends": {
        "base_url": "https://tcgrepublic.com/category/category_page_86.html?p={}",
        "total_pages": 21,  # Adjust as needed
        "pattern": re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")
    },
    "Kamen Rider Battle Ganbarizing": {
        "base_url": "https://tcgrepublic.com/category/category_page_85.html?p={}",
        "total_pages": 99,  # Adjust as needed
        "pattern": re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")
    },
    "Kantai Collection Kancolle Arcade": {
        "base_url": "https://tcgrepublic.com/category/category_page_60.html?p={}",
        "total_pages": 1,  # Adjust as needed
        "pattern": re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")
    },
    "Love Live": {
        "base_url": "https://tcgrepublic.com/category/category_page_95.html?p={}",
        "total_pages": 5,  # Adjust as needed
        "pattern": re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")
    },
    "Lycee Over Ture": {
        "base_url": "https://tcgrepublic.com/category/category_page_48.html?p={}",
        "total_pages": 172,  # Adjust as needed
        "pattern": re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")
    },
    "Magic the Gathering": {
            "base_url": "https://tcgrepublic.com/category/category_page_64.html?p={}",
            "total_pages": 835,  # Adjust as needed
            "pattern": re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")
        },
    "One Piece": {
        "base_url": "https://tcgrepublic.com/category/category_page_67.html?p={}",
        "total_pages": 64,  # Adjust as needed
        "pattern": re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")
    },
    "Osica": {
        "base_url": "https://tcgrepublic.com/category/category_page_68.html?p={}",
        "total_pages": 64,  # Adjust as needed
        "pattern": re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")
    },
    "Precious Memories": {
        "base_url": "https://tcgrepublic.com/category/category_page_41.html?p={}",
        "total_pages": 415,  # Adjust as needed
        "pattern": re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")
    },
    "Prism Connect": {
        "base_url": "https://tcgrepublic.com/category/category_page_59.html?p={}",
        "total_pages": 89,  # Adjust as needed
        "pattern": re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")
    },
    "Rebirth for you": {
        "base_url": "https://tcgrepublic.com/category/category_page_38.html?p={}",
        "total_pages": 372,  # Adjust as needed
        "pattern": re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")
    },
    "Shadowverse Evolve": {
        "base_url": "https://tcgrepublic.com/category/category_page_62.html?p={}",
        "total_pages": 95,  # Adjust as needed
        "pattern": re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")
    },
    "Takashi Murakami Jellyfish Eyes": {
        "base_url": "https://tcgrepublic.com/category/category_page_91.html?p={}",
        "total_pages": 3,  # Adjust as needed
        "pattern": re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")
    },
    "The Quintessential Quintuplets": {
        "base_url": "https://tcgrepublic.com/category/category_page_87.html?p={}",
        "total_pages": 11,  # Adjust as needed
        "pattern": re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")
    },
    "Trails Series": {
        "base_url": "https://tcgrepublic.com/category/category_page_92.html?p={}",
        "total_pages": 3,  # Adjust as needed
        "pattern": re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")
    },
    "Ultraman": {
        "base_url": "https://tcgrepublic.com/category/category_page_90.html?p={}",
        "total_pages": 8,  # Adjust as needed
        "pattern": re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")
    },
    "Union Arena": {
        "base_url": "https://tcgrepublic.com/category/category_page_74.html?p={}",
        "total_pages": 133,  # Adjust as needed
        "pattern": re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")
    },
    "Vividz": {
        "base_url": "https://tcgrepublic.com/category/category_page_70.html?p={}",
        "total_pages": 12,  # Adjust as needed
        "pattern": re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")
    },
    "Weiss Schwarz": {
        "base_url": "https://tcgrepublic.com/category/category_page_31.html?p={}",
        "total_pages": 1235,  # Adjust as needed
        "pattern": re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")
    },
    "Weiss Schwarz Blau": {
        "base_url": "https://tcgrepublic.com/category/category_page_72.html?p={}",
        "total_pages": 79,  # Adjust as needed
        "pattern": re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")
    },
    "Wixoss": {
        "base_url": "https://tcgrepublic.com/category/category_page_43.html?p={}",
        "total_pages": 331,  # Adjust as needed
        "pattern": re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")
    },
    "Yugioh": {
        "base_url": "https://tcgrepublic.com/category/category_page_34.html?p={}",
        "total_pages": 761,  # Adjust as needed
        "pattern": re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")
    },
    "Z-X Zillions over enemy X": {
        "base_url": "https://tcgrepublic.com/category/category_page_42.html?p={}",
        "total_pages": 418,  # Adjust as needed
        "pattern": re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")
    }
}

def setup_driver():
    """Setup headless Selenium WebDriver."""
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)


def read_skipped_csv(site_name):
    """Read skipped images from CSV for the given site, create an empty CSV if it doesn't exist."""
    skipped_image_ids = []
    site_folder = os.path.join("csv_logs", site_name)
    skipped_csv_path = os.path.join(site_folder, "skipped.csv")

    # Create the skipped.csv file if it doesn't exist
    if not os.path.exists(skipped_csv_path):
        os.makedirs(site_folder, exist_ok=True)  # Ensure the folder exists
        with open(skipped_csv_path, "w", newline="", encoding="utf-8"):
            pass  # Just create an empty CSV file

    # If the file exists, read skipped image IDs
    with open(skipped_csv_path, "r", newline="", encoding="utf-8") as file:
        reader = csv.reader(file)
        skipped_image_ids = [row[0] for row in reader if row]

    return skipped_image_ids


def save_skipped_csv(skipped_image_ids, site_name):
    """Save skipped image IDs to skipped.csv."""
    site_folder = os.path.join("csv_logs", site_name)
    skipped_csv_path = os.path.join(site_folder, "skipped.csv")

    os.makedirs(site_folder, exist_ok=True)
    with open(skipped_csv_path, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        for image_id in skipped_image_ids:
            writer.writerow([image_id])


def scrape_images(site_name, site_data):
    """Scrape image URLs from the given site."""
    driver = setup_driver()
    image_urls = []
    skipped_image_ids = read_skipped_csv(site_name)

    for page in tqdm(range(1, site_data["total_pages"] + 1), desc=f"Scraping {site_name}", unit="page"):
        url = site_data["base_url"].format(page)
        driver.get(url)
        time.sleep(2)

        images = driver.find_elements(By.TAG_NAME, "img")
        for img in images:
            src = img.get_attribute("src")
            if src and site_data["pattern"].match(src) and src not in image_urls:
                clean_url = src.replace(".l2_thumbnail.jpg", "")
                image_urls.append(clean_url)
                print(f"[{site_name}] Found: {clean_url}")

    driver.quit()

    # Save each site's images to its own directory
    save_csv(image_urls, site_name, "image_links.csv")
    print(f"[{site_name}] Scraping complete. {len(image_urls)} images saved.")

    # Download images
    download_images(image_urls, skipped_image_ids, site_name)

    # Save skipped images to CSV for future reference
    save_skipped_csv(skipped_image_ids, site_name)


def save_csv(data, site_name, filename):
    """Saves a list of data to a CSV file inside its site-specific directory."""
    site_folder = os.path.join("csv_logs", site_name)
    os.makedirs(site_folder, exist_ok=True)
    filepath = os.path.join(site_folder, filename)

    with open(filepath, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        for row in data:
            writer.writerow([row])


def download_images(image_urls, skipped_image_ids, site_name):
    """Download images, skipping existing ones."""
    save_folder = os.path.join("downloads", site_name)
    os.makedirs(save_folder, exist_ok=True)

    session = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS"]
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    for url in tqdm(image_urls, desc="Downloading images", unit="image"):
        image_name = sanitize_filename(url.split("/")[-1])
        image_path = os.path.join(save_folder, image_name)

        # Skip download if image already exists
        if os.path.exists(image_path):
            print(f"[{site_name}] Skipped (Already Exists): {image_name}")
            skipped_image_ids.append(image_name)  # Add to skipped list
            continue

        try:
            response = session.get(url, headers=headers, stream=True)
            if response.status_code == 200:
                with open(image_path, "wb") as file:
                    for chunk in response.iter_content(1024):
                        file.write(chunk)
                print(f"[{site_name}] Downloaded: {image_name}")
            else:
                print(f"[{site_name}] Failed: {image_name} (Status Code: {response.status_code})")
        except Exception as e:
            print(f"[{site_name}] Error downloading {image_name}: {e}")


def sanitize_filename(filename):
    """Sanitize filenames by replacing problematic characters."""
    return re.sub(r'[\\/*?:"<>|]', "", filename)


if __name__ == "__main__":
    for site_name, site_data in SITES.items():
        print(f"Starting scrape for {site_name}")
        scrape_images(site_name, site_data)
