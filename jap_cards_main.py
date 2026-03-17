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

# Global Trackers
download_counter = 0
new_download_count = 0
counter_lock = threading.Lock()

# --- 1. THE ENGINE ---

def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS jap_tcgs
                        (tcg_name TEXT PRIMARY KEY, site_id INTEGER, total_pages INTEGER,
                         last_run TEXT, last_duration TEXT, lifetime_dl INTEGER DEFAULT 0)""")

def display_menu(rows, global_total):
    os.system('cls' if os.name == 'nt' else 'clear')
    print(f"\n {C['header']}  JAPANESE CARD HARVESTER v4.0 (READ-ONLY)  {C['reset']}")
    print(f" {C['tag']}Manual Skips Tracked: {C['val']}{global_total:,}{C['reset']} records")
    print(f"{C['line']}═{'═' * 105}{C['reset']}")

    head = f"{'ID':<4} {'TCG CATEGORY':<20} | {'SITE ID':<10} | {'PAGES':<6} | {'LAST RUN':<18} | {'DUR':<6} | {'LIFETIME'}"
    print(f" {C['bold']}{head}{C['reset']}")
    print(f"{C['line']}----{'--------------------'}---{'----------'}---{'------'}---{'------------------'}---{'------'}---{'----------'}{C['reset']}")

    for i, (name, pgs, sid, last, dur, life) in enumerate(rows, 1):
        display_name = (name[:17] + "..") if len(name) > 20 else name
        last = last if last else "Never"
        dur = dur if dur else "0s"
        name_clr = C['green'] if "2026" in last else C['cyan']

        print(f" {C['val']}{i:<3}{C['reset']} "
              f"{name_clr}{display_name:<20}{C['reset']} | "
              f"{C['val']}{str(sid):<10}{C['reset']} | "
              f"{C['val']}{str(pgs):<6}{C['reset']} | "
              f"{C['tag']}{last:<18}{C['reset']} | "
              f"{C['val']}{dur:<6}{C['reset']} | "
              f"{C['green']}{str(life):<10}{C['reset']}")

    print(f"{C['line']}═{'═' * 105}{C['reset']}")
    return input(f" {C['bold']}📂 Select TCG # (or 'q'): {C['reset']}")

async def run_harvest(site_id, pages, all_skips):
    all_urls = set()
    browser = await uc.start(browser_args=['--window-size=1920,1080'])
    try:
        page = await browser.get("https://tcgrepublic.com/")
        await asyncio.sleep(8)
        for p in range(1, pages + 1):
            url = f"https://tcgrepublic.com/category/category_page_{site_id}.html?p={p}"
            print(f"\n   {C['bold']}📄 [PAGE {p}/{pages}]{C['reset']} Scanning: {url}")
            await page.get(url)
            try:
                await page.select('li.product_thumbnail', timeout=15)
                await page.scroll_down(1200)
                await asyncio.sleep(3)
                imgs = await page.select_all("li.product_thumbnail img")
                for idx, img in enumerate(imgs, 1):
                    attrs = img.attributes
                    src = next((attrs[i + 1] for i in range(len(attrs)) if attrs[i] == 'src'), None)
                    if src:
                        full_url = src.replace(".l2_thumbnail.jpg", "")
                        if not full_url.startswith("http"): full_url = "https://tcgrepublic.com" + full_url
                        img_name = full_url.split("/")[-1]
                        if img_name in all_skips:
                            print(f"      {C['line']}🏛️  Skip: {img_name}{C['reset']}")
                        else:
                            all_urls.add(full_url)
                            print(f"      {C['green']}✨ Found New: {img_name}{C['reset']}")
            except: continue
    finally: browser.stop()
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
                new_download_count += 1; download_counter += 1
                print(f"      {C['green']}📥 [DL {download_counter}/{total}] Saved: {name}{C['reset']}")
    except:
        with counter_lock: download_counter += 1

def main():
    global download_counter, new_download_count
    init_db()
    while True:
        with sqlite3.connect(DB_FILE) as conn:
            rows = conn.execute("SELECT tcg_name, total_pages, site_id, last_run, last_duration, lifetime_dl FROM jap_tcgs ORDER BY tcg_name").fetchall()
            global_total = conn.execute("SELECT COUNT(*) FROM skipped_images").fetchone()[0]

        choice = display_menu(rows, global_total)
        if choice.lower() == 'q': break
        try:
            name, pgs, sid, _, _, _ = rows[int(choice) - 1]
        except: continue

        print(f"\n {C['cyan']}📊 Analyzing {name} Storage...{C['reset']}")
        with sqlite3.connect(DB_FILE) as conn:
            # READ ONLY: Filters by Game Name and Language
            db_skips = {r[0] for r in conn.execute("SELECT image_name FROM skipped_images WHERE language = 'japanese' AND game_name = ?", (name,)).fetchall()}

        local_files = set()
        for folder in [CHECK_FOLDER, BASE_SAVE_DIR]:
            p = os.path.join(folder, name)
            if os.path.exists(p): local_files.update(os.listdir(p))

        all_skips = db_skips.union(local_files)
        print(f"   ├─ Database Archive (Banned): {len(db_skips):,}\n   ├─ Local Folders:            {len(local_files):,}\n   └─ Total Skip List:           {C['bold']}{len(all_skips):,}{C['reset']}")

        start_time = time.time()
        download_counter = new_download_count = 0
        urls = asyncio.run(run_harvest(sid, pgs, all_skips))

        if urls:
            total = len(urls)
            print(f"\n {C['cyan']}📥 Downloading {total} New Photos...{C['reset']}")
            with ThreadPoolExecutor(max_workers=MAX_DOWNLOAD_WORKERS) as exe:
                for u in urls: exe.submit(download_file, u, os.path.join(BASE_SAVE_DIR, name), total)
                while download_counter < total: time.sleep(0.5)

            duration = int(time.time() - start_time)
            now = datetime.now().strftime("%m-%d %H:%M")
            with sqlite3.connect(DB_FILE) as conn:
                conn.execute("UPDATE jap_tcgs SET last_run=?, last_duration=?, lifetime_dl=lifetime_dl + ? WHERE tcg_name = ?",
                             (now, f"{duration}s", new_download_count, name))
            print(f"\n {C['green']}🏁 Finished! Downloaded {new_download_count} cards.{C['reset']}")
        else: print(f"\n {C['val']}🟡 No new cards found today.{C['reset']}")
        input(f"\n {C['bold']}Press Enter to return...{C['reset']}")

if __name__ == "__main__":
    main()