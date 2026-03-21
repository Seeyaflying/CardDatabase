import os
import time
import sqlite3
import requests
import threading
import asyncio
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import nodriver as uc

# ==============================================================
# 1. PLATFORM DETECTION & PATH CONFIGURATION
# ==============================================================
IS_WINDOWS = os.name == 'nt'

# Database path
DB_FILE = os.path.abspath("skipped_images.sqlite")

if IS_WINDOWS:
    # Windows Native Google Drive Paths
    BASE_SAVE_DIR = r"G:\My Drive\New Cards"
    CHECK_FOLDER = r"G:\My Drive\Card Database"
    CLEAR_CMD = 'cls'
else:
    # Ubuntu Paths (Assumes rclone mount at ~/Desktop/GDrive)
    BASE_SAVE_DIR = os.path.expanduser("~/Desktop/GDrive/New Cards")
    CHECK_FOLDER = os.path.expanduser("~/Desktop/GDrive/Card Database")
    CLEAR_CMD = 'clear'

MAX_DOWNLOAD_WORKERS = 40

# --- COLOR PALETTE ---
C = {
    "header": "\033[48;2;40;44;52m\033[38;2;97;175;239m\033[1m",
    "tag": "\033[38;2;198;120;221m",
    "val": "\033[38;2;229;192;123m",
    "green": "\033[38;2;152;195;121m",
    "cyan": "\033[38;2;86;182;194m",
    "reset": "\033[0m",
    "bold": "\033[1m",
    "line": "\033[38;2;75;82;99m"
}

download_counter = 0
new_download_count = 0
counter_lock = threading.Lock()


# ==============================================================
# 2. UI & UTILITIES
# ==============================================================
def display_menu(rows, global_total):
    os.system(CLEAR_CMD)
    print(f"\n {C['header']}  JAPANESE HARVESTER v5.1 (CROSS-PLATFORM)  {C['reset']}")
    print(f" {C['tag']}Total Skips Tracked: {C['val']}{global_total:,}{C['reset']}")
    print(f"{C['line']}?{'?' * 105}{C['reset']}")

    head = f"{'ID':<4} {'TCG CATEGORY':<25} | {'SITE ID':<10} | {'PAGES':<6} | {'LAST RUN'}"
    print(f" {C['bold']}{head}{C['reset']}")
    print(f"{C['line']}{'-' * 4}{'-' * 26}|{'-' * 12}|{'-' * 8}|{'-' * 20}{C['reset']}")

    for i, (name, lang, sid, pgs, folder, last) in enumerate(rows, 1):
        last_str = last if last else "Never"
        # Highlight if updated in the current year
        name_clr = C['green'] if "2026" in str(last_str) else C['cyan']
        print(f" {C['val']}{i:<3}{C['reset']} {name_clr}{name:<25}{C['reset']} | "
              f"{C['val']}{str(sid):<10}{C['reset']} | "
              f"{C['val']}{str(pgs):<6}{C['reset']} | "
              f"{C['tag']}{last_str:<18}{C['reset']}")

    print(f"{C['line']}?{'?' * 105}{C['reset']}")
    return input(f" {C['bold']}? Select #, {C['green']}'all'{C['reset']}{C['bold']} or 'q': {C['reset']}")


# ==============================================================
# 3. NODRIVER HARVESTING (Scraping)
# ==============================================================
async def run_harvest(site_id, pages, all_skips):
    all_urls = set()

    # Linux-specific flags to prevent "No Sandbox" errors
    browser_args = ['--window-size=1920,1080', '--no-sandbox', '--disable-dev-shm-usage']

    browser = await uc.start(browser_args=browser_args)
    try:
        # Initial handshake
        page = await browser.get("https://tcgrepublic.com/")
        await asyncio.sleep(5)

        for p in range(1, pages + 1):
            url = f"https://tcgrepublic.com/category/category_page_{site_id}.html?p={p}"
            print(f"   {C['bold']}? [PAGE {p}/{pages}]{C['reset']} Scanning...")
            await page.get(url)

            try:
                # Wait for products to appear
                await page.select('li.product_thumbnail', timeout=15)
                await page.scroll_down(1200)
                await asyncio.sleep(2)

                imgs = await page.select_all("li.product_thumbnail img")
                for img in imgs:
                    attrs = img.attributes
                    # Extract 'src' attribute safely
                    src = next((attrs[i + 1] for i in range(len(attrs)) if attrs[i] == 'src'), None)
                    if src:
                        # Clean the URL to get high-res original
                        full_url = src.replace(".l2_thumbnail.jpg", "")
                        if not full_url.startswith("http"):
                            full_url = "https://tcgrepublic.com" + full_url

                        img_name = full_url.split("/")[-1]
                        if img_name not in all_skips:
                            all_urls.add(full_url)
            except Exception:
                continue
    finally:
        browser.stop()
    return list(all_urls)


