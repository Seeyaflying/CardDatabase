import os
import time
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service
from webdriver_manager.firefox import GeckoDriverManager
from urllib.parse import urljoin

# Define skipped images (add more to this list as needed)
SKIPPED_IMAGES = {
    "empty.png",
    "altered_applestore_en_us-1.png",
    "altered_googleplay_en_us-1.png",
    "altered_homepage_cover_logo.png",
    "divider-sm.png",
}

# Setup WebDriver with headless mode
def setup_driver():
    options = webdriver.FirefoxOptions()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    driver = webdriver.Firefox(service=Service(GeckoDriverManager().install()), options=options)
    return driver

# Function to download all images
def download_all_images(url, folder="G:/My Drive/Card Database/Altered"):
    if not os.path.exists(folder):
        os.makedirs(folder)

    driver = setup_driver()
    driver.get(url)
    time.sleep(3)

    img_tags = driver.find_elements(By.TAG_NAME, 'img')
    print(f"Found {len(img_tags)} images on {url}")

    for img_tag in img_tags:
        img_url = img_tag.get_attribute('src') or img_tag.get_attribute('data-src')
        if not img_url:
            continue

        img_url = urljoin(url, img_url)
        img_filename = os.path.basename(img_url)

        if img_filename in SKIPPED_IMAGES:
            print(f"Skipping {img_filename} (in skipped list)")
            continue

        img_path = os.path.join(folder, img_filename)

        try:
            print(f"Downloading {img_url}...")
            img_data = requests.get(img_url).content
            with open(img_path, 'wb') as file:
                file.write(img_data)
            print(f"Downloaded {img_path}")
        except Exception as e:
            print(f"Error downloading {img_url}: {e}")

    driver.quit()

# Function to handle URL-based pagination
def scrape_paginated_site(base_url, start_page=1, max_pages=40):
    current_page = start_page
    while current_page <= max_pages:
        print(f"Scraping page {current_page}...")
        page_url = f"{base_url}?page={current_page}"
        download_all_images(page_url)
        current_page += 1

# Start the process with the given site URL
scrape_paginated_site("https://www.altered.gg/en-us/cards", max_pages=40)






