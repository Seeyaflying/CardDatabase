import os
import time
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

# --- CONFIGURATION ---
# Replace 'C:/path/to/your/utils/chromedriver.exe' with your actual path
chromedriver_path = './utils/chromedriver.exe'
save_folder = 'G:/My Drive/New Cards/NeoPets Battledome'
check_folder = 'G:/My Drive/Card Database/NeoPets Battledome'

# Create directories
os.makedirs(save_folder, exist_ok=True)
os.makedirs(check_folder, exist_ok=True)


def download_image(url, folder=save_folder, check_folder=check_folder):
    try:
        # Get filename and strip potential URL parameters (e.g., ?v=1)
        image_name = url.split("/")[-1].split("?")[0]
        save_path = os.path.join(folder, image_name)
        check_path = os.path.join(check_folder, image_name)

        if "upper_deck_logo" in image_name.lower():
            return

        if os.path.exists(save_path) or os.path.exists(check_path):
            print(f"Already exists: {image_name}")
            return

        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            with open(save_path, 'wb') as f:
                f.write(response.content)
            print(f"Saved: {image_name}")
    except Exception as e:
        print(f"Error downloading {url}: {e}")


# --- SELENIUM SETUP ---
chrome_options = Options()
#chrome_options.add_argument("--headless") # Uncomment this to hide the browser window

# Initialize using your local path
service = Service(executable_path=chromedriver_path)
driver = webdriver.Chrome(service=service, options=chrome_options)

base_url = 'https://my.upperdeck.com/public/neopets/cards'
driver.get(base_url)


def scrape_images_from_page():
    time.sleep(3)  # Give the Neopets gallery time to render images
    images = driver.find_elements(By.TAG_NAME, 'img')
    valid_extensions = ['.jpg', '.png', '.jpeg', '.webp']

    for img in images:
        img_url = img.get_attribute('src')
        if img_url and any(ext in img_url.lower() for ext in valid_extensions):
            download_image(img_url)


def scrape_all_images():
    try:
        while True:
            scrape_images_from_page()
            try:
                # Targeted XPATH for the "Next" pagination button
                next_button = driver.find_element(By.XPATH, "//a[contains(text(), 'Next')]")

                # Check if the button is disabled or if we're at the end
                if "disabled" in next_button.get_attribute("class") or not next_button.is_enabled():
                    print("Reached the last page.")
                    break

                next_button.click()
                print("Moving to next page...")
            except:
                print("No more pages found.")
                break
    finally:
        print("Cleaning up driver...")
        driver.quit()


import traceback

if __name__ == "__main__":
    try:
        scrape_all_images()
        print("\nProcess completed successfully.")
    except Exception:
        # This captures the full error log
        error_details = traceback.format_exc()
        print("\n" + "!"*30)
        print("CRITICAL ERROR DETECTED:")
        print(error_details)
        print("!"*30)
    finally:
        # This keeps the window open until you press Enter
        input("\nPress Enter to close this window and return to manager...")
