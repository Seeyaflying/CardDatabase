
import os
import shutil
import sys
import time
from collections import deque
from pathlib import Path

from pymongo import MongoClient

# ============================================================
# Configuration - edit these
# ============================================================

# Replace <SERVER_IP> with the server's Tailscale IP (or LAN IP).
# Port 27018 matches what we mapped in the compose file.
MONGO_URI = ("mongodb://card_manager:1369@100.80.179.119:27018/carddb")
DB_NAME = "carddb"
COLLECTION_NAME = "card_index"

SOURCE = Path(r"T:\Card Database")
DEST = Path(r"G:\My Drive\Card Database")
DONE_CARDS = Path(r"T:\Cards Done")
UNMATCHED = DONE_CARDS / "Unmatched"

BASE_DIR = Path.home() / "card-database-manager"
REPORT_FILE = BASE_DIR / "verification-report.txt"
DIFFERENCES_FILE = BASE_DIR / "verification-differences.txt"
COMBINED_FILE = BASE_DIR / "verification-combined.txt"
REORG_FILE = BASE_DIR / "reorganize-report.txt"

VERBOSE = True

# ============================================================
# Mongo connection helpers
# ============================================================

_client = None

def _get_db():
    global _client
    if _client is None:
        _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    return _client[DB_NAME]

def _get_coll():
    return _get_db()[COLLECTION_NAME]

def close_db():
    global _client
    if _client is not None:
        _client.close()
        _client = None

def init_db():
    _get_coll().create_index([("game", 1), ("filename", 1)], unique=True)

def db_has_data():
    return _get_coll().count_documents({}) > 0

# ============================================================
# Helpers
# ============================================================

def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")

def pause():
    input("\nPress Enter to return to the menu...")
    clear_screen()

def ensure_directories():
    SOURCE.mkdir(parents=True, exist_ok=True)
    DEST.mkdir(parents=True, exist_ok=True)
    DONE_CARDS.mkdir(parents=True, exist_ok=True)
    UNMATCHED.mkdir(parents=True, exist_ok=True)
    BASE_DIR.mkdir(parents=True, exist_ok=True)

def log(msg):
    if VERBOSE:
        print(msg)

def format_duration(seconds):
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)

def _write_report(message):
    with open(REPORT_FILE, "a", encoding="utf-8") as f:
        f.write(message + "\n")

def _write_difference(message):
    with open(DIFFERENCES_FILE, "a", encoding="utf-8") as f:
        f.write(message + "\n")

def _write_combined(message):
    with open(COMBINED_FILE, "a", encoding="utf-8") as f:
        f.write(message + "\n")

def _write_reorg(message):
    with open(REORG_FILE, "a", encoding="utf-8") as f:
        f.write(message + "\n")

def _enable_ansi():
    if os.name == "nt":
        os.system("")

class Dashboard:
    def __init__(self, max_lines=15, refresh_interval=1.0):
        _enable_ansi()
        self.max_lines = max_lines
        self.recent = deque(maxlen=max_lines)
        self.folder = ""
        self.elapsed = 0
        self.folder_done =  0
        self.total_done = 0
        self.last_refresh = 0.0
        self.refresh_interval = refresh_interval

    def set_header(self, folder, elapsed, folder_done, total_done):
        self.folder = folder
        self.elapsed = elapsed
        self.folder_done = folder_done
        self.total_done = total_done

    def add_line(self, text):
        self.recent.append(text)

    def draw(self):
        out = "\033[2J\033[H"
        out += "=" * 60 + "\n"
        out += "CARD DATABASE MANAGER - LIVE STATUS\n"
        out += "=" * 60 + "\n"
        out += f"Folder:       {self.folder}\n"
        out += f"Time Elapsed: {format_duration(self.elapsed)}\n"
        out += f"Folder Files: {self.folder_done}\n"
        out += f"Total Files:  {self.total_done}\n"
        out += "-" * 60 + "\n"
        for line in self.recent:
            out += line + "\n"
        sys.stdout.write(out)
        sys.stdout.flush()

    def maybe_refresh(self):
        now = time.time()
        if now - self.last_refresh >= self.refresh_interval:
            self.last_refresh = now
            self.draw()

def set_refresh_for_folder(dash, folder_name):
    dash.refresh_interval = 2.0 if folder_name.lower() == "magic the gathering" else 1.0

