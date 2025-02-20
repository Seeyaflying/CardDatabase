import os
import time
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from urllib.parse import urljoin


# Setup WebDriver with headless mode
def setup_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")  # Make sure headless mode is set
    options.add_argument("--disable-gpu")  # Disable GPU acceleration (helps in headless mode)
    options.add_argument("--no-sandbox")  # Necessary for some environments (e.g., Docker)

    # Set path for the WebDriver
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    return driver


# Function to download all images
def download_all_images(url, folder="G:/My Drive/Card Database/Altered"):
    if not os.path.exists(folder):
        os.makedirs(folder)

    # Setup the driver
    driver = setup_driver()
    driver.get(url)

    # Allow time for the page to load
    time.sleep(3)  # Adjust if needed

    # Find all img tags
    img_tags = driver.find_elements(By.TAG_NAME, 'img')

    # Debug: Print total number of images found
    print(f"Found {len(img_tags)} images on {url}")

    for img_tag in img_tags:
        img_url = img_tag.get_attribute('src') or img_tag.get_attribute('data-src')

        # Debug: Print image URL
        if img_url:
            print(f"Found image URL: {img_url}")

        if img_url:
            img_url = urljoin(url, img_url)  # Ensure the full URL
            img_name = os.path.join(folder, os.path.basename(img_url))

            try:
                # Debug: Print before downloading
                print(f"Downloading {img_url}...")

                img_data = requests.get(img_url).content
                with open(img_name, 'wb') as file:
                    file.write(img_data)
                print(f"Downloaded {img_name}")
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





