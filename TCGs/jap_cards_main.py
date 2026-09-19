import os
import time
import sys
import sqlite3
import json
import requests
import threading
import asyncio
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import nodriver as uc

# Make config/db importable from Utilities/
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Utilities"))
import config
import db


# ==============================================================
# 1. PLATFORM DETECTION & PATH CONFIGURATION
# ==============================================================
IS_WINDOWS = os.name == 'nt'

if IS_WINDOWS:
    # G: drive is local to this machine, so it works with the VPN on
    BASE_SAVE_DIR = r"G:\My Drive\New Cards"          # new downloads land here
    CHECK_FOLDER = r"G:\My Drive\Card Database"        # existing files checked here
    CLEAR_CMD = 'cls'
else:
    BASE_SAVE_DIR = os.path.expanduser("~/Desktop/GDrive/New Cards")
    CHECK_FOLDER = os.path.expanduser("~/Desktop/GDrive/Card Database")
    CLEAR_CMD = 'clear'

MAX_DOWNLOAD_WORKERS = 20   # respects the site's rate limit

LOCAL_MIRROR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jap_local_mirror.db")

# --- Vivaldi / Chrome executable detection ---
def find_browser():
    candidates = [
        r"C:\Program Files\Vivaldi\Application\vivaldi.exe",
        r"C:\Program Files (x86)\Vivaldi\Application\vivaldi.exe",
        os.path.expanduser(r"~\AppData\Local\Vivaldi\Application\vivaldi.exe"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None

BROWSER_PATH = find_browser()

# --- COLOR PALETTE (Matrix green) ---
C = {
    "header": "\033[38;2;0;255;65m\033[1m",
    "tag": "\033[38;2;0;255;65m",
    "val": "\033[38;2;0;255;65m",
    "green": "\033[38;2;0;255;65m",
    "dim": "\033[38;2;0;143;17m",
    "cyan": "\033[38;2;0;255;65m",
    "reset": "\033[0m",
    "bold": "\033[1m",
    "line": "\033[38;2;0;143;17m"
}

download_counter = 0
new_download_count = 0
counter_lock = threading.Lock()
print_lock = threading.Lock()


def feed(msg):
    """Print one line of the live feed, serialized so threads don't garble."""
    with print_lock:
        print(f" {C['green']}>>{C['reset']} {msg}", flush=True)


def skipped_coll():
    return db.get_db()[config.SKIPPED_IMAGES_COLLECTION]

def progress_coll():
    return db.get_db()[config.PROGRESS_COLLECTION]

def tcg_master_coll():
    return db.get_db()[config.TCG_MASTER_COLLECTION]


# ==============================================================
# 1b. LOCAL MIRROR (skipped_images + tcg_master)
# ==============================================================
def _local_conn():
    conn = sqlite3.connect(LOCAL_MIRROR)
    conn.execute("""CREATE TABLE IF NOT EXISTS skipped_images (
        _id TEXT PRIMARY KEY, data TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS tcg_master (
        _id TEXT PRIMARY KEY, data TEXT)""")
    return conn


def export_local():
    """Copy skipped_images + tcg_master from Mongo into local SQLite (batched)."""
    print("\n[1/3] Exporting collections to local copy...")
    client = db.get_db()
    conn = _local_conn()

    for coll_name, table in (("skipped_images", "skipped_images"),
                             ("tcg_master", "tcg_master")):
        coll = client[coll_name]
        total = coll.count_documents({})
        print(f"  Exporting {coll_name} ({total} docs)...")
        count = 0
        batch = 0
        for doc in coll.find():
            doc_id = str(doc["_id"])
            payload = {k: v for k, v in doc.items() if k != "_id"}
            payload = json.loads(json.dumps(payload, default=str))
            conn.execute(
                f"INSERT OR REPLACE INTO {table} (_id, data) VALUES (?, ?)",
                (doc_id, json.dumps(payload)))
            count += 1
            batch += 1
            if batch >= 10000:
                conn.commit()
                batch = 0
            if count % 2000 == 0:
                print(f"    {count} docs...", flush=True)
        conn.commit()
        print(f"  Done: {coll_name} ({count} docs)")

    conn.close()
    print("  Local copy ready.\n")


def local_skipped_images():
    """Return set of image_names already skipped, from local copy."""
    conn = _local_conn()
    rows = conn.execute("SELECT data FROM skipped_images").fetchall()
    conn.close()
    names = set()
    for (data,) in rows:
        doc = json.loads(data)
        name = doc.get("image_name")
        if name:
            names.add(name)
    return names


def local_skipped_count():
    conn = _local_conn()
    n = conn.execute("SELECT COUNT(*) FROM skipped_images").fetchone()[0]
    conn.close()
    return n


def local_tcg_master_rows():
    """Return Japanese rows from the local tcg_master copy."""
    conn = _local_conn()
    rows = conn.execute("SELECT data FROM tcg_master").fetchall()
    conn.close()
    out = []
    for (data,) in rows:
        doc = json.loads(data)
        if doc.get("language") == "japanese":
            out.append((doc.get("tcg_display_name"), "japanese",
                        doc.get("site_id"), doc.get("total_pages", 0),
                        doc.get("folder_name"), doc.get("last_run")))
    out.sort(key=lambda r: (r[0] or "").lower())
    return out


def local_set_last_run(tcg_name, now):
    """Update last_run on the local tcg_master copy."""
    conn = _local_conn()
    row = conn.execute("SELECT data FROM tcg_master WHERE data LIKE ?",
                       (f'%"{tcg_name}"%',)).fetchone()
    if row:
        doc = json.loads(row[0])
        if doc.get("tcg_display_name") == tcg_name:
            doc["last_run"] = now
            conn.execute("UPDATE tcg_master SET data = ? WHERE _id = ?",
                         (json.dumps(doc), row[0]))
    conn.commit()
    conn.close()


def sync_local():
    """Push local skipped_images + tcg_master changes back to Mongo."""
    print("\n[3/3] Uploading changes to server...")
    client = db.get_db()
    from bson import ObjectId

    for coll_name, table in (("skipped_images", "skipped_images"),
                             ("tcg_master", "tcg_master")):
        coll = client[coll_name]
        conn = _local_conn()
        rows = conn.execute(f"SELECT _id, data FROM {table}").fetchall()
        conn.close()
        updated = 0
        for _id, data in rows:
            doc = json.loads(data)
            try:
                oid = ObjectId(_id)
            except Exception:
                continue
            coll.update_one({"_id": oid}, {"$set": doc}, upsert=True)
            updated += 1
        print(f"  Synced {updated} docs to {coll_name}.")
    #client.close()
    print("  Upload complete.\n")


# ==============================================================
# 2. UI & UTILITIES
# ==============================================================
def display_menu(rows, global_total):
    os.system(CLEAR_CMD)
    print(f"\n {C['header']}  JAPANESE HARVESTER v5.6 (G-DRIVE)  {C['reset']}")
    print(f" {C['tag']}Total Skips Tracked: {C['val']}{global_total:,}{C['reset']}")
    print(f"{C['line']}{'?' * 105}{C['reset']}")

    head = f"{'ID':<4} {'TCG CATEGORY':<25} | {'SITE ID':<10} | {'PAGES':<6} | {'LAST RUN'}"
    print(f" {C['bold']}{head}{C['reset']}")
    print(f"{C['line']}{'-' * 4}{'-' * 26}|{'-' * 12}|{'-' * 8}|{'-' * 20}{C['reset']}")

    for i, (name, lang, sid, pgs, folder, last) in enumerate(rows, 1):
        last_str = last if last else "Never"
        name_clr = C['green'] if "2026" in str(last_str) else C['cyan']
        print(f" {C['val']}{i:<3}{C['reset']} {name_clr}{name:<25}{C['reset']} | "
              f"{C['val']}{str(sid):<10}{C['reset']} | "
              f"{C['val']}{str(pgs):<6}{C['reset']} | "
              f"{C['tag']}{last_str:<18}{C['reset']}")

    print(f"{C['line']}{'?' * 105}{C['reset']}")
    return input(f" {C['bold']}? Select #, {C['green']}'all'{C['reset']}{C['bold']} or 'q': {C['reset']}")


# ==============================================================
# 3. NODRIVER HARVESTING - streams downloads as pages scan
# ==============================================================
async def run_harvest(site_id, pages, all_skips, executor, folder):
    browser_args = ['--window-size=1920,1080', '--no-sandbox', '--disable-dev-shm-usage']
    if not BROWSER_PATH:
        raise SystemExit("Could not find Vivaldi or Chrome. Install one and re-run.")
    browser = await uc.start(browser_executable_path=BROWSER_PATH, browser_args=browser_args)
    try:
        page = await browser.get("https://tcgrepublic.com/")
        await asyncio.sleep(5)
        for p in range(1, pages + 1):
            url = f"https://tcgrepublic.com/category/category_page_{site_id}.html?p={p}"
            feed(f"{C['bold']}[PAGE {p}/{pages}]{C['reset']} scanning {url}")
            await page.get(url)
            try:
                await page.select('li.product_thumbnail', timeout=15)
                await page.scroll_down(1200)
                await asyncio.sleep(2)
                imgs = await page.select_all("li.product_thumbnail img")
                page_seen = set()  # stop SKIP spam for repeats on this page
                for img in imgs:
                    attrs = img.attributes
                    src = next((attrs[i + 1] for i in range(len(attrs)) if attrs[i] == 'src'), None)
                    if src:
                        full_url = src.replace(".l2_thumbnail.jpg", "")
                        if not full_url.startswith("http"):
                            full_url = "https://tcgrepublic.com" + full_url
                        img_name = full_url.split("/")[-1]
                        if img_name in page_seen:
                            continue  # already handled this image on this page
                        page_seen.add(img_name)
                        if img_name not in all_skips:
                            all_skips.add(img_name)
                            feed(f"{C['dim']}QUEUE{C['reset']} {img_name}")
                            executor.submit(download_file, full_url, folder)
                        else:
                            feed(f"{C['dim']}SKIP{C['reset']} {img_name}")
            except Exception:
                continue
    finally:
        browser.stop()


# ==============================================================
# 4. DOWNLOAD & PROCESSING
# ==============================================================
def download_file(url, folder):
    global new_download_count
    name = url.split("/")[-1]
    path = os.path.join(folder, name)
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        if r.status_code == 200:
            with open(path, "wb") as f:
                f.write(r.content)
            with counter_lock:
                new_download_count += 1
            feed(f"{C['green']}SAVED{C['reset']} {name}  ({new_download_count} total)")
        else:
            feed(f"{C['dim']}HTTP {r.status_code}{C['reset']} {name}")
    except Exception as e:
        feed(f"{C['dim']}FAIL{C['reset']} {name}  ({type(e).__name__})")


def process_single_tcg(tcg_data):
    global new_download_count
    name, _, sid, pgs, folder_name, _ = tcg_data

    print(f"\n{C['header']} ? PROCESSING: {name.upper()} {C['reset']}")

    db_skips = local_skipped_images()

    local_files = set()
    for base_folder in [CHECK_FOLDER, BASE_SAVE_DIR]:
        target_p = os.path.join(base_folder, folder_name)
        if os.path.exists(target_p):
            local_files.update(os.listdir(target_p))

    all_skips = db_skips.union(local_files)
    new_download_count = 0

    # Create the save folder ONCE, before any downloads start
    save_folder = os.path.join(BASE_SAVE_DIR, folder_name)
    os.makedirs(save_folder, exist_ok=True)

    feed(f"{C['dim']}Loaded {len(all_skips)} known images to skip{C['reset']}")

    with ThreadPoolExecutor(max_workers=MAX_DOWNLOAD_WORKERS) as exe:
        asyncio.run(run_harvest(sid, pgs, all_skips, exe, save_folder))

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    local_set_last_run(name, now)

    print(f" {C['green']}? Finished {name}! Saved {new_download_count}.{C['reset']}")


# ==============================================================
# 4b. MOVE NEW CARDS TO T: (run after harvest, VPN OFF)
# ==============================================================
def move_new_cards_to_t():
    print("\n[POST-RUN] Moving New Cards from G: to T: ...")
    src_root = r"G:\My Drive\New Cards"
    dst_root = r"T:\Full Card Database\New Cards"
    if not os.path.exists(src_root):
        print("  No G:\\My Drive\\New Cards folder found. Nothing to move.")
        return
    moved = skipped = 0
    for folder in os.listdir(src_root):
        src_folder = os.path.join(src_root, folder)
        if not os.path.isdir(src_folder):
            continue
        dst_folder = os.path.join(dst_root, folder)
        os.makedirs(dst_folder, exist_ok=True)
        for fname in os.listdir(src_folder):
            src_file = os.path.join(src_folder, fname)
            dst_file = os.path.join(dst_folder, fname)
            if os.path.exists(dst_file):
                skipped += 1
                continue
            try:
                os.rename(src_file, dst_file)
                moved += 1
            except Exception as e:
                print(f"  FAILED {fname}: {e}")
    print(f"  Moved: {moved}   Skipped (already on T:): {skipped}")


# ==============================================================
# 5. MAIN LOOP (guided: export -> VPN -> harvest -> sync -> move)
# ==============================================================
def main():
    # STEP 1: Export local copy (Mongo must be reachable, VPN OFF)
    print(f"\n{C['header']} JAPANESE HARVESTER - LOCAL MIRROR MODE {C['reset']}")
    print("Step 1: Exporting collections to a local copy.")
    print("Make sure the VPN is OFF so the server is reachable.")
    input("Press Enter when ready to export...")
    export_local()

    # STEP 2: Ask user to enable VPN, then show menu
    print("Step 2: Turn ON your VPN now, then press Enter to continue.")
    input("VPN enabled? Press Enter...")

    while True:
        rows = local_tcg_master_rows()
        global_total = local_skipped_count()

        if not rows:
            print("No Japanese TCGs found in local tcg_master!")
            break

        choice = display_menu(rows, global_total)
        if choice.lower() == 'q':
            break

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

    # STEP 3: Turn VPN off and upload changes
    print("\nStep 3: Done harvesting.")
    print("Turn OFF your VPN now so the server is reachable.")
    upload = input("Upload changes to server? (y/n): ").strip().lower()
    if upload in ("y", "yes"):
        sync_local()
    else:
        print("Skipped upload. Local copy kept in jap_local_mirror.db")

    # STEP 4: Move new files from G: to T: (now that VPN is off, T: is reachable)
    print("\nT: drive should be reachable now (VPN off).")
    move_now = input("Move New Cards from G: to T: now? (y/n): ").strip().lower()
    if move_now in ("y", "yes"):
        move_new_cards_to_t()
    else:
        print("Skipped. Run move_new_cards_to_t() later.")


if __name__ == "__main__":
    main()


