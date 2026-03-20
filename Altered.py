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
from urllib.parse import urljoin

# --- CONFIGURATION ---
HEADLESS_MODE = True
DB_FILE = 'skipped_images.sqlite'
GAME_NAME = 'Altered'
LANGUAGE = 'english'

save_folder = "G:/My Drive/New Cards/Altered"
check_folder = "G:/My Drive/Card Database/Altered"

script_dir = os.path.dirname(os.path.abspath(__file__))
# Use a very specific path to avoid permission issues
scraper_profile_path = os.path.join(script_dir, "Scraper_Profiles", "Altered_Data")

os.makedirs(save_folder, exist_ok=True)
os.makedirs(check_folder, exist_ok=True)
os.makedirs(scraper_profile_path, exist_ok=True)


def is_in_skipped_database(image_name):
    try:
        with sqlite3.connect(DB_FILE) as conn:
            query = "SELECT 1 FROM skipped_images WHERE image_name = ? AND language = ? AND game_name = ?"
            result = conn.execute(query, (image_name, LANGUAGE, GAME_NAME)).fetchone()
            return result is not None
    except sqlite3.Error:
        return False


def setup_driver():
    chrome_options = Options()

    if HEADLESS_MODE:
        chrome_options.add_argument("--headless=new")

    # CRITICAL: Path formatting for Windows
    chrome_options.add_argument(f"--user-data-dir={scraper_profile_path}")

    # Stability Arguments
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--remote-debugging-port=9222")  # Fixes the DevTools error

    # Keeps Chrome from showing "Controlled by automated software"
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)

    # Further automation stealth
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    return driver


def download_image(img_url, img_filename, folder=save_folder, check_folder=check_folder):
    try:
        save_path = os.path.join(folder, img_filename)
        check_path = os.path.join(check_folder, img_filename)

        if os.path.exists(save_path):
            print(f"  - SKIPPED: Already in Save Folder ({img_filename})")
            return

        if os.path.exists(check_path):
            print(f"  - SKIPPED: Already in Check Folder ({img_filename})")
            return

        if is_in_skipped_database(img_filename):
            print(f"  - SKIPPED: Found in Database Skip List ({img_filename})")
            return

        response = requests.get(img_url, timeout=10)
        if response.status_code == 200:
            with open(save_path, 'wb') as file:
                file.write(response.content)
            print(f"  [DOWNLOADED]: {img_filename}")
    except Exception as e:
        print(f"  [ERROR] processing {img_filename}: {e}")


def scrape_page(driver, url):
    driver.get(url)
    time.sleep(6)  # Increased wait for Altered assets

    img_tags = driver.find_elements(By.TAG_NAME, 'img')
    print(f"Scanning {len(img_tags)} image tags...")

    found_count = 0
    for img_tag in img_tags:
        img_url = img_tag.get_attribute('src') or img_tag.get_attribute('data-src')
        if not img_url:
            continue

        full_url = urljoin(url, img_url)
        img_filename = os.path.basename(full_url).split("?")[0]

        if img_filename:
            found_count += 1
            download_image(full_url, img_filename)

    print(f"Finished page. Total images detected: {found_count}")


def main():
    base_url = "https://www.altered.gg/en-us/cards"
    max_pages = 40
    driver = setup_driver()

    try:
        for current_page in range(1, max_pages + 1):
            print(f"\n--- [PAGE {current_page}] ---")
            page_url = f"{base_url}?page={current_page}"
            scrape_page(driver, page_url)
    except Exception:
        print("\n" + "!" * 30)
        print("CRITICAL ERROR:")
        print(traceback.format_exc())
        print("!" * 30)
    finally:
        print("\nClosing browser...")
        driver.quit()


if __name__ == "__main__":
    main()
    input("\nProcess complete. Press Enter to exit...")







