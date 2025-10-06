import os
import time
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service
from webdriver_manager.firefox import GeckoDriverManager

# Paths
save_folder = 'G:/My Drive/New Cards/NeoPets Battledome'
check_folder = 'G:/My Drive/Card Database/NeoPets Battledome'  # Add your check folder path here

# Create directories if they don't exist
os.makedirs(save_folder, exist_ok=True)
os.makedirs(check_folder, exist_ok=True)

# Function to download an image
def download_image(url, folder=save_folder, check_folder=check_folder):
    try:
        # Extract the image name
        image_name = url.split("/")[-1]
        save_path = os.path.join(folder, image_name)
        check_path = os.path.join(check_folder, image_name)

        # Skip specific images based on file name
        if "upper_deck_logo" in image_name.lower():
            print(f"Skipping specific file: {image_name}")
            return

        # Skip downloading if the file already exists in either folder
        if os.path.exists(save_path) or os.path.exists(check_path):
            print(f"Skipping already downloaded: {image_name}")
            return

        response = requests.get(url)
        if response.status_code == 200:
            with open(save_path, 'wb') as f:
                f.write(response.content)
            print(f"Downloaded {save_path}")
    except Exception as e:
        print(f"Error downloading {url}: {e}")

# Set up Selenium WebDriver
options = webdriver.FirefoxOptions()
options.add_argument("--headless")
driver = webdriver.Firefox(service=Service(GeckoDriverManager().install()), options=options)

# URL of the website
base_url = 'https://my.upperdeck.com/public/neopets/cards'
driver.get(base_url)

# Scrape images from page
def scrape_images_from_page():
    time.sleep(2)  # Wait for page to load
    images = driver.find_elements(By.TAG_NAME, 'img')
    valid_extensions = ['.jpg', '.png', '.jpeg', '.webp']

    for img in images:
        img_url = img.get_attribute('src')
        if img_url and any(img_url.lower().endswith(ext) for ext in valid_extensions):
            download_image(img_url)
        elif img_url:
            print(f"Skipping image (invalid extension): {img_url}")

# Handle pagination
def scrape_all_images():
    while True:
        scrape_images_from_page()
        try:
            next_button = driver.find_element(By.XPATH, "//a[contains(text(), 'Next')]")
            if next_button:
                next_button.click()
                time.sleep(2)
            else:
                break
        except Exception as e:
            print("Pagination finished or failed:", e)
            break

# Start scraping
scrape_all_images()
driver.quit()
