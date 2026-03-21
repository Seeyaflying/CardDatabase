import os
import time
import requests
import gdown
import zipfile
import shutil
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# --- CONFIGURATION ---
BASE_PATH = r"G:\My Drive\New Cards\Legend of the Five Rings"
DATABASE_PATH = r"G:\My Drive\Database\Legend of the Five Rings"
LOCAL_STAGING = os.path.join(os.getcwd(), "L5R_Staging")
PROFILE_DIR = os.path.join(os.getcwd(), "ScraperProfile")


def setup_driver():
    print(f"\n[SYSTEM] Initializing Compact Browser (1024x768)...")
    chrome_options = Options()
    chrome_options.add_argument(f"--user-data-dir={PROFILE_DIR}")
    chrome_options.add_argument("--profile-directory=Default")
    chrome_options.add_argument("--window-size=1024,768")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    return driver


def get_existing_library():
    print("\n--- [INDEX] SCANNING ALL LOCATIONS FOR EXISTING CARDS ---")
    existing = set()
    for path in [LOCAL_STAGING, BASE_PATH, DATABASE_PATH]:
        if os.path.exists(path):
            for root, _, files in os.walk(path):
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        if os.path.getsize(fp) > 5000:
                            existing.add(f.lower())
                    except:
                        pass
    print(f"  [RESULT] Found {len(existing)} unique valid cards in your collection.")
    return existing


# --- STEP 1: DOWNLOAD CLASSIC ---
def download_classic_local():
    print(f"\n{'=' * 60}\n[STEP 1] DOWNLOADING ARCHIVE TO LOCAL STAGING\n{'=' * 60}")
    drive_url = "https://drive.google.com/drive/folders/1nw_--s3Nsynczf1yFkogmGrMCaIg_Xrx"
    os.makedirs(LOCAL_STAGING, exist_ok=True)
    print("[NETWORK] Connecting to Google Drive Archive...")
    try:
        gdown.download_folder(url=drive_url, output=LOCAL_STAGING, quiet=False, remaining_ok=True)
        print("[SUCCESS] Local staging updated.")
    except Exception as e:
        print(f"[ERROR] Drive download failed: {e}")


# --- STEP 2: SAFE LOCAL FLATTEN ---
def process_and_flatten_local():
    print(f"\n{'=' * 60}\n[STEP 2] SAFE EXTRACTION & VERIFIED FLATTENING\n{'=' * 60}")
    if not os.path.exists(LOCAL_STAGING): return

    for root, _, files in os.walk(LOCAL_STAGING):
        for f in files:
            if f.lower().endswith(".zip"):
                zip_path = os.path.join(root, f)
                print(f"\n  [ZIP] Inspecting: {f}")
                try:
                    with zipfile.ZipFile(zip_path, 'r') as z:
                        extract_dir = os.path.join(root, f"_extracted_{int(time.time())}")
                        z.extractall(extract_dir)
                        extracted_files = z.namelist()
                        success_count = 0

                        for ext_f in extracted_files:
                            if ext_f.endswith(('/', '\\')): continue
                            src_path = os.path.join(extract_dir, ext_f)
                            dest_filename = os.path.basename(ext_f)
                            dest_path = os.path.join(LOCAL_STAGING, dest_filename)

                            if os.path.exists(dest_path):
                                if os.path.getsize(src_path) > os.path.getsize(dest_path):
                                    shutil.move(src_path, dest_path)
                                success_count += 1
                            else:
                                shutil.move(src_path, dest_path)
                                success_count += 1

                        if success_count >= len([x for x in extracted_files if not x.endswith(('/', '\\'))]):
                            os.remove(zip_path)
                            shutil.rmtree(extract_dir)
                except Exception as e:
                    print(f"    [!] Zip Error: {e}")

    for root, dirs, files in os.walk(LOCAL_STAGING, topdown=False):
        if root == LOCAL_STAGING: continue
        try:
            if not os.listdir(root): os.rmdir(root)
        except:
            pass
    print("[SUCCESS] Staging area is now verified and flat.")


