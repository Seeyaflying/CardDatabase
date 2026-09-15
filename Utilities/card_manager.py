import os
import shutil
import sys
import time
from collections import deque
from pathlib import Path
import config
import db

BASE_DIR = Path.home() / "card-database-manager"
REPORT_FILE = BASE_DIR / "verification-report.txt"
DIFFERENCES_FILE = BASE_DIR / "verification-differences.txt"
COMBINED_FILE = BASE_DIR / "verification-combined.txt"
REORG_FILE = BASE_DIR / "reorganize-report.txt"
VERBOSE = True

def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")

def pause():
    input("\nPress Enter to return to the menu...")
    clear_screen()

def ensure_directories():
    for p in (config.CARD_UPLOAD, config.CARD_DATABASE, config.G_DRIVE, BASE_DIR):
        p.mkdir(parents=True, exist_ok=True)


def log(msg):
    if VERBOSE:
        print(msg)

def format_duration(seconds):
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if days: parts.append(f"{days}d")
    if hours: parts.append(f"{hours}h")
    if minutes: parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)

def _write_report(m):  open(REPORT_FILE, "a", encoding="utf-8").write(m + "\n")
def _write_difference(m): open(DIFFERENCES_FILE, "a", encoding="utf-8").write(m + "\n")
def _write_combined(m):  open(COMBINED_FILE, "a", encoding="utf-8").write(m + "\n")
def _write_reorg(m):     open(REORG_FILE, "a", encoding="utf-8").write(m + "\n")

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
        self.folder_done = 0
        self.total_done = 0
        self.last_refresh = 0.0
        self.refresh_interval = refresh_interval
    def set_header(self, folder, elapsed, folder_done, total_done):
        self.folder = folder; self.elapsed = elapsed
        self.folder_done = folder_done; self.total_done = total_done
    def add_line(self, text):
        self.recent.append(text)
    def draw(self):
        out = "\033[2J\033[H" + "=" * 60 + "\nCARD DATABASE MANAGER - LIVE STATUS\n" + "=" * 60 + "\n"
        out += f"Folder:       {self.folder}\n"
        out += f"Time Elapsed: {format_duration(self.elapsed)}\n"
        out += f"Folder Files: {self.folder_done}\n"
        out += f"Total Files:  {self.total_done}\n" + "-" * 60 + "\n"
        for line in self.recent:
            out += line + "\n"
        sys.stdout.write(out); sys.stdout.flush()
    def maybe_refresh(self):
        now = time.time()
        if now - self.last_refresh >= self.refresh_interval:
            self.last_refresh = now
            self.draw()

def set_refresh_for_folder(dash, folder_name):
    dash.refresh_interval = 2.0 if folder_name.lower() == "magic the gathering" else 1.0

def game_folders():
    try:
        return sorted([p for p in config.CARD_UPLOAD.iterdir()
                       if p.is_dir() and p.name.lower() != "done cards"],
                      key=lambda p: p.name.lower())
    except Exception as e:
        print(f"  ERROR listing source: {e}")
        return []


