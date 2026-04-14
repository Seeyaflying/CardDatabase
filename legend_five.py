import os
import time
import requests
import gdown
import zipfile
import shutil
import sys
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# ==============================================================
# 1. PLATFORM DETECTION & PATH CONFIGURATION
# ==============================================================
IS_WINDOWS = os.name == 'nt'

# Global Scrapers Root (to be ignored in Git)
SCRAPER_ROOT = os.path.join(os.getcwd(), "scrapers")
os.makedirs(SCRAPER_ROOT, exist_ok=True)

if IS_WINDOWS:
    # Windows Native Paths
    BASE_PATH = r"G:\My Drive\New Cards\Legend of the Five Rings"
    DATABASE_PATH = r"G:\My Drive\Database\Legend of the Five Rings"
    LOCAL_STAGING = os.path.join( "L5R_Staging")
    PROFILE_DIR = os.path.join(SCRAPER_ROOT, "L5R")
else:
    # Ubuntu Paths (Assumes rclone mount at ~/Desktop/GDrive)
    BASE_PATH = os.path.expanduser("~/Desktop/GDrive/New Cards/Legend of the Five Rings")
    DATABASE_PATH = os.path.expanduser("~/Desktop/GDrive/Database/Legend of the Five Rings")
    LOCAL_STAGING = os.path.expanduser("~/Desktop/L5R_Staging")
    # Using a local hidden folder for profile to avoid rclone lag
    PROFILE_DIR = os.path.expanduser("~/.config/l5r_scraper_profile")

# Ensure local staging exists
os.makedirs(LOCAL_STAGING, exist_ok=True)


# ==============================================================
# 2. BROWSER SETUP
# ==============================================================
def setup_driver():
    print(f"\n[SYSTEM] Initializing Browser (1024x768)...")
    chrome_options = Options()
    chrome_options.add_argument(f"--user-data-dir={PROFILE_DIR}")
    chrome_options.add_argument("--window-size=1024,768")

    # Critical Linux Stability Flags
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver


# ==============================================================
# 3. CORE LOGIC
# ==============================================================
def get_existing_library():
    print("\n--- [INDEX] SCANNING ALL LOCATIONS ---")
    existing = set()
    # Check both cloud and local staging to prevent redownloads
    for path in [LOCAL_STAGING, BASE_PATH, DATABASE_PATH]:
        if os.path.exists(path):
            for root, _, files in os.walk(path):
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        # Ignore dead/empty files
                        if os.path.getsize(fp) > 5000:
                            existing.add(f.lower())
                    except:
                        pass
    print(f"  [RESULT] Found {len(existing)} unique cards in collection.")
    return existing


def download_classic_local():
    print(f"\n{'=' * 60}\n[STEP 1] DOWNLOADING ARCHIVE\n{'=' * 60}")
    drive_url = "https://drive.google.com/drive/folders/1nw_--s3Nsynczf1yFkogmGrMCaIg_Xrx"
    print("[NETWORK] Connecting to Google Drive Archive...")
    try:
        # gdown works great on both OSs
        gdown.download_folder(url=drive_url, output=LOCAL_STAGING, quiet=False, remaining_ok=True)
        print("[SUCCESS] Local staging updated.")
    except Exception as e:
        print(f"[ERROR] Drive download failed: {e}")


def process_and_flatten_local():
    print(f"\n{'=' * 60}\n[STEP 2] EXTRACTION & FLATTENING\n{'=' * 60}")
    if not os.path.exists(LOCAL_STAGING): return

    for root, _, files in os.walk(LOCAL_STAGING):
        for f in files:
            if f.lower().endswith(".zip"):
                zip_path = os.path.join(root, f)
                print(f"  [ZIP] Inspecting: {f}")
                try:
                    with zipfile.ZipFile(zip_path, 'r') as z:
                        extract_dir = os.path.join(root, f"_extracted_{int(time.time())}")
                        z.extractall(extract_dir)

                        success_count = 0
                        items = [x for x in z.namelist() if not x.endswith(('/', '\\'))]

                        for ext_f in items:
                            src_path = os.path.join(extract_dir, ext_f)
                            dest_filename = os.path.basename(ext_f)
                            dest_path = os.path.join(LOCAL_STAGING, dest_filename)

                            # Move and overwrite only if the new file is larger/better
                            if os.path.exists(dest_path):
                                if os.path.getsize(src_path) > os.path.getsize(dest_path):
                                    shutil.move(src_path, dest_path)
                            else:
                                shutil.move(src_path, dest_path)
                            success_count += 1

                        if success_count >= len(items):
                            os.remove(zip_path)
                            shutil.rmtree(extract_dir)
                except Exception as e:
                    print(f"    [!] Zip Error: {e}")

    # Clean up empty subdirectories
    for root, dirs, files in os.walk(LOCAL_STAGING, topdown=False):
        if root == LOCAL_STAGING: continue
        try:
            if not os.listdir(root): os.rmdir(root)
        except:
            pass
    print("[SUCCESS] Staging area is now flat.")


