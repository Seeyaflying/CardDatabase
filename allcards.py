import asyncio
import aiohttp
import aiofiles
import os
import sqlite3
import time
import traceback
from datetime import datetime

# ==============================================================
# CONFIGURATION SECTION
# ==============================================================
DB_FILE = os.path.abspath("skipped_images.sqlite")
SAVE_ROOT = "G:/My Drive/New Cards"
CHECK_ROOT = "G:/My Drive/Card Database"
MAX_CONCURRENT_DOWNLOADS = 30

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

new_dl_count = 0
counter_lock = asyncio.Lock()


def display_menu(rows, global_total):
    os.system('cls' if os.name == 'nt' else 'clear')
    print(f"\n {C['header']}  ENGLISH TCG HARVESTER v5.1 (CLEAN FOLDERS)  {C['reset']}")
    print(f" {C['tag']}Total Banned Tracks: {C['val']}{global_total:,}{C['reset']} records")
    print(f"{C['line']}═{'═' * 105}{C['reset']}")

    head = f"{'ID':<4} {'TCG CATEGORY':<25} | {'SITE ID':<10} | {'LAST RUN':<18} | {'FOLDER'}"
    print(f" {C['bold']}{head}{C['reset']}")
    print(f"{C['line']}{'-' * 4}{'-' * 26}|{'-' * 12}|{'-' * 20}|{'-' * 20}{C['reset']}")

    for i, r in enumerate(rows, 1):
        name = r['tcg_display_name']
        sid = r['site_id']
        last = r['last_run'] if r['last_run'] else "Never"
        folder = r['folder_name']
        name_clr = C['green'] if "2026" in last else C['cyan']
        print(f" {C['val']}{i:<3}{C['reset']} {name_clr}{name:<25}{C['reset']} | "
              f"{C['val']}{str(sid):<10}{C['reset']} | {C['tag']}{last:<18}{C['reset']} | "
              f"{C['skip']}{folder:<20}{C['reset']}")

    print(f"{C['line']}═{'═' * 105}{C['reset']}")
    return input(f" {C['bold']}📂 Select #, {C['green']}'all'{C['reset']}{C['bold']} or 'q': {C['reset']}")


async def fetch_json(session, url):
    try:
        async with session.get(url, timeout=15) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get('results', [])
    except:
        return []
    return []


async def download_image(session, image_url, save_folder, image_name, skipped_ids, existing_filenames, semaphore):
    global new_dl_count
    async with semaphore:
        if image_name in skipped_ids or image_name in existing_filenames:
            return

        image_path = os.path.join(save_folder, image_name)
        try:
            async with session.get(image_url, timeout=20) as response:
                if response.status == 200:
                    # ONLY CREATE FOLDER IF WE HAVE A VALID DOWNLOAD
                    if not os.path.exists(save_folder):
                        os.makedirs(save_folder, exist_ok=True)

                    data = await response.read()
                    async with aiofiles.open(image_path, 'wb') as f:
                        await f.write(data)
                    async with counter_lock:
                        new_dl_count += 1
                        print(f"      {C['green']}📥 Downloaded: {image_name}{C['reset']}")
        except:
            pass


async def process_tcg(session, row):
    global new_dl_count
    new_dl_count = 0
    name = row['tcg_display_name']
    sid = row['site_id']
    folder_name = row['folder_name']

    print(f"\n{C['header']} 🚀 PROCESSING: {name.upper()} ({folder_name}) {C['reset']}")

    with sqlite3.connect(DB_FILE) as conn:
        skipped_ids = {str(r[0]) for r in conn.execute(
            "SELECT image_name FROM skipped_images WHERE language='english' AND game_name=?", (name,)).fetchall()}

    save_dir = os.path.join(SAVE_ROOT, folder_name)
    check_dir = os.path.join(CHECK_ROOT, folder_name)

    existing_files = set()
    for path in [save_dir, check_dir]:
        if os.path.exists(path): existing_files.update(os.listdir(path))

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
    groups_data = await fetch_json(session, f'https://tcgcsv.com/tcgplayer/{sid}/groups')

    for group in groups_data:
        group_id = group.get('groupId')
        if not group_id: continue

        products = await fetch_json(session, f'https://tcgcsv.com/tcgplayer/{sid}/{group_id}/products')
        tasks = []
        for item in products:
            img_url = item.get('imageUrl')
            if img_url:
                img_name = img_url.split('/')[-1]
                tasks.append(
                    download_image(session, img_url, save_dir, img_name, skipped_ids, existing_files, semaphore))

        if tasks: await asyncio.gather(*tasks)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("UPDATE tcg_master SET last_run=? WHERE tcg_display_name = ? AND language = 'english'",
                     (now, name))
        conn.commit()

    if new_dl_count > 0:
        print(f"\n {C['green']}🏁 Finished {name}! Saved {new_dl_count} new images.{C['reset']}")
    else:
        print(f"\n {C['val']}🟡 No new cards for {name}. Folder not touched.{C['reset']}")


async def main_async():
    async with aiohttp.ClientSession(headers={'User-Agent': 'Mozilla/5.0'}) as session:
        while True:
            with sqlite3.connect(DB_FILE) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT * FROM tcg_master WHERE language = 'english' ORDER BY tcg_display_name").fetchall()
                global_total = conn.execute("SELECT COUNT(*) FROM skipped_images").fetchone()[0]

            if not rows: break

            choice = display_menu(rows, global_total)
            if choice.lower() == 'q': break
            if choice.lower() in ['all', 'a']:
                for tcg_row in rows: await process_tcg(session, tcg_row)
                input("\nBatch Run Complete. Press [Enter]...")
                continue
            try:
                target_row = rows[int(choice) - 1]
                await process_tcg(session, target_row)
                input("\nPress [Enter] to return...")
            except:
                continue


if __name__ == '__main__':
    try:
        asyncio.run(main_async())
    except (KeyboardInterrupt, Exception):
        traceback.print_exc()