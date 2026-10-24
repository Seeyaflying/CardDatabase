# merge_skipped_v2.py

"""Merges images from the "Skipped Cards" folders into the unified card tracker (`card_tracker`), flagging each as `skipped` so miners skip them and don't re-download. Once a file is handled (matched or inserted), it is DELETED from the skipped folder.

Three modes, chosen interactively:

dry    — walk & report only. No DB writes, no file deletes. Prints a JSON preview of the first 5 files that would be written.
folder — real DB writes + file deletes, but restricted to ONE game folder.
live   — real DB writes + file deletes across the ENTIRE SKIPPED_DIR tree, then drops the legacy skipped collections.

Run it with no arguments and answer the prompts:

    python merge_skipped_v2.py

Design notes (matches config_v2 / db_v2 conventions):

- All MongoDB access goes through db_v2 helpers.
- image_id = file stem with "_200w" stripped (same as scan_folders_v2).
- game_name = first path segment under SKIPPED_DIR.
- set_name  = second path segment (if present).
- language  = parsed from the filename suffix -> full ISO name
              (en->english, de->german, es->spanish, fr->french,
               it->italian, ja->japanese, ...), else None.
- Matched record  -> set skipped=True + skipped_at (keep existing card data).
- Unmatched file  -> insert new record with skipped=True (a blocklist entry).
- Both legacy collections `skipped_images` and `folder_skipped_images` are DROPPED only in `live` mode, after the merge completes.
"""

from pathlib import Path
import os
import sys
import json
from datetime import datetime

import config_v2
import db_v2

# ---------------------------------------------------------------------------
# CONFIG — three toggles
# ---------------------------------------------------------------------------

# Verbose per-line logging. False = quiet (only summaries + errors).
DEBUG = True

# Image extensions we consider. Add/remove as needed.
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".tif", ".tiff"}

# The two legacy skipped collections to drop at the end of the LIVE run.
LEGACY_SKIPPED_COLLECTIONS = ["skipped_images", "folder_skipped_images"]

# How many sample files to show in the dry-run JSON preview.
SAMPLE_SIZE = 5

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

# --- Toggles ----------------------------------------------------------------
# These are asked at the start of every run (input options, not parameters).

# Write to the DB (flag records + insert unmatched). False = report only.
TOGGLE_WRITE_DB = True

# Delete files from the skipped folders after they are handled.
TOGGLE_DELETE_FILES = True

# Insert unmatched files as new skipped records (False = leave them alone).
TOGGLE_INSERT_UNMATCHED = True

# ---------------------------------------------------------------------------
# END CONFIG
# ---------------------------------------------------------------------------


def _dbg(msg):
    if DEBUG:
        print(f"[DEBUG] {msg}")


def _skipped_root():
    """Root of the skipped-cards tree, from config."""
    return Path(config_v2.SKIPPED_DIR)


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


def _build_doc(image_id: str, game: str, set_name, existing: bool, stem: str):
    """Build the JSON document that would be written to card_tracker."""
    doc = {
        "image_name": image_id,
        "game_name": game,
        "set_name": set_name,
        "language": _language_from_stem(stem),   # was "lang": "en"
        "file_path": None,
        "uploaded": False,
        "asset_id": None,
        "is_duplicate": False,
        "skipped": True,
        "skipped_at": datetime.utcnow().isoformat() + "Z",
    }
    if existing:
        doc["status"] = "pending"  # existing card keeps its status
    else:
        doc["status"] = "skipped"  # new blocklist entry
    return doc


def _handle_file(img: Path, game: str, set_name, dry: bool, samples: list):
    """Process one image file in the skipped folder.

    Returns an action string:
      "matched"  — record existed, flagged skipped
      "inserted" — record didn't exist, added as skipped
      "skipped"  — unmatched and TOGGLE_INSERT_UNMATCHED is False (left alone)
      "error"    — something went wrong (file not deleted)
    """
    image_id = img.stem.replace("_200w", "")

    # 1. Try to match an existing card in card_tracker.
    existing = db_v2.tracker_find_one(image_id, game)

    if existing:
        action = "matched"
        if not dry:
            db_v2.tracker_mark_skipped(image_id, game)
        _dbg(f"FLAG (matched): {img}  ->  image_id={image_id} [{game}] set={set_name}")
    else:
        if TOGGLE_INSERT_UNMATCHED:
            action = "inserted"
            if not dry:
                db_v2.tracker_mark_skipped_new(image_id, game, set_name)
            _dbg(f"ADD  (new skipped): {img}  ->  image_id={image_id} [{game}] set={set_name}")
        else:
            action = "skipped"  # unmatched, not inserted — leave alone
            _dbg(f"SKIP (unmatched, insert off): {img}  ->  image_id={image_id} [{game}]")

    # 2. Delete the file only after it is handled (matched or inserted),
    #    and only if file deletion is enabled.
    if not dry and TOGGLE_DELETE_FILES and action in ("matched", "inserted"):
        try:
            img.unlink()
            _dbg(f"DEL  {img}")
        except OSError as e:
            print(f"[ERROR] Could not delete {img}: {e}")
            action = "error"

    # Collect the first SAMPLE_SIZE files for the dry-run JSON preview.
    if dry and len(samples) < SAMPLE_SIZE:
        samples.append({
            "action": action,
            "file": str(img),
            "image_id": image_id,
            "game": game,
            "set_name": set_name,
            "doc": _build_doc(image_id, game, set_name, existing, img.stem),
        })

    return action