def download_modern_semi_auto():
    print(f"\n{'=' * 60}\n[STEP 3] MODERN SCRAPE (EMERALD DB)\n{'=' * 60}")
    library = get_existing_library()
    driver = setup_driver()
    wait = WebDriverWait(driver, 25)
    current_page = 1

    try:
        driver.get("https://www.emeralddb.org/cards")
        while True:
            print(f"\n>>> [PAGE {current_page}] Scanning Gallery...")
            try:
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/card/']")))
            except:
                print("[!] Gallery didn't load. Please navigate to the cards page in Chrome.")
                input("Press ENTER when cards are visible...")

            # Deduplicate links
            links = list(dict.fromkeys([l.get_attribute('href') for l in driver.find_elements(By.CSS_SELECTOR, "a[href*='/card/']")]))

            for url in links:
                slug = url.split('/')[-1]
                filename = f"LCG_{slug}.jpg"

                if filename.lower() in library or os.path.exists(os.path.join(LOCAL_STAGING, filename)):
                    continue

                print(f"  [VISIT] {slug}")
                driver.get(url)
                try:
                    # Specific EmeraldDB Image Selector
                    wait.until(EC.visibility_of_element_located(
                        (By.CSS_SELECTOR, "img[src*='lcg-cdn'], img[src*='emerald-legacy']")))
                    time.sleep(1)
                    img_elements = driver.find_elements(By.CSS_SELECTOR, "img")

                    target_src = None
                    for img in img_elements:
                        src = img.get_attribute('src')
                        if not src: continue
                        if any(x in src for x in ["lcg-cdn", "emerald-legacy", ".jpg"]):
                            target_src = src
                            break

                    if target_src:
                        if target_src.startswith('/'): target_src = "https://www.emeralddb.org" + target_src

                        # Use browser user agent to bypass basic scrap blockers
                        ua = driver.execute_script("return navigator.userAgent")
                        res = requests.get(target_src, headers={'User-Agent': ua, 'Referer': url}, timeout=15)

                        if res.status_code == 200 and len(res.content) > 5000:
                            with open(os.path.join(LOCAL_STAGING, filename), 'wb') as f:
                                f.write(res.content)
                            print(f"    [SAVE] {filename} ({len(res.content) // 1024} KB)")
                    else:
                        print(f"\n[!!!] FAILED: No card art for {slug}.")
                        input("Press ENTER to skip or fix manually in browser...")
                except Exception as e:
                    print(f"    [!] Error: {e}")
                driver.back()
                time.sleep(1)

            # Auto-Next Logic
            auto_success = False
            try:
                next_buttons = driver.find_elements(By.CSS_SELECTOR, "button")
                for btn in next_buttons:
                    btn_text = btn.text.strip().lower()
                    if (btn_text == "next" or "chevron_right" in btn.get_attribute("innerHTML")) and btn.is_enabled():
                        print(f"\n[SYSTEM] Auto-clicking Next page...")
                        btn.click()
                        auto_success = True
                        break
            except: pass

            if auto_success:
                current_page += 1
                time.sleep(2)
            else:
                print(f"\n[PAUSE] Finished Page {current_page}. Could not find 'Next' button.")
                cmd = input("Navigate to next page in browser and press ENTER to continue (or type 'done' to stop): ").lower()
                if cmd == 'done': break
                current_page += 1
    finally:
        driver.quit()


def master_sync_to_cloud():
    print(f"\n{'=' * 60}\n[STEP 4] MASTER SYNC (LOCAL -> CLOUD)\n{'=' * 60}")
    if not os.path.exists(BASE_PATH):
        os.makedirs(BASE_PATH, exist_ok=True)

    files_to_sync = [f for f in os.listdir(LOCAL_STAGING) if os.path.isfile(os.path.join(LOCAL_STAGING, f))]
    if not files_to_sync:
        print("[INFO] No files to sync.");
        return

    print(f"[SYNC] Moving {len(files_to_sync)} files to rclone mount...")
    count = 0
    for filename in files_to_sync:
        src = os.path.join(LOCAL_STAGING, filename)
        dst = os.path.join(BASE_PATH, filename)
        try:
            # shutil.copy2 preserves metadata
            shutil.copy2(src, dst)
            if os.path.exists(dst):
                os.remove(src)
                count += 1
                if count % 10 == 0: print(f"  Synced {count} files...")
        except Exception as e:
            print(f"  [!] Sync Error on {filename}: {e}")
    print(f"[FINISH] {count} items moved to Cloud.")


def purge_cloud():
    print(f"\n{'=' * 60}\n[STEP 5] PURGING DEAD FILES\n{'=' * 60}")
    count = 0
    if os.path.exists(BASE_PATH):
        for root, _, files in os.walk(BASE_PATH):
            for f in files:
                fp = os.path.join(root, f)
                try:
                    # Remove files under 1KB (likely failed downloads)
                    if os.path.getsize(fp) < 1024:
                        os.remove(fp)
                        count += 1
                except:
                    pass
    print(f"[SUCCESS] Purged {count} dead files from Cloud.")


# ==============================================================
# 4. MAIN MENU
# ==============================================================
def main():
    while True:
        os.system('cls' if IS_WINDOWS else 'clear')
        print("\n" + "#" * 50 + "\n L5R ULTIMATE MANAGER (CROSS-PLATFORM)\n" + "#" * 50)
        print("1. [STEP 1] Download Classic (LOCAL STAGING)")
        print("2. [STEP 2] Flatten & Extract (LOCAL STAGING)")
        print("3. [STEP 3] Scrape Modern (LOCAL STAGING)")
        print("4. [STEP 4] MASTER SYNC (LOCAL -> CLOUD)")
        print("5. [STEP 5] Purge Dead Files (CLOUD)")
        print("0. Exit")

        choice = input("\nSelect Action: ")
        if choice == '1':
            download_classic_local()
        elif choice == '2':
            process_and_flatten_local()
        elif choice == '3':
            download_modern_semi_auto()
        elif choice == '4':
            master_sync_to_cloud()
        elif choice == '5':
            purge_cloud()
        elif choice == '0':
            break
        input("\nPress Enter to return to menu...")


if __name__ == "__main__":
    main()