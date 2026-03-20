import os
import time
import requests
import gdown
import zipfile
import shutil
import re
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager

# --- CONFIGURATION ---
BASE_PATH = r"G:\My Drive\New Cards\Legend of the Five Rings"
DATABASE_PATH = r"G:\My Drive\Database\Legend of the Five Rings"
L5R_DIR = BASE_PATH  # Direct root path for all operations

# Persistent Chrome Profile Location (Saves your session/cookies)
PROFILE_DIR = os.path.join(os.getcwd(), "Scraper_Profile_L5R")


def setup_driver(headless=False):
    """Sets up Chrome with a persistent profile and anti-bot measures."""
    chrome_options = Options()
    if headless:
        chrome_options.add_argument("--headless=new")

    # Use a persistent user data directory to stay 'Human'
    chrome_options.add_argument(f"--user-data-dir={PROFILE_DIR}")
    chrome_options.add_argument("--profile-directory=Default")

    # Anti-detection and UI settings
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_argument("--window-size=1366,768")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)

    # Bypass simple 'is_automated' checks
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver


def get_existing_library():
    """Indexes files in both paths to prevent duplicate downloads."""
    print("\n--- INDEXING EXISTING LIBRARIES ---")
    existing = set()
    for path in [BASE_PATH, DATABASE_PATH]:
        if os.path.exists(path):
            print(f"  > Scanning: {path}")
            for root, _, files in os.walk(path):
                for f in files:
                    existing.add(f.lower())
    print(f"  > Total files found: {len(existing)}")
    return existing


# --- PHASE 1: CLASSIC (GOOGLE DRIVE) ---
def download_classic():
    print(f"\n--- [PHASE 1] CLASSIC CCG (GOOGLE DRIVE) ---")
    drive_url = "https://drive.google.com/drive/folders/1nw_--s3Nsynczf1yFkogmGrMCaIg_Xrx"
    try:
        os.makedirs(L5R_DIR, exist_ok=True)
        gdown.download_folder(url=drive_url, output=L5R_DIR, quiet=False, remaining_ok=True)
    except Exception as e:
        print(f"!! Drive Error: {e}")


# --- PHASE 2: MODERN (HEADED SELENIUM CRAWLER) ---
def download_modern_selenium():
    print("\n--- [PHASE 2] MODERN CRAWLER (EMERALD DB) ---")
    library = get_existing_library()

    # Open in Headed mode so you can see the 'Next' clicks
    driver = setup_driver(headless=False)

    total_new = 0
    try:
        driver.get("https://www.emeralddb.org/cards?page=1")
        print("!! Browser is open. Solve any CAPTCHAs manually if they appear.")

        while True:
            try:
                # Wait for card links to appear
                wait = WebDriverWait(driver, 20)
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/card/']")))

                # Trigger lazy loading
                driver.execute_script("window.scrollBy(0, 800);")
                time.sleep(1.5)

                # Get all card slugs
                card_elements = driver.find_elements(By.CSS_SELECTOR, "a[href*='/card/']")
                slugs = list(
                    set([el.get_attribute('href').split('/')[-1] for el in card_elements if el.get_attribute('href')]))

                print(f"  [>] Page contains {len(slugs)} cards. Checking library...")

                for slug in slugs:
                    filename = f"LCG_{slug}.png"
                    if filename.lower() not in library:
                        img_url = f"https://www.emeralddb.org/bundles/card/{slug}.png"
                        try:
                            res = requests.get(img_url, timeout=10)
                            if res.status_code == 200:
                                with open(os.path.join(L5R_DIR, filename), 'wb') as f:
                                    f.write(res.content)
                                print(f"    [+] Saved: {filename}")
                                total_new += 1
                                library.add(filename.lower())
                        except:
                            pass

                # --- ROBUST NEXT PAGE LOGIC ---
                try:
                    # Target by the specific Aria Label you identified
                    next_btn = driver.find_element(By.CSS_SELECTOR, 'button[aria-label="Go to next page"]')

                    # Check if Material UI marked it as disabled
                    is_disabled = next_btn.get_attribute(
                        "disabled") is not None or "Mui-disabled" in next_btn.get_attribute("class")

                    if is_disabled:
                        print("  [>] Final page reached.")
                        break

                    print("  [>] Flipping Page...")
                    # Force click via JS to ignore the 'Ripple' overlay
                    driver.execute_script("arguments[0].click();", next_btn)

                    # Slow down for G: Drive sync and site loading
                    time.sleep(4)

                except Exception:
                    print("  [!] Next button not found. Ending crawl.")
                    break

            except TimeoutException:
                print("!! Timeout: Cards failed to load.")
                input(">> Manually fix the page in Chrome, then press Enter to retry...")
                continue

    finally:
        driver.quit()
    print(f"\nModern sync complete. {total_new} images added.")


# --- UTILITIES ---
def process_and_flatten():
    print("\n--- [PHASE 3] UNZIPPING & FLATTENING ---")
    if not os.path.exists(L5R_DIR): return

    for item in os.listdir(L5R_DIR):
        if item.lower().endswith(".zip"):
            print(f"  [>] Extracting archive: {item}")
            try:
                with zipfile.ZipFile(os.path.join(L5R_DIR, item), 'r') as z:
                    z.extractall(L5R_DIR)
                os.remove(os.path.join(L5R_DIR, item))
            except:
                pass

    # Recursive Move: Subfolders -> Root BASE_PATH
    for root, _, files in os.walk(L5R_DIR, topdown=False):
        if root == L5R_DIR: continue
        for f in files:
            source = os.path.join(root, f)
            target = os.path.join(L5R_DIR, f)
            if os.path.exists(target):
                target = os.path.join(L5R_DIR, f"alt_{int(time.time())}_{f}")
            try:
                shutil.move(source, target)
            except:
                pass
        try:
            os.rmdir(root)
        except:
            pass
    print("Folder structure flattened.")


# --- MAIN MENU ---
def main():
    while True:
        print("\n" + "=" * 50)
        print(" L5R MASTER MANAGER - G: DRIVE")
        print("=" * 50)
        print("1. [FULL RUN] Sync Classic + Modern + Flatten")
        print("2. [CLASSIC] G-Drive Archive Only")
        print("3. [MODERN] Selenium Crawler Only")
        print("4. [UTILS] Flatten Folder Structure")
        print("0. Exit")
        print("-" * 50)
        choice = input("Select an option: ")

        if choice == '1':
            download_classic()
            download_modern_selenium()
            process_and_flatten()
        elif choice == '2':
            download_classic()
        elif choice == '3':
            download_modern_selenium()
        elif choice == '4':
            process_and_flatten()
        elif choice == '0':
            break


if __name__ == "__main__":
    main()