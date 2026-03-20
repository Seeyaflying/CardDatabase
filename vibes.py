import os
import time
import requests
import re
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

# --- CONFIGURATION ---
TARGET_DIR = r"G:\My Drive\New Cards\Vibes"
# List all directories you want to check for existing cards
DATABASE_DIRS = [ r"G:\My Drive\Card Database\Vibes",
    TARGET_DIR  # Also check the folder we are currently filling
                ]
URL = "https://www.vibes.game/spoiler?sort=Name&sortDirection=asc"

# 1. Setup Folders and Gather Existing Files
if not os.path.exists(TARGET_DIR):
    os.makedirs(TARGET_DIR)
    print(f"Created target folder: {TARGET_DIR}")


def get_all_filenames(directories):
    found_files = set()
    for directory in directories:
        if os.path.exists(directory):
            files = {f.lower() for f in os.listdir(directory) if os.path.isfile(os.path.join(directory, f))}
            found_files.update(files)
            print(f"Indexed {len(files)} files from: {directory}")
    return found_files


# Create a master set of everything you already own
existing_files = get_all_filenames(DATABASE_DIRS)
print(f"--- Total unique cards indexed: {len(existing_files)} ---")

# 2. Setup Selenium
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()))
driver.get(URL)

# 3. Scroll Phase
print("\n--- Starting Scroll Phase ---")
last_height = driver.execute_script("return document.body.scrollHeight")
while True:
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(3)
    new_height = driver.execute_script("return document.body.scrollHeight")
    if new_height == last_height:
        break
    last_height = new_height

# 4. Discovery
cards = driver.find_elements(By.CSS_SELECTOR, "a[class*='aspect-[2.5/3.5]'] img")
total_cards = len(cards)
print(f"--- Found {total_cards} cards on site ---\n")

# 5. Download with Triple-Check
for index, img in enumerate(cards, 1):
    try:
        raw_name = img.get_attribute('alt') or f"card_{index}"
        # Clean name for filesystem safety
        clean_name = re.sub(r'[^\w\s-]', '', raw_name).strip().replace(" ", "_")
        filename = f"{clean_name}.png"

        # CHECK IF EXISTS IN ANY OF THE THREE FOLDERS
        if filename.lower() in existing_files:
            print(f"[{index}/{total_cards}] SKIP: {raw_name} (Already in database)")
            continue

        print(f"[{index}/{total_cards}] DOWNLOADING: {raw_name}...", end="\r")

        srcset = img.get_attribute('srcset')
        if srcset:
            # Grab the high-res URL from the srcset
            actual_url = srcset.split('url=')[1].split('&')[0]
            actual_url = requests.utils.unquote(actual_url)

            response = requests.get(actual_url)
            if response.status_code == 200:
                with open(os.path.join(TARGET_DIR, filename), 'wb') as f:
                    f.write(response.content)
                print(f"[{index}/{total_cards}] SUCCESS: {raw_name}          ")
                existing_files.add(filename.lower())  # Prevent duplicates in same session

    except Exception as e:
        print(f"\n[{index}/{total_cards}] ERROR on {raw_name}: {str(e)[:50]}")

print("\n--- Sync Task Complete! ---")
driver.quit()