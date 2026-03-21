import os
import time
import sqlite3
import requests
import traceback
import sys
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from urllib.parse import urljoin

# ==============================================================
# 1. PLATFORM DETECTION & PATH CONFIGURATION
# ==============================================================
IS_WINDOWS = os.name == 'nt'
HEADLESS_MODE = True
DB_FILE = 'skipped_images.sqlite'
GAME_NAME = 'Altered'
LANGUAGE = 'english'

script_dir = os.path.dirname(os.path.abspath(__file__))

if IS_WINDOWS:
    # Windows Paths
    SAVE_FOLDER = r"G:\My Drive\New Cards\Altered"
    CHECK_FOLDER = r"G:\My Drive\Card Database\Altered"
    SCRAPER_PROFILE_PATH = os.path.join(script_dir, "Scraper_Profiles", "Altered_Data")
else:
    # Ubuntu Paths (Assumes rclone mount at ~/Desktop/GDrive)
    SAVE_FOLDER = os.path.expanduser("~/Desktop/GDrive/New Cards/Altered")
    CHECK_FOLDER = os.path.expanduser("~/Desktop/GDrive/Card Database/Altered")
    # Chrome profiles on Linux work best in /tmp or local home hidden folders
    SCRAPER_PROFILE_PATH = os.path.expanduser("~/.config/altered_scraper_profile")

# Ensure directories exist
os.makedirs(SAVE_FOLDER, exist_ok=True)
os.makedirs(CHECK_FOLDER, exist_ok=True)
os.makedirs(os.path.dirname(SCRAPER_PROFILE_PATH), exist_ok=True)


# ==============================================================
# 2. UTILITY FUNCTIONS
# ==============================================================
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

    # Chrome Stability & Linux Sandbox Fixes
    chrome_options.add_argument(f"--user-data-dir={SCRAPER_PROFILE_PATH}")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")

    # Essential for Ubuntu to prevent "Chrome failed to start"
    chrome_options.add_argument("--remote-debugging-port=9222")

    # Stealth settings
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)

    # Auto-install and set up driver
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)

    # Stealth: Hide Selenium signature
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    return driver


def download_image(img_url, img_filename):
    try:
        save_path = os.path.join(SAVE_FOLDER, img_filename)
        check_path = os.path.join(CHECK_FOLDER, img_filename)

        if os.path.exists(save_path) or os.path.exists(check_path):
            return  # Already have it

        if is_in_skipped_database(img_filename):
            print(f"  - SKIPPED: In Skip List ({img_filename})")
            return

        # Use a real browser-like User Agent
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(img_url, headers=headers, timeout=10)

        if response.status_code == 200:
            with open(save_path, 'wb') as file:
                file.write(response.content)
            print(f"  [DOWNLOADED]: {img_filename}")

    except Exception as e:
        print(f"  [ERROR] downloading {img_filename}: {e}")


def scrape_page(driver, url):
    print(f"Navigating to: {url}")
    driver.get(url)

    # Altered.gg uses heavy JS, wait for elements to load
    time.sleep(7)

    # Find images
    img_tags = driver.find_elements(By.TAG_NAME, 'img')
    print(f"Found {len(img_tags)} tags. Filtering...")

    found_count = 0
    for img_tag in img_tags:
        # Check src and data-src for lazy loading
        img_url = img_tag.get_attribute('src') or img_tag.get_attribute('data-src')
        if not img_url or "base64" in img_url:
            continue

        full_url = urljoin(url, img_url)
        img_filename = os.path.basename(full_url).split("?")[0]

        if img_filename and len(img_filename) > 4:  # Avoid tiny icon files
            found_count += 1
            download_image(full_url, img_filename)

    print(f"Page processing finished. Detected: {found_count}")


# ==============================================================
# 3. MAIN LOOP
# ==============================================================
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
        print("\n" + "!" * 30 + "\nCRITICAL ERROR:\n" + traceback.format_exc() + "\n" + "!" * 30)
    finally:
        print("\nClosing browser...")
        driver.quit()


if __name__ == "__main__":
    main()
    if IS_WINDOWS:
        input("\nProcess complete. Press Enter to exit...")