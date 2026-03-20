import os
import requests
import sqlite3
import time
import threading
import asyncio
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import nodriver as uc

# --- CONFIG ---
BASE_SAVE_DIR = "G:/My Drive/New Cards"
CHECK_FOLDER = "G:/My Drive/Card Database"
DB_FILE = os.path.abspath("skipped_images.sqlite")
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

def display_menu(rows, global_total):
    os.system('cls' if os.name == 'nt' else 'clear')
    print(f"\n {C['header']}  JAPANESE HARVESTER v5.0 (MASTER SYNC)  {C['reset']}")
    print(f" {C['tag']}Total Skips Tracked: {C['val']}{global_total:,}{C['reset']}")
    print(f"{C['line']}═{'═' * 105}{C['reset']}")

    head = f"{'ID':<4} {'TCG CATEGORY':<25} | {'SITE ID':<10} | {'PAGES':<6} | {'LAST RUN'}"
    print(f" {C['bold']}{head}{C['reset']}")
    print(f"{C['line']}{'-'*4}{'-'*26}|{'-'*12}|{'-'*8}|{'-'*20}{C['reset']}")

    for i, (name, lang, sid, pgs, folder, last) in enumerate(rows, 1):
        last = last if last else "Never"
        name_clr = C['green'] if "2026" in last else C['cyan']
        print(f" {C['val']}{i:<3}{C['reset']} {name_clr}{name:<25}{C['reset']} | "
              f"{C['val']}{str(sid):<10}{C['reset']} | "
              f"{C['val']}{str(pgs):<6}{C['reset']} | "
              f"{C['tag']}{last:<18}{C['reset']}")

    print(f"{C['line']}═{'═' * 105}{C['reset']}")
    return input(f" {C['bold']}📂 Select #, {C['green']}'all'{C['reset']}{C['bold']} or 'q': {C['reset']}")

async def run_harvest(site_id, pages, all_skips):
    all_urls = set()
    browser = await uc.start(browser_args=['--window-size=1920,1080'])
    try:
        page = await browser.get("https://tcgrepublic.com/")
        await asyncio.sleep(5)
        for p in range(1, pages + 1):
            url = f"https://tcgrepublic.com/category/category_page_{site_id}.html?p={p}"
            print(f"   {C['bold']}📄 [PAGE {p}/{pages}]{C['reset']} Scanning...")
            await page.get(url)
            try:
                await page.select('li.product_thumbnail', timeout=15)
                await page.scroll_down(1200)
                await asyncio.sleep(2)
                imgs = await page.select_all("li.product_thumbnail img")
                for img in imgs:
                    attrs = img.attributes
                    src = next((attrs[i + 1] for i in range(len(attrs)) if attrs[i] == 'src'), None)
                    if src:
                        full_url = src.replace(".l2_thumbnail.jpg", "")
                        if not full_url.startswith("http"): full_url = "https://tcgrepublic.com" + full_url
                        img_name = full_url.split("/")[-1]
                        if img_name not in all_skips:
                            all_urls.add(full_url)
            except: continue
    finally:
        browser.stop()
    return list(all_urls)

def download_file(url, folder, total):
    global download_counter, new_download_count
    name = url.split("/")[-1]
    path = os.path.join(folder, name)
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        if r.status_code == 200:
            os.makedirs(folder, exist_ok=True)
            with open(path, "wb") as f: f.write(r.content)
            with counter_lock:
                new_download_count += 1
                download_counter += 1
                if download_counter % 5 == 0:
                    print(f"      {C['green']}📥 [DL {download_counter}/{total}] Progressing...{C['reset']}")
    except:
        with counter_lock: download_counter += 1

def process_single_tcg(tcg_data):
    global download_counter, new_download_count
    # Mapping the new tcg_master columns
    name, _, sid, pgs, folder_name, _ = tcg_data

    print(f"\n{C['header']} 🚀 PROCESSING: {name.upper()} {C['reset']}")

    with sqlite3.connect(DB_FILE) as conn:
        db_skips = {r[0] for r in conn.execute(
            "SELECT image_name FROM skipped_images WHERE language = 'japanese' AND game_name = ?", (name,)).fetchall()}

    local_files = set()
    # Uses folder_name from DB instead of display name
    for folder in [CHECK_FOLDER, BASE_SAVE_DIR]:
        p = os.path.join(folder, folder_name)
        if os.path.exists(p): local_files.update(os.listdir(p))

    all_skips = db_skips.union(local_files)
    start_time = time.time()
    download_counter = new_download_count = 0
    urls = asyncio.run(run_harvest(sid, pgs, all_skips))

    if urls:
        total = len(urls)
        print(f" {C['cyan']}📥 Downloading {total} New Photos...{C['reset']}")
        with ThreadPoolExecutor(max_workers=MAX_DOWNLOAD_WORKERS) as exe:
            for u in urls: exe.submit(download_file, u, os.path.join(BASE_SAVE_DIR, folder_name), total)
            while download_counter < total: time.sleep(0.5)

        duration = f"{int(time.time() - start_time)}s"
        now = datetime.now().strftime("%m-%d %H:%M")
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute(
                "UPDATE tcg_master SET last_run=? WHERE tcg_display_name = ? AND language = 'japanese'",
                (now, name))
        print(f" {C['green']}🏁 Finished {name}! Saved {new_download_count}.{C['reset']}")
    else:
        print(f" {C['val']}🟡 No new cards for {name}.{C['reset']}")

def main():
    while True:
        with sqlite3.connect(DB_FILE) as conn:
            # PULLS FROM tcg_master INSTEAD
            rows = conn.execute(
                "SELECT tcg_display_name, language, site_id, total_pages, folder_name, last_run FROM tcg_master WHERE language = 'japanese' ORDER BY tcg_display_name").fetchall()
            global_total = conn.execute("SELECT COUNT(*) FROM skipped_images").fetchone()[0]

        if not rows:
            print("No Japanese TCGs found in tcg_master!")
            break

        choice = display_menu(rows, global_total)
        if choice.lower() == 'q': break
        if choice.lower() in ['all', 'a']:
            for tcg in rows: process_single_tcg(tcg)
            input(f"\n {C['bold']}Press Enter to return...{C['reset']}")
            continue
        try:
            target_tcg = rows[int(choice) - 1]
            process_single_tcg(target_tcg)
            input(f"\n {C['bold']}Press Enter to return...{C['reset']}")
        except: continue

if __name__ == "__main__":
    main()