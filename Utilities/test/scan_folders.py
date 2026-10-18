"""
scan_folders.py
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

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".tif", ".tiff"}

JAPANESE_GAMES = {
    "Weiss Schwarz", "Cardfight Vanguard", "Digimon", "Pokemon", "One Piece",
    "Dragon Ball", "Yu-Gi-Oh", "Flesh and Blood", "Final Fantasy", "Gundam"
}

# ============================================================
# DEBUG MODE — flip to False for quiet runs
# ============================================================
DEBUG = True


def _dbg(msg):
    if DEBUG:
        print(f"[DEBUG] {msg}")


def _lang(game_name):
    return "japanese" if game_name in JAPANESE_GAMES else "english"


def baseline():
    """ONE-TIME: scan Folder Database only. Mark all as done/uploaded."""
    root = Path(config_v2.FOLDER_DATABASE_DIR)
    if not root.exists():
        print(f"[BASELINE] Folder Database not found: {root}")
        return

    added = skipped = 0
    print(f"[BASELINE] Scanning {root} ...")
    for img in root.rglob("*"):
        if img.suffix.lower() not in IMAGE_EXTS:
            continue
        rel = img.relative_to(root).parts
        game = rel[0]
        set_name = rel[-2] if len(rel) > 2 else None
        image_id = img.stem.replace("_200w", "")

        if db_v2.tracker_find_one(image_id, game):
            skipped += 1
            _dbg(f"SKIP (already tracked): {image_id} [{game}]")
            continue

        db_v2.tracker_mark_reviewed(image_id, game, "yes")
        db_v2.tracker_mark_uploaded(image_id, game, None, set_name, False)
        added += 1
        _dbg(f"ADD  (done/uploaded): {image_id} [{game}] set={set_name}")

    print(f"[BASELINE] Added {added}, skipped {skipped} (already present)")
    print(f"[BASELINE] card_tracker total: {db_v2.tracker_total()}")


def scan_new():
    """Scan New Cards and add anything not already tracked as pending."""
    root = Path(config_v2.NEW_CARDS_DIR)
    if not root.exists():
        print(f"[SCAN] New Cards not found: {root}")
        return

    added = skipped = 0
    print(f"[SCAN] Scanning {root} ...")
    for img in root.rglob("*"):
        if img.suffix.lower() not in IMAGE_EXTS:
            continue
        rel = img.relative_to(root).parts
        game = rel[0]
        set_name = rel[-2] if len(rel) > 2 else None
        image_id = img.stem.replace("_200w", "")

        if db_v2.tracker_find_one(image_id, game):
            skipped += 1
            _dbg(f"SKIP (already tracked): {image_id} [{game}]")
            continue

        db_v2.tracker_mark_pending(image_id, game, set_name, _lang(game))
        added += 1
        _dbg(f"ADD  (pending): {image_id} [{game}] set={set_name} lang={_lang(game)}")

    print(f"[SCAN] Added {added} pending, skipped {skipped} (already tracked)")
    print(f"[SCAN] card_tracker total: {db_v2.tracker_total()}")


if __name__ == "__main__":
    print("What do you want to scan?")
    print("  1. Folder Database (baseline — already uploaded/tagged)")
    print("  2. New Cards (add pending)")
    choice = input("Enter 1 or 2: ").strip()

    choice = sys.argv[1] if len(sys.argv) > 1 else "baseline"

    if choice in ("baseline", "1"):
        baseline()
    elif choice in ("new", "2"):
        scan_new()
    else:
        print(f"Unknown mode: {choice}")
        print("Usage: python scan_folders.py [baseline|new]")
        print("  (no arg defaults to baseline)")
