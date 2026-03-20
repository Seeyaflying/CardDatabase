import os
import time
import sqlite3
import requests
import traceback
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

# --- CONFIGURATION ---
HEADLESS_MODE = True  # Set to True to hide the browser, False to show it
DB_FILE = 'skipped_images.sqlite'
GAME_NAME = 'NeoPets Battledome'
LANGUAGE = 'english'

script_dir = os.path.dirname(os.path.abspath(__file__))
scraper_profile_path = os.path.join(script_dir, "Scraper_Profile")

save_folder = 'G:/My Drive/New Cards/NeoPets Battledome'
check_folder = 'G:/My Drive/Card Database/NeoPets Battledome'

os.makedirs(save_folder, exist_ok=True)
os.makedirs(check_folder, exist_ok=True)
os.makedirs(scraper_profile_path, exist_ok=True)


def is_in_skipped_database(image_name):
    """READ ONLY: Checks if the image is in the DB skip table."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            query = "SELECT 1 FROM skipped_images WHERE image_name = ? AND language = ? AND game_name = ?"
            result = conn.execute(query, (image_name, LANGUAGE, GAME_NAME)).fetchone()
            return result is not None
    except sqlite3.Error:
        return False


def download_image(url, folder=save_folder, check_folder=check_folder):
    try:
        image_name = url.split("/")[-1].split("?")[0]
        if "upper_deck_logo" in image_name.lower() or not image_name:
            return

        save_path = os.path.join(folder, image_name)
        check_path = os.path.join(check_folder, image_name)

        if os.path.exists(save_path):
            print(f"  - SKIPPED: Already in Save Folder ({image_name})")
            return

        if os.path.exists(check_path):
            print(f"  - SKIPPED: Already in Check Folder ({image_name})")
            return

        if is_in_skipped_database(image_name):
            print(f"  - SKIPPED: Found in Database Skip List ({image_name})")
            return

        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            with open(save_path, 'wb') as f:
                f.write(response.content)
            print(f"  [DOWNLOADED]: {image_name}")

    except Exception as e:
        print(f"  [ERROR]: Could not process {url}: {e}")


# --- SELENIUM SETUP ---
chrome_options = Options()

# Toggle Headless based on the variable above
if HEADLESS_MODE:
    chrome_options.add_argument("--headless=new")  # 'new' is the modern implementation
    print("Running in HEADLESS mode (Browser hidden)...")
else:
    print("Running in HEADED mode (Browser visible)...")

chrome_options.add_argument(f"--user-data-dir={scraper_profile_path}")
chrome_options.add_argument("--window-size=1920,1080")  # Vital for headless galleries
chrome_options.add_argument("--disable-blink-features=AutomationControlled")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("--no-sandbox")

service = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service, options=chrome_options)

base_url = 'https://my.upperdeck.com/public/neopets/cards'


def scrape_images_from_page():
    print("\n--- Scanning page for images... ---")
    time.sleep(5)
    images = driver.find_elements(By.TAG_NAME, 'img')
    valid_extensions = ['.jpg', '.png', '.jpeg', '.webp']

    found_count = 0
    for img in images:
        try:
            img_url = img.get_attribute('src')
            if img_url and any(ext in img_url.lower() for ext in valid_extensions):
                found_count += 1
                download_image(img_url)
        except:
            continue
    print(f"Finished page. Total images detected: {found_count}")


def scrape_all_images():
    try:
        driver.get(base_url)
        page_num = 1
        while True:
            print(f"\n[PAGE {page_num}]")
            scrape_images_from_page()

            try:
                next_button = driver.find_element(By.XPATH, "//a[contains(text(), 'Next')]")
                if "disabled" in next_button.get_attribute("class"):
                    print("\nReached the last page.")
                    break

                driver.execute_script("arguments[0].click();", next_button)
                print("\nClicking 'Next'...")
                time.sleep(3)
                page_num += 1
            except Exception:
                print("\nNo more pagination buttons found.")
                break
    finally:
        print("\nClosing browser and cleaning up...")
        driver.quit()


if __name__ == "__main__":
    try:
        scrape_all_images()
        print("\nProcess completed successfully.")
    except Exception:
        print("\n" + "!" * 30)
        print("CRITICAL ERROR DETECTED:")
        print(traceback.format_exc())
        print("!" * 30)
    finally:
        input("\nBrowser closed. Press Enter to exit the console...")