def game_folders():
    log(f"  Listing source: {SOURCE}")
    try:
        entries = sorted(
            [p for p in SOURCE.iterdir() if p.is_dir() and p.name != "Done Cards"],
            key=lambda p: p.name.lower(),
        )
    except Exception as e:
        print(f"  ERROR listing source {SOURCE}: {type(e).__name__}: {e}")
        return []
    log(f"  Found {len(entries)} game folder(s)")
    return entries

# ============================================================
# Card index (Mongo)
# ============================================================

def rebuild_index():
    clear_screen()
    print("=" * 70)
    print("BUILD CARD INDEX (first run)")
    print("=" * 70)
    print("\nThis scans every game folder under the source (T) and")
    print("destination (G) and records each file's location.")
    print("This is a one-time full scan - it can take a while")
    print("with hundreds of thousands of files.")
    print("\nPress Enter to start...")
    input()
    clear_screen()

    init_db()
    coll = _get_coll()
    coll.delete_many({})

    dash = Dashboard()
    dash.set_header("Building index", 0, 0, 0)
    dash.draw()

    start_time = time.time()
    total_files = 0
    scanned_folders = 0
    errors = 0

    for root in (SOURCE,):
        if not root.exists():
            continue
        for folder in root.iterdir():
            if not folder.is_dir() or folder.name == "Done Cards":
                continue
            scanned_folders += 1
            set_refresh_for_folder(dash, folder.name)
            dash.set_header(
                f"Scanning: {folder.name}",
                int(time.time() - start_time),
                scanned_folders,
                total_files,
            )
            dash.maybe_refresh()
            try:
                with os.scandir(folder)as it:
                    batch = []
                    for entry in it:
                        if entry.is_file():
                            total_files += 1
                            dst = DEST / folder.name / entry.name
                            batch.append({
                                "filename": entry.name,
                                "game": folder.name,
                                "source_path": str(SOURCE / folder.name / entry.name),
                                "dest_path": str(dst),
                                "status": "uploaded" if dst.exists() else "pending",
                                "file_size": entry.stat().st_size,
                                "uploaded_at": None,
                            })
                            if len(batch) >= 5000:
                                coll.insert_many(batch, ordered=False)
                                batch.clear()
                            dash.set_header(
                                f"Scanning: {folder.name}",
                                int(time.time() - start_time),
                                scanned_folders,
                                total_files,
                            )
                            dash.maybe_refresh()
                    if batch:
                        coll.insert_many(batch, ordered=False)
            except Exception as e:
                errors += 1
                print(f"  ERROR scanning {folder}: {type(e).__name__}: {e}")

    print("\033[2J\033[H", end="")
    print("=" * 70)
    print("INDEX BUILD COMPLETE")
    print("=" * 70)
    print(f"  Folders scanned: {scanned_folders}")
    print(f"  Files indexed:     {total_files}")
    print(f"  Errors:           {errors}")
    print(f"  Database:          {MONGO_URI}")
    pause()


def scan_for_new_cards():
    clear_screen()
    print("=" * 70)
    print("SCAN FOR NEW CARDS")
    print("=" * 70)
    print(f"\nSource:      {SOURCE}")
    print("\nWalks the source and records any card not already in the")
    print("database as 'pending'. Run this after adding new cards,")
    print("then use Copy & Archive to upload them.")
    print("\nPress Enter to start...")
    input()
    clear_screen()

    if not db_has_data():
        print("\n  No index found. Run 'Build Card Index' first (option 1).")
        pause()
        return

    coll = _get_coll()

    dash = Dashboard()
    dash.set_header("Scanning for new cards", 0, 0, 0)
    dash.draw()

    start_time = time.time()
    new_cards = 0
    already_known = 0
    errors =  0
    total_scanned = 0

    for folder in game_folders():
        folder_path = folder.resolve()
        set_refresh_for_folder(dash, folder.name)
        dash.set_header(
            f"Scanning: {folder.name}",
            int(time.time() - start_time),
            0,
            total_scanned,
        )
        try:
            with os.scandir(folder_path) as it:
                for entry in it:
                    if not entry.is_file():
                        continue
                    total_scanned += 1
                    if coll.find_one({"filename": entry.name}):
                        already_known += 1
                        continue
                    src = SOURCE / folder.name / entry.name
                    dst = DEST / folder.name / entry.name
                    try:
                        coll.insert_one({
                            "filename": entry.name,
                            "game": folder.name,
                            "source_path": str(src),
                            "dest_path": str(dst),
                            "status": "pending",
                            "file_size": entry.stat().st_size,
                            "uploaded_at": None,
                        })
                        new_cards += 1
                        dash.add_line(f"  NEW: {entry.name}")
                    except Exception:
                        already_known += 1
                    dash.maybe_refresh()
        except Exception as e:
            errors += 1
            print(f"  ERROR scanning {folder.name}: {type(e).__name__}: {e}")

    print("\033[2J\033[H", end="")
    print("=" * 70)
    print("SCAN COMPLETE")
    print("=" * 70)
    print(f"  Files scanned:   {total_scanned}")
    print(f"  New cards found:  {new_cards}")
    print(f"  Already known:    {already_known}")
    print(f"  Errors:           {errors}")
    if new_cards == 0:
        print("\n  No new cards found. Everything is up to date.")
    else:
        print(f"\n  {new_cards} new card(s) recorded as 'pending'.")
        print("  Run 'Copy & Archive' to upload them.")
    pause()