def _scan_game(root: Path, game: str, dry: bool, samples: list):
    """Walk one game's skipped folder tree. Returns a count dict."""
    counts = {"matched": 0, "inserted": 0, "skipped": 0, "error": 0}

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

            action = _handle_file(img, game, set_name, dry, samples)
            counts[action] += 1

    return counts


def _print_sample(samples: list):
    """Print the JSON documents for the collected sample files (dry run)."""
    print(f"\n=== SAMPLE ({len(samples)} of {SAMPLE_SIZE} files) ===\n")
    for i, s in enumerate(samples, 1):
        print(f"[{i}] {s['action'].upper()}")
        print(f"    File : {s['file']}")
        print(f"    Match: image_id={s['image_id']} [{s['game']}] set={s['set_name']}")
        print("    JSON :")
        print(json.dumps(s["doc"], indent=2))
        print()


def run_mode(mode: str, game: str = None):
    """Execute a mode. mode: "dry" | "folder" | "live"; game restricts to one."""
    root = _skipped_root()
    if not root.exists():
        print(f"[FATAL] SKIPPED_DIR not found: {root}")
        sys.exit(1)

    dry = (mode == "dry")

    # Determine which game subfolders to scan.
    if game:
        targets = [root / game]
        if not targets[0].exists():
            print(f"[FATAL] Game folder not found: {targets[0]}")
            sys.exit(1)
    else:
        targets = [d for d in sorted(root.iterdir()) if d.is_dir()]

    totals = {"matched": 0, "inserted": 0, "skipped": 0, "error": 0}
    samples = []
    print(f"\n=== MODE: {mode.upper()} ===\n")

    for target in targets:
        game_name = target.name
        c = _scan_game(target, game_name, dry=dry, samples=samples)
        for k in totals:
            totals[k] += c[k]

    print(f"\n=== {mode.upper()} SUMMARY ===")
    print(f"  matched  : {totals['matched']}")
    print(f"  inserted : {totals['inserted']}")
    print(f"  skipped  : {totals['skipped']}")
    print(f"  errors   : {totals['error']}")
    print(f"  card_tracker total: {db_v2.tracker_total()}")

    if mode == "dry" and samples:
        _print_sample(samples)

    if mode == "live" and not dry:
        _drop_legacy_collections()


def _drop_legacy_collections():
    """Drop the two old skipped collections (live mode only)."""
    db = db_v2.get_db()
    for name in LEGACY_SKIPPED_COLLECTIONS:
        if name in db.list_collection_names():
            db.drop_collection(name)
            print(f"[DROP] Dropped collection: {name}")
        else:
            print(f"[DROP] Collection not present (skipped): {name}")


def main():
    print("=== Merge Skipped Cards ===\n")

    # --- Ask for the mode (input option, not a parameter) ---
    while True:
        mode = input("Mode (dry / folder / live): ").strip().lower()
        if mode in ("dry", "folder", "live"):
            break
        print("  Please enter dry, folder, or live.")

    # --- Ask for the game (only meaningful for folder mode) ---
    game = None
    if mode == "folder":
        game = input("Game folder (default Digimon): ").strip() or "Digimon"
    elif mode == "live":
        print("[INFO] live mode scans ALL games under SKIPPED_DIR.")

    # --- Ask the three toggles (input options) ---
    print()
    if mode == "dry":
        # Dry run never writes or deletes; toggles are irrelevant but asked anyway.
        print("[INFO] dry mode: reporting only, nothing will be written or deleted.")
    else:
        TOGGLE_WRITE_DB = _ask("Write to the database?", True)
        TOGGLE_DELETE_FILES = _ask("Delete files from skipped folders after handling?", True)
        TOGGLE_INSERT_UNMATCHED = _ask("Insert unmatched files as new skipped records?", True)

    run_mode(mode, game)


if __name__ == "__main__":
    main()