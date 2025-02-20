import os
import csv
import re
import time
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from concurrent.futures import ThreadPoolExecutor
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def scrape_images():
    # Set up Selenium WebDriver
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")  # Run in headless mode
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    base_url = "https://tcgrepublic.com/category/category_page_61.html?p={}"  # Corrected pagination format
    total_pages = 158
    image_urls = []
    pattern = re.compile(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg")

    for page in range(1, total_pages + 1):
        url = base_url.format(page)
        driver.get(url)
        time.sleep(2)  # Allow page to load

        images = driver.find_elements(By.TAG_NAME, "img")
        for img in images:
            src = img.get_attribute("src")
            if src and pattern.match(src) and src not in image_urls:
                clean_url = src.replace(".l2_thumbnail.jpg", "")
                image_urls.append(clean_url)
                print(clean_url)  # Print each found URL

        print(f"Scraped {len(image_urls)} images from page {page}")

    driver.quit()

    # Save to CSV
    with open("../image_links.csv", "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        for url in image_urls:
            writer.writerow([url])

    print("Scraping complete. Links saved to image_links.csv")

    # Download images using multiple threads
    download_images(image_urls)


def download_images(image_urls):
    save_folder = "Build Divide"
    os.makedirs(save_folder, exist_ok=True)

    # Create a session with retry logic
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

    # Set User-Agent header to mimic a browser request
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    def download_image(url):
        image_name = sanitize_filename(url.split("/")[-1])
        image_path = os.path.join(save_folder, image_name)

        try:
            # Include headers in the GET request
            response = session.get(url, headers=headers, stream=True)
            if response.status_code == 200:
                with open(image_path, "wb") as file:
                    for chunk in response.iter_content(1024):
                        file.write(chunk)
                print(f"Downloaded: {image_name}")
            else:
                print(f"Failed to download: {image_name} (Status Code: {response.status_code})")
        except Exception as e:
            print(f"Error downloading {image_name}: {e}")

    # Process images one at a time
    for url in image_urls:
        download_image(url)  # Download each image sequentially
        #time.sleep(0)  # Optional: Add a slight delay between requests to avoid overwhelming the server

    print("All images have been processed.")

def sanitize_filename(filename):
    # Replace invalid characters for file systems
    return re.sub(r'[<>:"/\\|?*]', '_', filename)


if __name__ == "__main__":
    scrape_images()