def _mark_uploaded(filename, game, dst_file):
    coll = _get_coll()
    coll.update_one(
        {"filename": filename},
        {"$set": {"status": "uploaded", "dest_path": str(dst_file), "uploaded_at": time.strftime("%Y-%m-%d %H:%M:%S")}},
    )

def copy_and_archive():
    clear_screen()
    print("=" * 70)
    print("COPY & ARCHIVE (database-driven)")
    print("=" * 70)
    print(f"\nSource:      {SOURCE}")
    print(f"Destination: {DEST}")
    print(f"Done Cards:  {DONE_CARDS}")
    print("\nUploads all 'pending' cards to the destination, verifies,")
    print("then moves the originals into Done Cards. Cards already")
    print("marked 'uploaded' are skipped automatically.")
    print("\nPress Enter to start...")
    input()
    clear_screen()

    if not db_has_data():
        print("\n  No index found. Run 'Build Card Index' first (option 1).")
        pause()
        return

    coll = _get_coll()
    pending = {}
    for doc in coll.find({"status": "pending"}):
        pending.setdefault(doc["game"], []).append((doc["filename"], Path(doc["source_path"]), Path(doc["dest_path"])))
    if not pending:
        print("\n  No pending cards to upload. Everything is already uploaded.")
        pause()
        return

    copied = archived = skipped = errors = 0
    total_done = 0

    dash = Dashboard()

    for game_name, files in pending.items():
        dest_folder = DEST / game_name
        done_subfolder = DONE_CARDS / game_name
        try:
            dest_folder.mkdir(parents=True, exist_ok=True)
            done_subfolder.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"  ERROR creating folders: {type(e).__name__}: {e}")
            errors += 1
            continue

        done = 0
        start_time = time.time()
        set_refresh_for_folder(dash, game_name)
        dash.set_header(game_name, 0, 0, total_done)
        dash.draw()

        for filename, src_file, dst_file in files:

            done += 1
            total_done += 1

            if dst_file.exists() and dst_file.stat().st_size == src_file.stat().st_size:
                _mark_uploaded(filename, game_name, dst_file)
                skipped += 1
                dash.add_line(f"  SKIPPED (already uploaded): {filename}")
                elapsed = int(time.time() - start_time)
                dash.set_header(game_name, elapsed, done, total_done)
                dash.maybe_refresh()
                continue

            if (done_subfolder / filename).exists():
                skipped += 1
                dash.add_line(f"  SKIPPED (already archived: {filename}")
                elapsed = int(time.time() - start_time)
                dash.set_header(game_name, elapsed, done, total_done)
                dash.maybe_refresh()
                continue

            if not src_file.exists():
                skipped += 1
                dash.add_line(f"  SKIPPED (source missing: {filename}")
                elapsed = int(time.time() - start_time)
                dash.set_header(game_name, elapsed, done, total_done)
                dash.maybe_refresh()
                continue

            try:
                shutil.copy2(str(src_file), str(dst_file))
                if src_file.stat().st_size != dst_file.stat().st_size:
                    raise RuntimeError("size mismatch after copy")
                shutil.move(str(src_file), str(done_subfolder / filename))
                copied += 1
                archived += 1
                _mark_uploaded(filename, game_name, dst_file)
                _write_combined(f"COPIED & ARCHIVED: {game_name} / {filename}")
                dash.add_line(f"  {filename}: copied, verified, moved")
            except FileNotFoundError:
                skipped += 1
                dash.add_line(f"  SKIPPED (not found): {filename}")
            except Exception as e:
                errors += 1
                dash.add_line(f"  ERROR: {filename}: {type(e).__name__}")
                _write_difference(f"ERROR: {game_name} / {filename} - {e}")

            elapsed = int(time.time() - start_time)
            dash.set_header(game_name, elapsed, done, total_done)
            dash.maybe_refresh()

    print("\033[2J\033[H", end="")
    print("=" * 70)
    print("COMPLETE")
    print("=" * 70)
    print(f"  Copied:   {copied}")
    print(f"  Archived: {archived}")
    print(f"  Skipped:   {skipped}")
    print(f"  Errors:    {errors}")
    print(f"  Total files processed: {total_done}")
    pause()

