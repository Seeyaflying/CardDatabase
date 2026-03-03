import os
import time
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from urllib.parse import urljoin

# --- CONFIGURATION ---
# Path to your local chromedriver
chromedriver_path = './utils/chromedriver.exe'

# Define skipped images
SKIPPED_IMAGES = {
    "empty.png",
    "altered_applestore_en_us-1.png",
    "altered_googleplay_en_us-1.png",
    "altered_homepage_cover_logo.png",
    "divider-sm.png",
}

# Folders
save_folder = "G:/My Drive/New Cards/Altered"
check_folder = "G:/My Drive/Card Database/Altered"

# Ensure folders exist
os.makedirs(save_folder, exist_ok=True)
os.makedirs(check_folder, exist_ok=True)


# Setup Chrome WebDriver
def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # Run in background
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")

    # Point to your local executable
    service = Service(executable_path=chromedriver_path)
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver


# Function to download images with check folder logic
def download_images_from_page(url, folder=save_folder, check_folder=check_folder):
    driver = setup_driver()
    try:
        driver.get(url)
        time.sleep(4)  # Altered.gg can be slow to load card assets

        img_tags = driver.find_elements(By.TAG_NAME, 'img')
        print(f"Found {len(img_tags)} image tags on {url}")

        for img_tag in img_tags:
            # Check src and data-src for lazy-loading
            img_url = img_tag.get_attribute('src') or img_tag.get_attribute('data-src')
            if not img_url:
                continue

            img_url = urljoin(url, img_url)
            img_filename = os.path.basename(img_url).split("?")[0]  # Clean URL params

            save_path = os.path.join(folder, img_filename)
            check_path = os.path.join(check_folder, img_filename)

            # 1. Skip if in global skip list
            if img_filename in SKIPPED_IMAGES:
                continue

            # 2. Skip if already exists in either location
            if os.path.exists(save_path) or os.path.exists(check_path):
                print(f"Skipping {img_filename} (already exists)")
                continue

            try:
                print(f"Downloading {img_url}...")
                response = requests.get(img_url, timeout=10)
                if response.status_code == 200:
                    with open(save_path, 'wb') as file:
                        file.write(response.content)
            except Exception as e:
                print(f"Error downloading {img_url}: {e}")
    finally:
        driver.quit()


# Function to handle URL-based pagination
def scrape_paginated_site(base_url, start_page=1, max_pages=40):
    current_page = start_page
    while current_page <= max_pages:
        print(f"\n--- Scraping page {current_page} ---")
        page_url = f"{base_url}?page={current_page}"
        download_images_from_page(page_url)
        current_page += 1


if __name__ == "__main__":
    scrape_paginated_site("https://www.altered.gg/en-us/cards", max_pages=40)







