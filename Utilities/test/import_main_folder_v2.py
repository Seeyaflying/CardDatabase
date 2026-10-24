# insert_main_folders_v2.py

"""Inserts the main folder images (under the "Folder Database" tree) into the
unified card tracker (`card_tracker`) as normal 'pending' records.

This runs BEFORE the skipped merge. The skipped merge later matches against
these records and flags the ones it handles with `skipped: true`.

Read-only to the DB except for inserts (no deletes, no updates to existing
records). Re-runnable: a file already present (image_name + game_name) is
skipped, so nothing is duplicated.

Run it with no arguments and answer the prompts:

    python insert_main_folders_v2.py

Design notes (matches config_v2 / db_v2 conventions):

- image_id  = file stem with "_200w" stripped (same as scan_folders_v2).
- game_name = first path segment under MAIN_DIR.
- set_name  = second path segment (if present).
- language  = parsed from the filename suffix -> full ISO name
              (en->english, de->german, es->spanish, fr->french,
               it->italian, ja->japanese, ...), else None.
- A record is inserted only if image_name + game_name is not already tracked.
"""

from pathlib import Path
import os
import sys
from datetime import datetime

import config_v2
import db_v2

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

# Verbose per-line logging. False = quiet (only summaries + errors).
DEBUG = True

# Root of the main folder tree.
MAIN_DIR = r"T:\Full Card Database\Folder Database"

# Image extensions we consider.
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".tif", ".tiff"}

# Map filename language suffix -> full ISO name stored in the DB.
# Add/remove codes as needed.
LANG_MAP = {
    "en": "english",
    "de": "german",
    "es": "spanish",
    "fr": "french",
    "it": "italian",
    "ja": "japanese",
    "pt": "portuguese",
    "ru": "russian",
    "zh": "chinese",
    "ko": "korean",
    "zhs": "chinese",
    "zht": "chinese",
}

# ---------------------------------------------------------------------------
# END CONFIG
# ---------------------------------------------------------------------------


def _dbg(msg):
    if DEBUG:
        print(f"[DEBUG] {msg}")


def _ask(prompt, default):
    """Ask a yes/no question. Returns the boolean default if the user hits enter."""
    while True:
        answer = input(f"{prompt} [y/N] (default {default}): ").strip().lower()
        if answer == "":
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("  Please answer y or n.")


def _language_from_stem(stem: str):
    """Parse the language from a filename stem's trailing suffix.

    'Splendid Reclamation_it' -> 'italian'
    'Beast_en'                -> 'english'
    'Wastes'                  -> None  (no recognizable suffix)
    """
    parts = stem.rsplit("_", 1)
    if len(parts) == 2 and parts[1].lower() in LANG_MAP:
        return LANG_MAP[parts[1].lower()]
    return None


def _build_doc(image_id: str, game: str, set_name, language, file_path: str):
    """Build the card_tracker document for a main-folder file.

    Matches the real schema seen in card_tracker (no 'skipped' field yet).
    """
    return {
        "image_name": image_id,
        "game_name": game,
        "set": set_name,
        "set_name": set_name,
        "language": language,
        "file_path": file_path,
        "uploaded": False,
        "uploaded_at": None,
        "asset_id": None,
        "is_duplicate": False,
        "processed_at": None,
        "status": "pending",
    }


def _handle_file(img: Path, game: str, set_name, dry: bool):
    """Process one image file in the main folder tree.

    Returns an action string:
      "inserted" — record added
      "exists"   — already tracked, left alone
      "error"    — something went wrong
    """
    image_id = img.stem.replace("_200w", "")
    language = _language_from_stem(img.stem)

    # 1. Only insert if not already tracked (image_name + game_name).
    if db_v2.tracker_find_one(image_id, game):
        _dbg(f"EXISTS: {img}  ->  image_id={image_id} [{game}] set={set_name}")
        return "exists"

    if dry:
        _dbg(f"ADD   : {img}  ->  image_id={image_id} [{game}] set={set_name} lang={language}")
        return "inserted"

    doc = _build_doc(image_id, game, set_name, language, str(img))
    db_v2.tracker_insert(doc)
    _dbg(f"ADD   : {img}  ->  image_id={image_id} [{game}] set={set_name} lang={language}")
    return "inserted"


def _scan_game(root: Path, game: str, dry: bool):
    """Walk one game's main-folder tree. Returns a count dict."""
    counts = {"inserted": 0, "exists": 0, "error": 0}

    if not root.exists():
        print(f"[SCAN] Folder not found: {root}")
        return counts

    print(f"[SCAN] {game} -> {root}")

    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        rel = current.relative_to(root).parts
        set_name = rel[0] if rel else None

        for name in filenames:
            img = current / name
            if img.suffix.lower() not in IMAGE_EXTS:
                continue

            action = _handle_file(img, game, set_name, dry)
            counts[action] += 1

    return counts


def main():
    print("=== Insert Main Folder Cards ===\n")

    # --- Ask whether to actually write (dry run = report only) ---
    write_db = _ask("Write to the database?", True)

    root = Path(MAIN_DIR)
    if not root.exists():
        print(f"[FATAL] Main folder not found: {root}")
        sys.exit(1)

    dry = not write_db

    print(f"\n=== SCANNING ALL GAMES under {root} (write={write_db}) ===\n")

    totals = {"inserted": 0, "exists": 0, "error": 0}

    for game_dir in sorted(root.iterdir()):
        if not game_dir.is_dir():
            continue
        game_name = game_dir.name
        c = _scan_game(game_dir, game_name, dry=dry)
        for k in totals:
            totals[k] += c[k]

    print(f"\n=== SUMMARY ===")
    print(f"  inserted : {totals['inserted']}")
    print(f"  exists   : {totals['exists']}")
    print(f"  errors   : {totals['error']}")
    print(f"  card_tracker total: {db_v2.tracker_total()}")


if __name__ == "__main__":
    main()