def copy_only():
    clear_screen()
    print("=" * 70)
    print("COPY ONLY (no archive)")
    print("=" * 70)
    print(f"\nSource:      {SOURCE}")
    print(f"Destination: {DEST}")
    print("\nCopies every active file to the destination but leaves")
    print("the originals in place (no archive).")
    print("\nPress Enter to start...")
    input()
    clear_screen()

    copied = skipped = errors = 0
    total_done = 0

    folders = game_folders()

    dash = Dashboard()

    for folder in folders:
        folder_path = folder.resolve()
        dest_folder = DEST / folder.name
        try:
            dest_folder.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"  ERROR creating {dest_folder}: {type(e).__name__}: {e}")
            errors += 1
            continue

        done = 0
        start_time = time.time()
        set_refresh_for_folder(dash, folder.name)
        dash.set_header(folder.name, 0, 0, total_done)
        dash.draw()

        try:
            with os.scandir(folder_path) as it:
                for entry in it:
                    if not entry.is_file():
                        continue

                    file = Path(entry.path)
                    done += 1
                    total_done += 1

                    if not file.exists():
                        skipped += 1
                        elapsed = int(time.time() - start_time)
                        dash.set_header(folder.name, elapsed, done, total_done)
                        dash.maybe_refresh()
                        continue

                    dest_file = dest_folder / file.name
                    if dest_file.exists() and dest_file.stat().st_size == file.stat().st_size:
                        skipped += 1
                        elapsed = int(time.time() - start_time)
                        dash.set_header(folder.name, elapsed, done, total_done)
                        dash.maybe_refresh()
                        continue

                    try:
                        shutil.copy2(str(file), str(dest_file))
                        copied += 1
                        _write_combined(f"COPIED: {folder.name} / {file.name}")
                        dash.add_line(f"  {file.name}: copied")
                    except FileNotFoundError:
                        skipped += 1
                        dash.add_line(f"  SKIPPED (not found): {file.name}")
                    except Exception as e:
                        errors += 1
                        dash.add_line(f"  ERROR: {file.name}: {type(e).__name__}")
                        _write_difference(f"ERROR: {folder.name} / {file.name} - {e}")

                    elapsed = int(time.time() - start_time)
                    dash.set_header(folder.name, elapsed, done, total_done)
                    dash.maybe_refresh()
        except Exception as e:
            print(f"\n  ERROR listing {folder.name}: {type(e).__name__}: {e}")
            errors += 1
            continue

    print("\033[2J\033[H", end="")
    print("=" * 70)
    print("COMPLETE")
    print("=" * 70)
    print(f"  Copied:  {copied}")
    print(f"  Skipped: {skipped}")
    print(f"  Errors:  {errors}")
    print(f"  Total files processed: {total_done}")
    pause()

