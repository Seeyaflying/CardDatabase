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

# ==============================================================
# 1. PLATFORM DETECTION & PATH CONFIGURATION
# ==============================================================
IS_WINDOWS = os.name == 'nt'
HEADLESS_MODE = True  # Set to True to hide the browser
DB_FILE = 'skipped_images.sqlite'
GAME_NAME = 'NeoPets Battledome'
LANGUAGE = 'english'

script_dir = os.path.dirname(os.path.abspath(__file__))

if IS_WINDOWS:
    # Windows Native Paths
    SAVE_FOLDER = r"G:\My Drive\New Cards\NeoPets Battledome"
    CHECK_FOLDER = r"G:\My Drive\Card Database\NeoPets Battledome"
    SCRAPER_PROFILE_PATH = os.path.join(script_dir, "Scraper_Profile")
else:
    # Ubuntu Paths (Assumes rclone mount at ~/Desktop/GDrive)
    SAVE_FOLDER = os.path.expanduser("~/Desktop/GDrive/New Cards/NeoPets Battledome")
    CHECK_FOLDER = os.path.expanduser("~/Desktop/GDrive/Card Database/NeoPets Battledome")
    # Using local hidden folder for profile to prevent rclone database locks
    SCRAPER_PROFILE_PATH = os.path.expanduser("~/.config/neopets_scraper_profile")

# Ensure directories exist
os.makedirs(SAVE_FOLDER, exist_ok=True)
os.makedirs(CHECK_FOLDER, exist_ok=True)
os.makedirs(SCRAPER_PROFILE_PATH, exist_ok=True)


# ==============================================================
# 2. UTILITY FUNCTIONS
# ==============================================================
def is_in_skipped_database(image_name):
    """Checks if the image is in the DB skip table."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            query = "SELECT 1 FROM skipped_images WHERE image_name = ? AND language = ? AND game_name = ?"
            result = conn.execute(query, (image_name, LANGUAGE, GAME_NAME)).fetchone()
            return result is not None
    except sqlite3.Error:
        return False


def download_image(url):
    try:
        # Extract filename and remove URL parameters
        image_name = url.split("/")[-1].split("?")[0]

        # Filter out common UI assets
        if "upper_deck_logo" in image_name.lower() or not image_name or len(image_name) < 4:
            return

        save_path = os.path.join(SAVE_FOLDER, image_name)
        check_path = os.path.join(CHECK_FOLDER, image_name)

        # Skip checks
        if os.path.exists(save_path) or os.path.exists(check_path):
            return

        if is_in_skipped_database(image_name):
            print(f"  - SKIPPED: In Skip List ({image_name})")
            return

        # Download with timeout and user-agent
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            with open(save_path, 'wb') as f:
                f.write(response.content)
            print(f"  [DOWNLOADED]: {image_name}")

    except Exception as e:
        print(f"  [ERROR]: Could not process {url}: {e}")


# ==============================================================
# 3. SELENIUM ENGINE
# ==============================================================
def setup_driver():
    chrome_options = Options()

    if HEADLESS_MODE:
        chrome_options.add_argument("--headless=new")
        print("Running in HEADLESS mode...")
    else:
        print("Running in HEADED mode...")

    # Stability & Linux Fixes
    chrome_options.add_argument(f"--user-data-dir={SCRAPER_PROFILE_PATH}")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--remote-debugging-port=9222")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)

    # Hide automation signature
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver


def scrape_images_from_page(driver):
    print("\n--- Scanning page for images... ---")
    # Increased wait for Upper Deck's dynamic gallery
    time.sleep(6)

    images = driver.find_elements(By.TAG_NAME, 'img')
    valid_extensions = ['.jpg', '.png', '.jpeg', '.webp']

    found_count = 0
    for img in images:
        try:
            # Check src and data-src for lazy-loading
            img_url = img.get_attribute('src') or img.get_attribute('data-src')
            if img_url and any(ext in img_url.lower() for ext in valid_extensions):
                found_count += 1
                download_image(img_url)
        except:
            continue
    print(f"Finished page. Total images detected: {found_count}")


def scrape_all_images():
    base_url = 'https://my.upperdeck.com/public/neopets/cards'
    driver = setup_driver()

    try:
        driver.get(base_url)
        page_num = 1
        while True:
            print(f"\n[PAGE {page_num}]")
            scrape_images_from_page(driver)

            try:
                # Find the Next button via XPATH
                next_button = driver.find_element(By.XPATH, "//a[contains(text(), 'Next')]")

                # Check if we've reached the end
                if "disabled" in next_button.get_attribute("class") or next_button.get_attribute("disabled"):
                    print("\nReached the last page.")
                    break

                # Use JS click to bypass potential overlay issues
                driver.execute_script("arguments[0].click();", next_button)
                print("\nClicking 'Next'...")
                time.sleep(4)
                page_num += 1
            except Exception:
                print("\nNo more pagination buttons found.")
                break
    finally:
        print("\nClosing browser...")
        driver.quit()


# ==============================================================
# 4. ENTRY POINT
# ==============================================================
if __name__ == "__main__":
    try:
        scrape_all_images()
        print("\nProcess completed successfully.")
    except Exception:
        print("\n" + "!" * 30 + "\nCRITICAL ERROR:\n" + traceback.format_exc() + "\n" + "!" * 30)

    # Pause at exit only on Windows
    if IS_WINDOWS:
        input("\nPress Enter to exit...")