import os
import time
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# Create a directory to store images
os.makedirs('G:/My Drive/Card Database/NeoPets Battledome', exist_ok=True)

# Function to download an image
def download_image(url, folder='G:/My Drive/Card Database/NeoPets Battledome'):
    try:
        # Extract the image name from the URL
        image_name = os.path.join(folder, url.split("/")[-1])

        # Skip specific images based on file name
        if image_name.endswith("Upper_Deck_Logo.png"):
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

# Set up the Selenium WebDriver (automatically fetches the correct ChromeDriver version)
options = webdriver.ChromeOptions()
options.add_argument("--headless")  # Run in headless mode (no UI)

# Use WebDriver Manager to automatically handle driver version matching
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

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
            # Skip certain images based on conditions
            if "placeholder" in img_url or not img_url.endswith(('.jpg', '.png', '.jpeg')):
                print(f"Skipping image: {img_url}")
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
