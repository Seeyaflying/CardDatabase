"""
scan_folders_v2.py
===============
Populates the `card_tracker` collection.

  1. baseline() — ONE-TIME scan of FOLDER_DATABASE_DIR only.
                   Marks everything there as already uploaded/tagged
                   (status='yes', uploaded=True). This is the starting baseline.
  2. scan_new()  — Scans NEW_CARDS_DIR, adds files not already tracked
                   as status='pending'.

card_tracker is the single source of truth. `progress` and `immich_upload`
are retired — nothing writes to them anymore.

DEBUG = True  -> prints every file as it's processed (verbose, per-line)
DEBUG = False -> prints only summary lines and errors
"""
from pathlib import Path

import config_v2
import db_v2
import sys
import os

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".tif", ".tiff"}

# ============================================================
# DEBUG MODE — flip to False for quiet runs
# ============================================================
DEBUG = True


def _dbg(msg):
    if DEBUG:
        print(f"[DEBUG] {msg}")


def _scan_folder(root, mark_done):
    if not root.exists():
        print(f"[SCAN] Folder not found: {root}")
        return 0, 0

    added = skipped = 0
    print(f"[SCAN] Scanning {root} ...")

    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        rel = current.relative_to(root).parts

        # Print the folder we're about to scan (game name, then set name).
        if rel:
            label = rel[0] if len(rel) == 1 else f"{rel[0]} / {rel[1]}"
            print(f"[SCAN] {label}")

        for name in filenames:
            img = current / name
            if img.suffix.lower() not in IMAGE_EXTS:
                continue

            game = rel[0]
            # Set is the SECOND level below the root (Root/Game/Set/file.jpg).
            set_name = rel[1] if len(rel) >= 2 else None
            image_id = img.stem.replace("_200w", "")

            if db_v2.tracker_find_one(image_id, game):
                skipped += 1
                _dbg(f"SKIP (already tracked): {image_id} [{game}]")
                continue

            if mark_done:
                db_v2.tracker_mark_reviewed(image_id, game, "yes")
                db_v2.tracker_mark_uploaded(image_id, game, None, set_name, False)
                _dbg(f"ADD  (done/uploaded): {image_id} [{game}] set={set_name}")
            else:
                # No hardcoded language — null means the app decides per card/folder.
                db_v2.tracker_mark_pending(
                    image_id, game, set_name, None, file_path=str(img)
                )
                _dbg(f"ADD  (pending): {image_id} [{game}] set={set_name}")
            added += 1

    return added, skipped


def baseline():
    """ONE-TIME: scan Folder Database only. Mark all as done/uploaded."""
    added, skipped = _scan_folder(Path(config_v2.FOLDER_DATABASE_DIR), mark_done=True)
    print(f"[BASELINE] Added {added}, skipped {skipped} (already present)")
    print(f"[BASELINE] card_tracker total: {db_v2.tracker_total()}")


def scan_new():
    """Scan New Cards, add files not already tracked as pending."""
    added, skipped = _scan_folder(Path(config_v2.NEW_CARDS_DIR), mark_done=False)
    print(f"[SCAN] Added {added} pending, skipped {skipped} (already tracked)")
    print(f"[SCAN] card_tracker total: {db_v2.tracker_total()}")


def main_menu():
    """Interactive menu for choosing what to scan."""
    while True:
        print("\n=== Card Sorter — Scan Menu ===")
        print("  1. Baseline — Folder Database (mark all as done/uploaded)")
        print("  2. New Cards (add pending)")
        print("  3. Exit")
        choice = input("Enter 1, 2, or 3: ").strip()

        if choice == "1":
            baseline()
        elif choice == "2":
            scan_new()
        elif choice == "3":
            print("Exiting.")
            break
        else:
            print("Invalid choice. Try again.")


if __name__ == "__main__":
    # CLI arg overrides the menu (handy for automation):
    #   python scan_folders_v2.py baseline
    #   python scan_folders_v2.py new
    if len(sys.argv) > 1:
        mode = sys.argv[1]
        if mode in ("baseline", "1"):
            baseline()
        elif mode in ("new", "2"):
            scan_new()
        else:
            print(f"Unknown mode: {mode}")
            print("Usage: python scan_folders_v2.py [baseline|new]")
    else:
        main_menu()
