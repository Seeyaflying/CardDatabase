import asyncio
import aiohttp
import aiofiles
import os
import re
import sqlite3
import time
import traceback
from tqdm.asyncio import tqdm
from datetime import datetime

# ==============================================================
# CONFIGURATION SECTION
# ==============================================================
DB_FILE = os.path.abspath("skipped_images.sqlite")
SAVE_ROOT = "G:/My Drive/New Cards"
CHECK_ROOT = "G:/My Drive/Card Database"
MAX_CONCURRENT_DOWNLOADS = 25  # Parallel download limit

# --- COLOR PALETTE ---
C = {
    "header": "\033[48;2;40;44;52m\033[38;2;97;175;239m\033[1m",
    "tag": "\033[38;2;198;120;221m",
    "val": "\033[38;2;229;192;123m",
    "green": "\033[38;2;152;195;121m",
    "cyan": "\033[38;2;86;182;194m",
    "reset": "\033[0m",
    "bold": "\033[1m",
    "line": "\033[38;2;75;82;99m",
    "skip": "\033[38;2;120;120;120m"
}

# Global Counter
new_dl_count = 0
counter_lock = asyncio.Lock()

# ==============================================================
# DATABASE HELPERS
# ==============================================================
def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS eng_tcgs
                        (tcg_name TEXT PRIMARY KEY,site_id INTEGER,total_pages INTEGER,
                         last_run TEXT,last_duration TEXT,lifetime_dl INTEGER DEFAULT 0)""")

        # Initial Seed of your TCG IDs
        count = conn.execute("SELECT COUNT(*) FROM eng_tcgs").fetchone()[0]
        if count == 0:
            seed_data = [
                ('Akora', 75), ("Alpha Clash", 78), ('Argent Saga', 61), ('Bakugan', 58),
                ('Battle Spirits Saga', 72), ('Cardfight Vanguard', 16), ('Caster Chronicles', 37),
                ("Chrono Clash System", 60), ("Dice Masters", 18), ("Digimon", 63), ("DBZ TCG", 23),
                ("DBZ Super", 27), ("DBZ Super Fusion World", 80), ("Dragoborne", 28), ("Elestrals", 83),
                ("Final Fantasy", 24), ("Flesh and Blood", 62), ("Force of Will", 17),
                ("Future Card BuddyFight", 19), ("Gate Ruler", 65), ("Godzilla Card Game", 88),
                ("Grand Archive", 74), ("Gundam", 86), ("Hololive", 87), ("Kryptik", 76),
                ("Lightseekers", 48), ("Lorcana", 71), ("MetaX", 30), ("MetaZoo", 66),
                ("Munchkin", 53), ("One Piece", 68), ("Pokemon", 3), ("Riftbound", 89),
                ("Shadowverse Evolve", 73), ("Sorcery Contested Realm", 77), ("Star Wars Destiny", 26),
                ("Star Wars Unlimited", 79), ("Transformers", 57), ("Union Arena", 81),
                ("UniVersus", 25), ("Warhammer Age of Sigmar Champions", 54), ("Weiss Schwarz", 20),
                ("Wixoss", 67), ("World of Warcraft", 13), ("Yugioh", 2), ("Zombie World Order", 36)
            ]
            conn.executemany("INSERT INTO eng_tcgs (tcg_name, site_id, total_pages) VALUES (?, ?, 0)", seed_data)
            conn.commit()

def display_menu(rows, global_total):
    os.system('cls' if os.name == 'nt' else 'clear')
    print(f"\n {C['header']}  ENGLISH TCG HARVESTER v4.5 (VERBOSE DEBUG)  {C['reset']}")
    print(f" {C['tag']}Banned Cards Tracked: {C['val']}{global_total:,}{C['reset']} records")
    print(f"{C['line']}═{'═' * 105}{C['reset']}")

    head = f"{'ID':<4} {'TCG CATEGORY':<25} | {'SITE ID':<10} | {'LAST RUN':<18} | {'DUR':<6} | {'LIFETIME'}"
    print(f" {C['bold']}{head}{C['reset']}")
    print(f"{C['line']}{'-'*4}{'-'*26}|{'-'*12}|{'-'*20}|{'-'*8}|{'-'*10}{C['reset']}")

    for i, (name, sid, last, dur, life) in enumerate(rows, 1):
        last = last if last else "Never"
        name_clr = C['green'] if "2026" in last else C['cyan']
        print(f" {C['val']}{i:<3}{C['reset']} {name_clr}{name:<25}{C['reset']} | "
              f"{C['val']}{str(sid):<10}{C['reset']} | {C['tag']}{last:<18}{C['reset']} | "
              f"{C['val']}{dur if dur else '0s':<6}{C['reset']} | {C['green']}{life:<10,}{C['reset']}")

    print(f"{C['line']}═{'═' * 105}{C['reset']}")
    return input(f" {C['bold']}📂 Select #, {C['green']}'all'{C['reset']}{C['bold']} or 'q': {C['reset']}")

# ==============================================================
# ASYNC HARVESTING LOGIC
# ==============================================================
async def fetch_json(session, url):
    try:
        async with session.get(url, timeout=15) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get('results', [])
    except: return []
    return []

async def download_image(session, image_url, save_folder, image_name, skipped_ids, existing_filenames, semaphore):
    global new_dl_count
    async with semaphore:
        # Extract numeric ID for DB checking
        id_match = re.search(r'(\d+)', image_name)
        img_id = id_match.group(1) if id_match else image_name

        # Check against DB Bans
        if img_id in skipped_ids or f"{img_id}_200w" in skipped_ids:
            print(f"      {C['skip']}🏛️  Skip (Banned): {img_id}{C['reset']}")
            return

        # Check against local folders (Silent skip to keep UI clean)
        if image_name in existing_filenames:
            return

        # Perform the actual download
        image_path = os.path.join(save_folder, image_name)
        try:
            async with session.get(image_url, timeout=20) as response:
                if response.status == 200:
                    data = await response.read()
                    async with aiofiles.open(image_path, 'wb') as f:
                        await f.write(data)
                    async with counter_lock:
                        new_dl_count += 1
                        print(f"      {C['green']}📥 Downloaded: {image_name}{C['reset']}")
        except: pass

async def process_tcg(session, name, tcg_id):
    global new_dl_count
    new_dl_count = 0
    start_time = time.time()

    print(f"\n{C['header']} 🚀 PROCESSING: {name.upper()} {C['reset']}")

    # 1. STORAGE ANALYSIS
    with sqlite3.connect(DB_FILE) as conn:
        skipped_ids = {str(row[0]) for row in conn.execute(
            "SELECT image_name FROM skipped_images WHERE language='english' AND game_name=?", (name,)).fetchall()}

    save_dir = os.path.join(SAVE_ROOT, name)
    check_dir = os.path.join(CHECK_ROOT, name)
    os.makedirs(save_dir, exist_ok=True)

    existing_files = set()
    for path in [save_dir, check_dir]:
        if os.path.exists(path): existing_files.update(os.listdir(path))

    print(f"   {C['cyan']}📊 Storage Check:{C['reset']} Banned: {len(skipped_ids):,} | Local: {len(existing_files):,}")

    # 2. GROUP FETCHING
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
    print(f"   {C['tag']}🔗 Connecting to TCGPlayer API...{C['reset']}")
    groups_data = await fetch_json(session, f'https://tcgcsv.com/tcgplayer/{tcg_id}/groups')
    print(f"   {C['tag']}📂 Found {len(groups_data)} Sets/Groups.{C['reset']}")

    # 3. SET-BY-SET SCANNING
    for group in groups_data:
        group_id = group.get('groupId')
        group_name = group.get('name', 'Unknown')
        if not group_id: continue

        print(f"\n   {C['bold']}📄 Scanning:{C['reset']} {group_name}")

        products = await fetch_json(session, f'https://tcgcsv.com/tcgplayer/{tcg_id}/{group_id}/products')

        tasks = []
        for item in products:
            img_url = item.get('imageUrl')
            if img_url:
                img_name = img_url.split('/')[-1]
                tasks.append(download_image(session, img_url, save_dir, img_name, skipped_ids, existing_files, semaphore))

        if tasks:
            await asyncio.gather(*tasks)
        else:
            print(f"      {C['line']}No products found in this set.{C['reset']}")

    # 4. FINAL LOGGING
    duration = int(time.time() - start_time)
    now = datetime.now().strftime("%m-%d %H:%M")
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("UPDATE eng_tcgs SET last_run=?, last_duration=?, lifetime_dl=lifetime_dl + ? WHERE tcg_name = ?",
                     (now, f"{duration}s", new_dl_count, name))

    print(f"\n {C['green']}🏁 Finished {name}! Saved {new_dl_count} new images.{C['reset']}")

async def main_async():
    init_db()
    async with aiohttp.ClientSession(headers={'User-Agent': 'Mozilla/5.0'}) as session:
        while True:
            with sqlite3.connect(DB_FILE) as conn:
                rows = conn.execute("SELECT tcg_name, site_id, last_run, last_duration, lifetime_dl FROM eng_tcgs ORDER BY tcg_name").fetchall()
                global_total = conn.execute("SELECT COUNT(*) FROM skipped_images").fetchone()[0]

            choice = display_menu(rows, global_total)
            if choice.lower() == 'q': break

            if choice.lower() in ['all', 'a']:
                print(f"\n {C['tag']}🌟 Starting Batch Run for {len(rows)} TCGs...{C['reset']}")
                for tcg in rows:
                    await process_tcg(session, tcg[0], tcg[1])
                print(f"\n {C['header']} ✨ ALL TCGs UPDATED ✨ {C['reset']}")
                input("Press [Enter] to return to menu...")
                continue

            try:
                target = rows[int(choice) - 1]
                await process_tcg(session, target[0], target[1])
                input("\nPress [Enter] to return...")
            except: continue

if __name__ == '__main__':
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt: pass
    except Exception: traceback.print_exc()