def archive_only():
    clear_screen()
    print("=" * 70)
    print("ARCHIVE ONLY (no copy)")
    print("=" * 70)
    print(f"\nSource:      {SOURCE}")
    print(f"Destination: {DEST}")
    print(f"Done Cards:  {DONE_CARDS}")
    print("\nMoves files that already exist on the destination into")
    print("Done Cards. Stops after 10 unverified files in a row.")
    print("\nPress Enter to start...")
    input()
    clear_screen()

    archived = skipped = errors = 0
    total_done = 0
    unverified_streak = 0
    stopped_early = False

    folders = game_folders()

    dash = Dashboard()

    for folder in folders:
        folder_path = folder.resolve()
        dest_folder = DEST / folder.name
        done_subfolder = DONE_CARDS / folder.name

        done = 0
        start_time = time.time()
        set_refresh_for_folder(dash, folder.name)
        dash.set_header(folder.name, 0, 0, total_done)
        dash.draw()

        try:
            with os.scandir(folder_path) as it:
                for entry in it:
                    if not entry.is_file():
                        continue

                    file = Path(entry.path)
                    done += 1
                    total_done += 1

                    if not file.exists():
                        skipped += 1
                        unverified_streak += 1
                        dash.add_line(f"  UNVERIFIED: {file.name} (missing)")
                        if unverified_streak >= 10:
                            stopped_early = True
                            break
                        continue

                    if (done_subfolder / file.name).exists():
                        skipped += 1
                        unverified_streak = 0
                        continue

                    dest_file = dest_folder / file.name
                    if not dest_file.exists():
                        skipped += 1
                        unverified_streak += 1
                        dash.add_line(f"  UNVERIFIED: {file.name} (not on destination)")
                        if unverified_streak >= 10:
                            stopped_early = True
                            break
                        continue

                    try:
                        if file.stat().st_size == dest_file.stat().st_size:
                            shutil.move(str(file), str(done_subfolder / file.name))
                            archived += 1
                            unverified_streak = 0
                            _write_combined(f"ARCHIVED: {folder.name} / {file.name}")
                            dash.add_line(f"  {file.name}: verified, moved")
                        else:
                            errors += 1
                            unverified_streak += 1
                            dash.add_line(f"  UNVERIFIED: {file.name} (size mismatch)")
                            _write_difference(f"SIZE MISMATCH: {folder.name} / {file.name}")
                            if unverified_streak >= 10:
                                stopped_early = True
                                break
                    except FileNotFoundError:
                        skipped += 1
                        unverified_streak += 1
                        dash.add_line(f"  UNVERIFIED: {file.name} (not found)")
                        if unverified_streak >= 10:
                            stopped_early = True
                            break
                    except Exception as e:
                        errors += 1
                        unverified_streak += 1
                        dash.add_line(f"  UNVERIFIED: {file.name} ({type(e).__name__})")
                        _write_difference(f"ERROR: {folder.name} / {file.name} - {e}")
                        if unverified_streak >= 10:
                            stopped_early = True
                            break

                    elapsed = int(time.time() - start_time)
                    dash.set_header(folder.name, elapsed, done, total_done)
                    dash.maybe_refresh()

                if stopped_early:
                    break

        except Exception as e:
            print(f"\n  ERROR listing {folder.name}: {type(e.__name__)}: {e}")
            errors += 1
            continue

        if stopped_early:
            break

    print("\033[2J\033[H", end="")
    print("=" * 70)
    if stopped_early:
        print("STOPPED EARLY - 10 unverified files in a row")
    else:
        print("COMPLETE")
    print("=" * 70)
    print(f"  Archived: {archived}")
    print(f"  Skipped:  {skipped}")
    print(f"  Errors:   {errors}")
    print(f"  Total files processed: {total_done}")
    pause()

def reorganize_done_cards():
    clear_screen()
    print("=" * 70)
    print("REORGANIZE DONE CARDS")
    print("=" * 70)
    print(f"\nDone Cards: {DONE_CARDS}")
    print("\nUses the card index to match each flat file to its game folder.")
    print("Files that can't be matched go to the Unmatched folder.")
    print("\nPress Enter to start...")
    input()
    clear_screen()

    with open(REORG_FILE, "w", encoding="utf-8") as f:
        f.write("REORGANIZE DONE CARDS REPORT\n")
        f.write("=" * 70 + "\n")

    col = _get_coll()
    if col.count_documents({}) == 0:
        print("\n  No index found. Run 'Build Card Index' first (option 1).")
        pause()
        return

    filename_map = {}
    for doc in col.find({}, {"filename": 1, "game": 1}):
        filename_map[doc["filename"]] = doc["game"]

    moved = 0
    unmatched = 0
    errors = 0
    total = 0

    dash = Dashboard()
    set_refresh_for_folder(dash, "done cards")
    dash.set_header("Done Cards", 0, 0, 0)
    dash.draw()

    start_time = time.time()

    try:
        with os.scandir(DONE_CARDS) as it:
            for entry in it:
                if not entry.is_file():
                    continue
                file = Path(entry.path)
                total += 1

                # Skip if the file is already gone (race condition fix)
                if not file.exists():
                    continue

                game = filename_map.get(file.name)
                if game:
                    target_folder = DONE_CARDS / game
                    try:
                        target_folder.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(file), str(target_folder / file.name))
                        moved += 1
                        _write_reorg(f"MOVED: {file.name} -> {game}")
                        dash.add_line(f"  {file.name}: -> {game}")
                    except Exception as e:
                        errors += 1
                        try:
                            shutil.move(str(file), str(UNMATCHED / file.name))
                            dash.add_line(f"  ERROR, sent to Unmatched: {file.name}")
                            _write_reorg(f"ERROR moved to Unmatched: {file.name} ({type(e).__name__}: {e})")
                        except Exception as e2:
                            dash.add_line(f"  ERROR (could not move): {file.name}")
                            _write_reorg(f"ERROR could not move: {file.name} ({type(e2).__name__}: {e2})")
                else:
                    unmatched += 1
                    try:
                        shutil.move(str(file), str(UNMATCHED / file.name))
                        dash.add_line(f"  UNMATCHED, sent to Unmatched: {file.name}")
                        _write_reorg(f"UNMATCHED moved to Unmatched: {file.name}")
                    except Exception as e2:
                        errors += 1
                        dash.add_line(f"  ERROR moving to Unmatched: {file.name}")
                        _write_reorg(f"ERROR moving to Unmatched: {file.name} ({type(e2).__name__}: {e2})")

                elapsed = int(time.time() - start_time)
                dash.set_header("Done Cards", elapsed, total, total)
                dash.maybe_refresh()
    except Exception as e:
        print(f"  ERROR scanning Done Cards: {type(e).__name__}: {e}")

    print("\033[2J\033[H", end="")
    print("=" * 70)
    print("COMPLETE")
    print("=" * 70)
    print(f"  Total flat files:   {total}")
    print(f"  Moved:              {moved}")
    print(f"  Unmatched:          {unmatched}")
    print(f"  Errors:             {errors}")
    print(f"\n  Report: {REORG_FILE}")
    print(f"  Unmatched folder: {UNMATCHED}")
    pause()


