"""transfer_gdrive.py — MOVE all cards from G: into the Card Database.
Moves per set, deletes set .json + empty set folder + empty game folder.
Preserves game -> set -> card structure. Per-line output throughout."""
import os
import shutil
from pathlib import Path
from collections import OrderedDict
import config_v2

SOURCE = Path(r"G:\My Drive\CCG Trader")
DEST = Path(config_v2.NEW_CARDS_DIR)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".tif", ".tiff"}

if not SOURCE.exists():
    print(f"[TRANSFER] Source not found: {SOURCE}")
    raise SystemExit
if not DEST.exists():
    print(f"[TRANSFER] Destination not found: {DEST}")
    raise SystemExit

# --- Live scan: per-folder and per-image lines ---
print(f"[TRANSFER] Scanning {SOURCE} ...")
files = []
for dirpath, dirnames, filenames in os.walk(SOURCE):
    d = Path(dirpath)
    print(f"[SCAN] folder: {d.relative_to(SOURCE)}")
    for name in filenames:
        p = d / name
        if p.suffix.lower() in IMAGE_EXTS:
            files.append(p)
            print(f"[SCAN]   image: {name}")

print(f"[TRANSFER] Found {len(files)} image files")

sets = OrderedDict()
for f in files:
    sets.setdefault(f.parent, []).append(f)
print(f"[TRANSFER] Found {len(sets)} set folders to process")

total_moved = total_skipped = total_errors = total_deleted = total_json = 0
deleted_games = set()

for s_idx, (parent, set_files) in enumerate(sets.items(), 1):
    rel_set = parent.relative_to(SOURCE)
    game_folder = parent.parent
    print(f"\n=== SET {s_idx}/{len(sets)}: {rel_set} ({len(set_files)} files) ===")

    set_moved = set_skipped = set_errors = 0
    for i, src in enumerate(set_files, 1):
        rel = src.relative_to(SOURCE)
        dst = DEST / rel
        try:
            if dst.exists():
                src.unlink()
                set_skipped += 1
                print(f"[TRANSFER] {i}/{len(set_files)} SKIP (already there): {rel}")
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            set_moved += 1
            print(f"[TRANSFER] {i}/{len(set_files)} MOVED: {rel}")
        except Exception as e:
            set_errors += 1
            print(f"[TRANSFER] {i}/{len(set_files)} ERROR {rel}: {e}")

    for jf in parent.glob("*.json"):
        try:
            jf.unlink()
            total_json += 1
            print(f"[TRANSFER] DELETED set .json: {jf.relative_to(SOURCE)}")
        except Exception as e:
            print(f"[TRANSFER] ERROR deleting .json {jf}: {e}")

    try:
        parent.rmdir()
        total_deleted += 1
        print(f"[TRANSFER] DELETED set folder: {rel_set}")
    except OSError:
        print(f"[TRANSFER] Set folder not empty, skipped delete: {rel_set}")

    if game_folder != SOURCE and game_folder not in deleted_games:
        try:
            game_folder.rmdir()
            deleted_games.add(game_folder)
            print(f"[TRANSFER] DELETED game folder (now empty): {game_folder.relative_to(SOURCE)}")
        except OSError:
            pass

    total_moved += set_moved
    total_skipped += set_skipped
    total_errors += set_errors
    print(f"--- SET DONE: {rel_set} -> moved {set_moved}, skipped {set_skipped}, errors {set_errors}")

print(f"\n[TRANSFER] ALL DONE - moved {total_moved}, skipped {total_skipped}, errors {total_errors}, "
      f"deleted {total_deleted} set folders, {total_json} set .json files, "
      f"{len(deleted_games)} game folders")
