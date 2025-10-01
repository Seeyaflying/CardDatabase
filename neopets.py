import os
import time
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service
from webdriver_manager.firefox import GeckoDriverManager

# Create a directory to store images
os.makedirs('G:/My Drive/New Cards/NeoPets Battledome', exist_ok=True)

# Function to download an image
def download_image(url, folder='G:/My Drive/New Cards/NeoPets Battledome'):
    try:
        # Extract the image name from the URL
        image_name = os.path.join(folder, url.split("/")[-1])

        # Skip specific images based on file name
        if "upper_deck_logo" in image_name.lower():
            print(f"Skipping specific file: {image_name}")
            return

        # Skip downloading if the file already exists
        if os.path.exists(image_name):
            print(f"Skipping already downloaded: {image_name}")
            return

        response = requests.get(url)
        if response.status_code == 200:
            with open(image_name, 'wb') as f:
                f.write(response.content)
            print(f"Downloaded {image_name}")
    except Exception as e:
        print(f"Error downloading {url}: {e}")

# Set up the Selenium WebDriver (automatically fetches the correct GeckoDriver version)
options = webdriver.FirefoxOptions()
options.add_argument("--headless")  # Run in headless mode (no UI)

# Use WebDriver Manager to automatically handle driver version matching
driver = webdriver.Firefox(service=Service(GeckoDriverManager().install()), options=options)

# URL of the website
base_url = 'https://my.upperdeck.com/public/neopets/cards'

# Open the webpage
driver.get(base_url)

# Function to scrape images from the current page
def scrape_images_from_page():
    # Wait for page content to load
    time.sleep(2)  # Adjust if necessary

    # Find all image elements on the page
    images = driver.find_elements(By.TAG_NAME, 'img')

    for img in images:
        img_url = img.get_attribute('src')
        if img_url:
            # Check if the image URL ends with a valid image extension
            valid_extensions = ['.jpg', '.png', '.jpeg', '.webp']
            if not any(img_url.lower().endswith(ext) for ext in valid_extensions):
                print(f"Skipping image: {img_url} (invalid extension)")
                continue

            # Download the image
            download_image(img_url)

# Function to handle pagination
def scrape_all_images():
    while True:
        # Scrape images on the current page
        scrape_images_from_page()

        # Check if there is a next page (adjust the selector based on how the site handles pagination)
        try:
            next_button = driver.find_element(By.XPATH, "//a[contains(text(), 'Next')]")
            if next_button:
                next_button.click()
                time.sleep(2)  # Wait for the next page to load
            else:
                print("No more pages found.")
                break
        except Exception as e:
            print("Pagination finished or failed:", e)
            break

# Start scraping images
scrape_all_images()

# Close the driver after scraping
driver.quit()