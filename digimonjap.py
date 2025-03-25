import requests
import json
import os
import time
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from PIL import Image
from io import BytesIO

# Paths for JSON and image storage
json_dir = "json"
json_file_path = os.path.join(json_dir, "digimonjap.json")
output_dir = "test"

# Ensure directories exist
os.makedirs(json_dir, exist_ok=True)
os.makedirs(output_dir, exist_ok=True)

# Setup Selenium WebDriver (Headless Firefox)
options = Options()
options.add_argument("--headless")
options.add_argument("--disable-gpu")
options.add_argument("--no-sandbox")
driver = webdriver.Firefox(options=options)

base_url = "https://wikimon.net/Category:Card_Images_(Digimon_Card_Game)"
image_page_urls = set()  # Use a set to avoid duplicates

# Scrape up to 20 pages
driver.get(base_url)
for page_num in range(1, 21):
    print(f"Scraping page {page_num}: {driver.current_url}")
    time.sleep(3)  # Allow time for page to load

    # Find all links to image pages
    links = driver.find_elements(By.TAG_NAME, 'a')
    for link in links:
        href = link.get_attribute('href')
        if href and href.startswith("https://wikimon.net/File:"):
            image_page_urls.add(href)

    # Click "next" button if available
    try:
        next_button = driver.find_element(By.PARTIAL_LINK_TEXT, "next")
        next_button.click()
    except:
        print("No more pages.")
        break

driver.quit()

# Save unique links to JSON file
with open(json_file_path, "w") as file:
    json.dump(list(image_page_urls), file, indent=4)
print(f"Saved {len(image_page_urls)} unique links to {json_file_path}")

# List of invalid characters for filenames
invalid_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']

# Function to sanitize filenames
def sanitize_filename(filename):
    for char in invalid_chars:
        filename = filename.replace(char, "_")
    return filename

# Set to track already downloaded images
downloaded_images = set(os.listdir(output_dir))

# Function to check image width
def is_valid_image(image_url):
    try:
        img_response = requests.get(image_url)
        if img_response.status_code!= 200:
            print(f"Failed to fetch {image_url}, Status Code: {img_response.status_code}")
            return False

        img = Image.open(BytesIO(img_response.content))
        width, height = img.size
        return width > 400  # Only allow images wider than 400 pixels

    except Exception as e:
        print(f"Error checking image size: {e}")
        return False

# Download JPG images from each URL
for page_url in image_page_urls:
    try:
        print(f"Fetching image page: {page_url}")
        response = requests.get(page_url)

        if response.status_code!= 200:
            print(f"Failed to fetch {page_url}, Status Code: {response.status_code}")
            continue

        # Parse the page and extract image URLs
        soup = BeautifulSoup(response.text, 'html.parser')
        jpg_images = [
            "https://wikimon.net" + img['src']
            for img in soup.find_all('img', src=True) if img['src'].endswith(".jpg")
        ]

        if not jpg_images:
            print(f"No JPG images found on {page_url}")
            continue

        # Download images
        for image_url in jpg_images:
            image_name = sanitize_filename(image_url.split("/")[-1])
            image_path = os.path.join(output_dir, image_name)

            if image_name in downloaded_images:
                print(f"Already downloaded: {image_name}")
                continue

            # Check image dimensions before downloading
            if not is_valid_image(image_url):
                print(f"Skipping {image_url} (width ≤ 400 pixels)")
                continue

            print(f"Downloading: {image_url}")
            img_response = requests.get(image_url)

            if img_response.status_code == 200:
                with open(image_path, "wb") as img_file:
                    img_file.write(img_response.content)
                downloaded_images.add(image_name)
                print(f"Saved: {image_path}")
            else:
                print(f"Failed to download {image_url}, Status Code: {img_response.status_code}")

        time.sleep(1)  # Prevent excessive requests

    except Exception as e:
        print(f"Error processing {page_url}: {e}")

print(" All images downloaded successfully!")