# ==============================================================
# 4. DOWNLOAD & PROCESSING
# ==============================================================
def download_file(url, folder, total):
    global download_counter, new_download_count
    name = url.split("/")[-1]
    path = os.path.join(folder, name)

    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        if r.status_code == 200:
            if not os.path.exists(folder):
                os.makedirs(folder, exist_ok=True)

            with open(path, "wb") as f:
                file_content = r.content
                f.write(file_content)

            with counter_lock:
                new_download_count += 1
                download_counter += 1
                if download_counter % 5 == 0:
                    print(f"      {C['green']}? [DL {download_counter}/{total}] Progressing...{C['reset']}")
    except:
        with counter_lock:
            download_counter += 1


def process_single_tcg(tcg_data):
    global download_counter, new_download_count
    name, _, sid, pgs, folder_name, _ = tcg_data

    print(f"\n{C['header']} ? PROCESSING: {name.upper()} {C['reset']}")

    # Pull existing skips from DB
    with sqlite3.connect(DB_FILE) as conn:
        db_skips = {r[0] for r in conn.execute(
            "SELECT image_name FROM skipped_images WHERE language = 'japanese' AND game_name = ?", (name,)).fetchall()}

    # Check local folders (rclone mount)
    local_files = set()
    for base_folder in [CHECK_FOLDER, BASE_SAVE_DIR]:
        target_p = os.path.join(base_folder, folder_name)
        if os.path.exists(target_p):
            local_files.update(os.listdir(target_p))

    all_skips = db_skips.union(local_files)
    download_counter = 0
    new_download_count = 0

    # Run the async scraper
    urls = asyncio.run(run_harvest(sid, pgs, all_skips))

    if urls:
        total = len(urls)
        print(f" {C['cyan']}? Downloading {total} New Photos...{C['reset']}")
        with ThreadPoolExecutor(max_workers=MAX_DOWNLOAD_WORKERS) as exe:
            for u in urls:
                exe.submit(download_file, u, os.path.join(BASE_SAVE_DIR, folder_name), total)

            # Simple waiter for thread completion
            while download_counter < total:
                time.sleep(0.5)

        # Update Last Run in DB
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute(
                "UPDATE tcg_master SET last_run=? WHERE tcg_display_name = ? AND language = 'japanese'",
                (now, name))
            conn.commit()

        print(f" {C['green']}? Finished {name}! Saved {new_download_count}.{C['reset']}")
    else:
        print(f" {C['val']}? No new cards for {name}. No folder created.{C['reset']}")


# ==============================================================
# 5. MAIN LOOP
# ==============================================================
def main():
    while True:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT tcg_display_name, language, site_id, total_pages, folder_name, last_run FROM tcg_master WHERE language = 'japanese' ORDER BY tcg_display_name").fetchall()
            global_total = conn.execute("SELECT COUNT(*) FROM skipped_images").fetchone()[0]

        if not rows:
            print("No Japanese TCGs found in tcg_master!")
            break

        choice = display_menu(rows, global_total)
        if choice.lower() == 'q': break

        if choice.lower() in ['all', 'a']:
            for tcg in rows:
                process_single_tcg(tcg)
            input(f"\n {C['bold']}Batch complete. Press Enter to return...{C['reset']}")
            continue

        try:
            target_tcg = rows[int(choice) - 1]
            process_single_tcg(target_tcg)
            input(f"\n {C['bold']}Press Enter to return...{C['reset']}")
        except (ValueError, IndexError):
            continue


if __name__ == "__main__":
    main()