def copy_and_archive():
    clear_screen()
    print("=" * 70)
    print("COPY & ARCHIVE (database-driven)")
    print("=" * 70)
    if not db.has_data():
        print("\n  No index found. Run 'Build Card Index' first.")
        pause(); return
    coll = db.coll()
    pending = {}
    for doc in coll.find({"status": "pending"}):
        pending.setdefault(doc["game"], []).append(
            (doc["filename"], Path(doc["source_path"]), Path(doc["dest_path"])))
    if not pending:
        print("\n  No pending cards.")
        pause(); return
    copied = archived = skipped = errors = total_done = 0
    dash = Dashboard(max_lines=10)
    for game_name, files in pending.items():
        dest_folder = config.G_DRIVE / game_name
        done_subfolder = config.CARD_DATABASE / game_name
        dest_folder.mkdir(parents=True, exist_ok=True)
        done_subfolder.mkdir(parents=True, exist_ok=True)
        done = 0
        start = time.time()
        set_refresh_for_folder(dash, game_name)
        dash.set_header(game_name, 0, 0, total_done)
        dash.draw()
        for filename, src_file, dst_file in files:
            done += 1; total_done += 1
            if not src_file.exists():
                skipped += 1
                db.mark_missing_source(filename, game_name)
                dash.add_line(f"  SKIPPED (source missing): {filename}")
                dash.set_header(game_name, int(time.time()-start), done, total_done)
                dash.maybe_refresh()
                continue
            if dst_file.exists() and dst_file.stat().st_size == src_file.stat().st_size:
                db.mark_uploaded(filename, game_name, dst_file)
                skipped += 1
                dash.add_line(f"  SKIPPED (already uploaded): {filename}")
                dash.set_header(game_name, int(time.time()-start), done, total_done)
                dash.maybe_refresh()
                continue
            if (done_subfolder / filename).exists():
                db.mark_uploaded(filename, game_name, dst_file)
                skipped += 1
                dash.add_line(f"  SKIPPED (already archived): {filename}")
                dash.set_header(game_name, int(time.time()-start), done, total_done)
                dash.maybe_refresh()
                continue
            try:
                size = src_file.stat().st_size
                shutil.copy2(str(src_file), str(dst_file))
                if size != dst_file.stat().st_size:
                    raise RuntimeError("size mismatch after copy")
                shutil.move(str(src_file), str(done_subfolder / filename))
                copied += 1; archived += 1
                db.mark_uploaded(filename, game_name, dst_file)
                _write_combined(f"COPIED & ARCHIVED: {game_name} / {filename}")
                dash.add_line(f"  {filename}: copied, verified, moved")
            except FileNotFoundError:
                skipped += 1
                db.mark_missing_source(filename, game_name)
                dash.add_line(f"  SKIPPED (not found): {filename}")
            except Exception as e:
                errors += 1
                dash.add_line(f"  ERROR: {filename}: {type(e).__name__}")
                _write_difference(f"ERROR: {game_name} / {filename} - {e}")
            dash.set_header(game_name, int(time.time()-start), done, total_done)
            dash.maybe_refresh()
    print("\033[2J\033[H", end="")
    print("=" * 70 + "\nCOMPLETE\n" + "=" * 70)
    print(f"  Copied: {copied}   Archived: {archived}   Skipped: {skipped}   Errors: {errors}")
    print(f"  Total processed: {total_done}")
    pause()

def archive_only():
    clear_screen()
    print("=" * 70)
    print("ARCHIVE ONLY (no copy to G Drive)")
    print("=" * 70)
    archived = skipped = errors = total_done = 0
    dash = Dashboard(max_lines=10)
    for folder in game_folders():
        done_subfolder = config.CARD_DATABASE / folder.name
        done_subfolder.mkdir(parents=True, exist_ok=True)
        done = 0
        start = time.time()
        set_refresh_for_folder(dash, folder.name)
        dash.set_header(folder.name, 0, 0, total_done)
        dash.draw()
        for entry in folder.iterdir():
            if not entry.is_file():
                continue
            file = Path(entry.path)
            done += 1; total_done += 1
            if (done_subfolder / file.name).exists():
                skipped += 1
                dash.add_line(f"  SKIPPED (already archived): {file.name}")
                dash.set_header(folder.name, int(time.time()-start), done, total_done)
                dash.maybe_refresh()
                continue
            try:
                shutil.move(str(file), str(done_subfolder / file.name))
                archived += 1
                _write_combined(f"ARCHIVED: {folder.name} / {file.name}")
                dash.add_line(f"  {file.name}: archived")
            except Exception as e:
                errors += 1
                dash.add_line(f"  ERROR: {file.name}: {type(e).__name__}")
                _write_difference(f"ERROR: {folder.name} / {file.name} - {e}")
            dash.set_header(folder.name, int(time.time()-start), done, total_done)
            dash.maybe_refresh()
    print("\033[2J\033[H", end="")
    print("=" * 70 + "\nCOMPLETE\n" + "=" * 70)
    print(f"  Archived: {archived}   Skipped: {skipped}   Errors: {errors}")
    print(f"  Total processed: {total_done}")
    pause()