def clean_empty_folders():
    clear_screen()
    print("=" * 70)
    print("REMOVE EMPTY FOLDERS")
    print("=" * 70)
    removed = 0
    for folder in game_folders():
        folder_path = folder.resolve()
        try:
            if not any(folder_path.iterdir()):
                folder_path.rmdir()
                removed += 1
                print(f"Removed: {folder_path}")
                _write_report(f"Removed empty folder: {folder.name}")
        except OSError as e:
            print(f"Could not remove {folder_path}: {e}")
    print(f"\nRemoved {removed} empty folder(s).")
    pause()

def view_reports():
    clear_screen()
    print("=" * 70)
    print("REPORTS")
    print("=" * 70)
    print(f"\n1. Combined results:     {COMBINED_FILE}")
    print(f"2. Differences:         {DIFFERENCES_FILE}")
    print(f"3. Summary report:      {REPORT_FILE}")
    print(f"4. Reorganize report:   {REORG_FILE}")
    choice = input("\nWhich report? (1-4): ").strip()
    path = {
        1: COMBINED_FILE,
        2: DIFFERENCES_FILE,
        3: REPORT_FILE,
        4: REORG_FILE,
    }.get(int(choice) if choice.isdigit() else 0)
    if path and path.exists():
        os.system(f'notepad "{path}"')
    else:
        print("\nNo report found at that selection.")
    pause()

# ============================================================
# Main menu
# ============================================================

def show_menu():
    clear_screen()
    print("=" * 70)
    print("CARD DATABASE MANAGER")
    print("=" * 70)
    print("\n  1. Build Card Index (first run)")
    print("  2. Scan for New Cards")
    print("  3. Copy & Archive (database-driven)")
    print("  4. Copy only (no archive)")
    print("  5. Archive only (no copy)")
    print("  6. Reorganize Done Cards")
    print("  7. Remove empty folders")
    print("  8. View reports")
    print("  9. Exit")

def main():
    ensure_directories()
    try:
        init_db()
    except Exception as e:
        print(f"\n  Could not connect to Mongo: {e}")
        print("  Check that the server is reachable and MONGO_URI is correct.")
        input("\nPress Enter to exit...")
        return
    while True:
        show_menu()
        choice = input("\nEnter your choice (1-9): ").strip()

        if choice == "1":
            rebuild_index()
        elif choice == "2":
            scan_for_new_cards()
        elif choice == "3":
            copy_and_archive()
        elif choice == "4":
            copy_only()
        elif choice == "5":
            archive_only()
        elif choice == "6":
            reorganize_done_cards()
        elif choice == "7":
            clean_empty_folders()
        elif choice == "8":
            view_reports()
        elif choice == "9":
            print("\nGoodbye.")
            break
        else:
            print("\nInvalid choice. Please enter 1-9.")
            input("\nPress Enter to continue...")
            clear_screen()
    close_db()

if __name__ == "__main__":
    main()
