import os
import time
import requests
import re
import sys
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

# ==============================================================
# 1. PLATFORM DETECTION & CONFIGURATION
# ==============================================================
IS_WINDOWS = os.name == 'nt'

if IS_WINDOWS:
    # Windows Native Google Drive Paths
    TARGET_DIR = r"G:\My Drive\New Cards\Vibes"
    DATABASE_DIRS = [r"G:\My Drive\Card Database\Vibes", TARGET_DIR]
else:
    # Ubuntu Paths (Assumes rclone mount at ~/Desktop/GDrive)
    TARGET_DIR = os.path.expanduser("~/Desktop/GDrive/New Cards/Vibes")
    DATABASE_DIRS = [
        os.path.expanduser("~/Desktop/GDrive/Card Database/Vibes"),
        TARGET_DIR
    ]

URL = "https://www.vibes.game/spoiler?sort=Name&sortDirection=asc"

# Ensure target folder exists
os.makedirs(TARGET_DIR, exist_ok=True)


# ==============================================================
# 2. FILE INDEXING
# ==============================================================
def get_all_filenames(directories):
    found_files = set()
    for directory in directories:
        if os.path.exists(directory):
            files = {f.lower() for f in os.listdir(directory) if os.path.isfile(os.path.join(directory, f))}
            found_files.update(files)
            print(f"Indexed {len(files)} files from: {directory}")
    return found_files


existing_files = get_all_filenames(DATABASE_DIRS)
print(f"--- Total unique cards indexed: {len(existing_files)} ---\n")

# ==============================================================
# 3. SELENIUM SETUP
# ==============================================================
chrome_options = Options()
if not IS_WINDOWS:
    # Mandatory flags for Ubuntu stability
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--headless=new")  # Optional: run hidden on Linux

driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
driver.get(URL)

# ==============================================================
# 4. SCROLL & DISCOVERY
# ==============================================================
print("--- Starting Scroll Phase ---")
last_height = driver.execute_script("return document.body.scrollHeight")
while True:
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(3)  # Give images time to lazy-load
    new_height = driver.execute_script("return document.body.scrollHeight")
    if new_height == last_height:
        break
    last_height = new_height

# Vibes specific selector
cards = driver.find_elements(By.CSS_SELECTOR, "a[class*='aspect-[2.5/3.5]'] img")
total_cards = len(cards)
print(f"--- Found {total_cards} cards on site ---\n")

# ==============================================================
# 5. DOWNLOAD LOOP
# ==============================================================
for index, img in enumerate(cards, 1):
    try:
        raw_name = img.get_attribute('alt') or f"card_{index}"
        # File-safe name cleaning
        clean_name = re.sub(r'[^\w\s-]', '', raw_name).strip().replace(" ", "_")
        filename = f"{clean_name}.png"

        if filename.lower() in existing_files:
            print(f"[{index}/{total_cards}] SKIP: {raw_name} (Exists)")
            continue

        srcset = img.get_attribute('srcset')
        if srcset:
            # Extract high-res URL from Next.js image optimization parameters
            try:
                actual_url = srcset.split('url=')[1].split('&')[0]
                actual_url = requests.utils.unquote(actual_url)

                # Check if URL is relative
                if actual_url.startswith('/'):
                    actual_url = "https://www.vibes.game" + actual_url

                print(f"[{index}/{total_cards}] DOWNLOADING: {raw_name}...", end="\r")

                # Use a browser-like User Agent
                headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'}
                response = requests.get(actual_url, headers=headers, timeout=15)

                if response.status_code == 200:
                    with open(os.path.join(TARGET_DIR, filename), 'wb') as f:
                        f.write(response.content)
                    print(f"[{index}/{total_cards}] SUCCESS: {raw_name}           ")
                    existing_files.add(filename.lower())
            except (IndexError, Exception) as inner_e:
                print(f"\n[{index}/{total_cards}] URL PARSE ERROR: {raw_name}")

    except Exception as e:
        print(f"\n[{index}/{total_cards}] ERROR on {raw_name}: {str(e)[:50]}")

print("\n--- Sync Task Complete! ---")
driver.quit()