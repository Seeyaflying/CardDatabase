# verify_main_folders_v2.py

"""Walks the MAIN folder database (T:\Full Card Database\<Game>\<Set>\)
and checks that every image file is present in card_tracker.

This is the same logic as the skipped-images merge, but pointed at the main
folder database instead of the skipped folders. It is READ-ONLY: it only
reports coverage — no writes, no deletes.

Run it with no arguments:

  python verify_main_folders_v2.py

Design notes (matches config_v2 / db_v2 conventions):

- All MongoDB access goes through db_v2 helpers.
- image_id = file stem with "_200w" stripped (same as scan_folders_v2).
- game_name = first path segment under MAIN_DIR.
- set_name  = second path segment (if present).
- For each file, looks up image_name + game_name in card_tracker.
- Every file prints a line showing whether it was found or missing
  (only when DEBUG = True).
- Missing files are also collected into a final list at the end.
"""

from pathlib import Path
import os
import sys

import config_v2
import db_v2

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

# Debug mode. True = print every file as it's checked ([FOUND]/[MISSING]).
# Set to False to quiet the per-line output (only [SCAN] lines + summary).
DEBUG = True

# Image extensions we consider. Add/remove as needed.
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".tif", ".tiff"}

# Root of the MAIN folder database (the parent of the game folders).
MAIN_DIR = r"T:/Full Card Database/Folder Database"

# ---------------------------------------------------------------------------
# END CONFIG
# ---------------------------------------------------------------------------


def _dbg(msg):
    if DEBUG:
        print(f"[DEBUG] {msg}")


def _main_root():
    """Root of the main folder database, from config."""
    return Path(MAIN_DIR)


def _verify_game(root: Path, game: str):
    """Check that every image file in a game's main folder exists in card_tracker.
    Returns (present, missing) counts and a list of missing files."""
    present = 0
    missing = 0
    missing_files = []

    if not root.exists():
        print(f"[SCAN] Folder not found: {root}")
        return 0, 0, missing_files

    print(f"[SCAN] {game} -> {root}")

    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        for name in filenames:
            img = current / name
            if img.suffix.lower() not in IMAGE_EXTS:
                continue

            image_id = img.stem.replace("_200w", "")
            existing = db_v2.tracker_find_one(image_id, game)
            if existing:
                present += 1
                _dbg(f"[FOUND] {img}  ->  image_id={image_id} [{game}]")
            else:
                missing += 1
                missing_files.append(str(img))
                _dbg(f"[MISSING] {img}  ->  image_id={image_id} [{game}]")

    return present, missing, missing_files


def main():
    print("=== Verify Main Folder Database ===\n")

    root = _main_root()
    if not root.exists():
        print(f"[FATAL] MAIN_DIR not found: {root}")
        sys.exit(1)

    targets = [d for d in sorted(root.iterdir()) if d.is_dir()]

    total_present = 0
    total_missing = 0
    all_missing = []

    print(f"\n=== MODE: VERIFY ===\n")

    for target in targets:
        game_name = target.name
        present, missing, missing_files = _verify_game(target, game_name)
        total_present += present
        total_missing += missing
        all_missing.extend(missing_files)

    print(f"\n=== VERIFY SUMMARY ===")
    print(f"  present in card_tracker : {total_present}")
    print(f"  MISSING from card_tracker: {total_missing}")
    print(f"  card_tracker total      : {db_v2.tracker_total()}")

    if all_missing:
        print(f"\n=== MISSING FILES ({len(all_missing)}) ===")
        for f in all_missing:
            print(f"  {f}")
    else:
        print("\n  All files in the main folders are present in card_tracker.")


if __name__ == "__main__":
    main()