def reorganize_done_cards():
    clear_screen()
    print("=" * 70)
    print("REORGANIZE CARD DATABASE")
    print("=" * 70)
    if not db.has_data():
        print("\n  No index found.")
        pause(); return
    coll = db.coll()
    filename_map = {}
    dupes = set()
    for doc in coll.find({}, {"filename": 1, "game": 1}):
        if doc["filename"] in filename_map and filename_map[doc["filename"]] != doc["game"]:
            dupes.add(doc["filename"])
        else:
            filename_map[doc["filename"]] = doc["game"]
    unmatched_dir = config.CARD_DATABASE / "Unmatched"
    unmatched_dir.mkdir(parents=True, exist_ok=True)
    moved = unmatched = errors = total = 0
    for entry in config.CARD_DATABASE.iterdir():
        if not entry.is_file():
            continue
        file = Path(entry.path)
        total += 1
        if file.name in dupes:
            unmatched += 1
            try:
                shutil.move(str(file), str(unmatched_dir / file.name))
            except Exception as e:
                errors += 1
        else:
            game = filename_map.get(file.name)
            if game:
                target = config.CARD_DATABASE / game
                target.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.move(str(file), str(target / file.name))
                    moved += 1
                except Exception as e:
                    errors += 1
            else:
                unmatched += 1
                try:
                    shutil.move(str(file), str(unmatched_dir / file.name))
                except Exception as e:
                    errors += 1
    print("\033[2J\033[H", end="")
    print("=" * 70 + "\nCOMPLETE\n" + "=" * 70)
    print(f"  Total: {total}   Moved: {moved}   Unmatched: {unmatched}   Errors: {errors}")
    pause()

def clean_empty_folders():
    clear_screen()
    print("=" * 70)
    print("REMOVE EMPTY FOLDERS")
    print("=" * 70)
    removed = 0
    for folder in game_folders():
        try:
            if not any(folder.iterdir()):
                folder.rmdir()
                removed += 1
                print(f"Removed: {folder}")
        except OSError as e:
            print(f"Could not remove {folder}: {e}")
    print(f"\nRemoved {removed} empty folder(s).")
    pause()

def verify():
    clear_screen()
    print("=" * 70)
    print("VERIFICATION")
    print("=" * 70)
    if not db.has_data():
        print("\n  No index found.")
        pause(); return
    coll = db.coll()
    missing = coll.count_documents({"status": "missing_source"})
    pending = coll.count_documents({"status": "pending"})
    uploaded = coll.count_documents({"status": "uploaded"})
    print(f"\n  Pending: {pending}   Uploaded: {uploaded}   Missing source: {missing}")
    pause()

def rebuild_index():
    clear_screen()
    print("=" * 70)
    print("BUILD CARD INDEX (from Card Upload)")
    print("=" * 70)
    coll = db.coll()
    added = skipped = 0
    for folder in game_folders():
        for entry in folder.iterdir():
            if not entry.is_file():
                continue
            file = Path(entry.path)
            if file.suffix.lower() not in config.IMAGE_EXTS:
                continue
            if coll.find_one({"filename": file.name, "game": folder.name}):
                skipped += 1
                continue
            coll.insert_one({
                "filename": file.name,
                "game": folder.name,
                "source_path": str(file),
                "dest_path": str(config.G_DRIVE / folder.name / file.name),
                "status": "pending",
                "added_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            })
            added += 1
    print(f"\n  Added: {added}   Already in index: {skipped}")
    pause()

def scan_for_new_cards():
    clear_screen()
    print("=" * 70)
    print("SCAN FOR NEW CARDS")
    print("=" * 70)
    coll = db.coll()
    new_count = 0
    for folder in game_folders():
        for entry in folder.iterdir():
            if not entry.is_file():
                continue
            file = Path(entry.path)
            if file.suffix.lower() not in config.IMAGE_EXTS:
                continue
            if not coll.find_one({"filename": file.name, "game": folder.name}):
                new_count += 1
                coll.insert_one({
                    "filename": file.name,
                    "game": folder.name,
                    "source_path": str(file),
                    "dest_path": str(config.G_DRIVE / folder.name / file.name),
                    "status": "pending",
                    "added_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                })
    print(f"\n  New cards added to index: {new_count}")
    pause()