# --- STEP 3: MODERN SCRAPE ---
def download_modern_semi_auto():
    print(f"\n{'=' * 60}\n[STEP 3] MODERN SCRAPE: STUBBORN FAIL-PAUSE\n{'=' * 60}")
    library = get_existing_library()
    driver = setup_driver()
    wait = WebDriverWait(driver, 25)
    current_page = 1

    try:
        driver.get("https://www.emeralddb.org/cards")
        while True:
            print(f"\n>>> [PAGE {current_page}] Scanning Gallery...")
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/card/']")))
            links = list(dict.fromkeys(
                [l.get_attribute('href') for l in driver.find_elements(By.CSS_SELECTOR, "a[href*='/card/']")]))

            for url in links:
                slug = url.split('/')[-1]
                filename = f"LCG_{slug}.jpg"
                if filename.lower() in library or os.path.exists(os.path.join(LOCAL_STAGING, filename)): continue

                print(f"  [VISIT] {slug}")
                driver.get(url)
                try:
                    wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "div.MuiGrid-grid-xs-12 img")))
                    time.sleep(1)
                    img_elements = driver.find_elements(By.CSS_SELECTOR, "div.MuiGrid-grid-xs-12 img")

                    target_src = None
                    for idx, img in enumerate(img_elements):
                        src = img.get_attribute('src')
                        if any(x in src for x in ["logo.webp", "static", "favicon", "neutral.svg"]): continue
                        if any(x in src for x in ["lcg-cdn", "image-proxy", "emerald-legacy", ".jpg"]):
                            target_src = src
                            break

                    if target_src:
                        if target_src.startswith('/'): target_src = "https://www.emeralddb.org" + target_src
                        res = requests.get(target_src,
                                           headers={'User-Agent': driver.execute_script("return navigator.userAgent"),
                                                    'Referer': url}, timeout=15)
                        if res.status_code == 200 and len(res.content) > 5000:
                            with open(os.path.join(LOCAL_STAGING, filename), 'wb') as f:
                                f.write(res.content)
                            print(f"    [SAVE] {filename} ({len(res.content) // 1024} KB)")
                        else:
                            print(f"    [!] File rejected (Size: {len(res.content)})")
                    else:
                        print(f"\n[!!!] FAILED: No card art for {slug}. Inspect browser.")
                        input("Press ENTER to continue...")
                except Exception as e:
                    print(f"    [!] Error: {e}")
                driver.back();
                time.sleep(1)

            print(f"\nPAGE {current_page} DONE. Click 'Next' in Chrome.")
            if input("Next? (Enter/done): ").lower() == 'done': break
            current_page += 1
    finally:
        driver.quit()


# --- STEP 4: MASTER SYNC ---
def master_sync_to_cloud():
    print(f"\n{'=' * 60}\n[STEP 4] MASTER SYNC: INDIVIDUAL MOVE & VERIFY\n{'=' * 60}")
    if not os.path.exists(BASE_PATH):
        print(f"[DIRECTORY] Creating destination: {BASE_PATH}")
        os.makedirs(BASE_PATH, exist_ok=True)

    if not os.path.exists(LOCAL_STAGING) or not os.listdir(LOCAL_STAGING):
        print("[INFO] Local Staging is empty.");
        return

    files_to_sync = [f for f in os.listdir(LOCAL_STAGING) if os.path.isfile(os.path.join(LOCAL_STAGING, f))]
    print(f"[SYNC] Moving {len(files_to_sync)} files...")

    count = 0
    for filename in files_to_sync:
        src_path, dst_path = os.path.join(LOCAL_STAGING, filename), os.path.join(BASE_PATH, filename)
        try:
            shutil.copy2(src_path, dst_path)
            if os.path.exists(dst_path):
                print(f"  [>>] SYNCED & PURGED: {filename}")
                os.remove(src_path)
                count += 1
        except Exception as e:
            print(f"  [!] Error: {e}")
    print(f"\n[FINISH] {count} items moved to Cloud.")


# --- STEP 5: PURGE ---
def purge_cloud():
    print(f"\n{'=' * 60}\n[STEP 5] PURGING DEAD FILES\n{'=' * 60}")
    count = 0
    if os.path.exists(BASE_PATH):
        for root, _, files in os.walk(BASE_PATH):
            for f in files:
                fp = os.path.join(root, f)
                if os.path.getsize(fp) < 1024:
                    os.remove(fp);
                    count += 1
    print(f"[SUCCESS] Purged {count} dead files.")


def main():
    while True:
        print("\n" + "#" * 50 + "\n L5R ULTIMATE MANAGER\n" + "#" * 50)
        print(
            "1. [STEP 1] Download Classic (LOCAL)\n2. [STEP 2] Flatten & Extract (LOCAL)\n3. [STEP 3] Scrape Modern (LOCAL)\n4. [STEP 4] MASTER SYNC (LOCAL -> CLOUD)\n5. [STEP 5] Purge Dead Files (CLOUD)\n0. Exit")
        choice = input("\nSelect: ")
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


if __name__ == "__main__":
    main()