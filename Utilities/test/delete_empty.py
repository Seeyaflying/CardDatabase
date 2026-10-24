#!/usr/bin/env python3
"""
delete_empty_newcard_folders.py

Find all completely empty subfolders under the 'New Cards' directory and
delete them, after confirmation.

Empty = no files at all (including hidden files), and no subfolders
that themselves contain anything. We check bottom-up so a folder that
becomes empty after its empty children are removed is also caught.

Usage:
    python delete_empty_newcard_folders.py            # clean output
    python delete_empty_newcard_folders.py --debug    # verbose per-folder logging
    python delete_empty_newcard_folders.py --dry-run  # list only, delete nothing
"""

import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
NEW_CARDS_DIR = "T:/Full Card Database/New Cards"


def is_dir_empty(path: Path) -> bool:
    """True if the directory has no entries at all (files or subdirs)."""
    try:
        return not any(path.iterdir())
    except PermissionError:
        return False


def find_empty_dirs(root: Path, debug: bool) -> list[Path]:
    """
    Walk the tree bottom-up and return directories that are empty,
    or that become empty once their empty children are removed.
    Prints each game/set folder as it is scanned.
    """
    empty = []

    # Walk depth-first, children before parents.
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        d = Path(dirpath)

        # Print what we're scanning (game/set folder names).
        print(f"  [scan ] {d}")

        # A dir is a candidate if it has no files.
        if not filenames:
            # Remove any subdirs we already flagged as empty (they'll be gone).
            remaining = [
                (d / name)
                for name in dirnames
                if (d / name) not in empty and (d / name).exists()
            ]
            if not remaining:
                empty.append(d)
                if debug:
                    print(f"  [empty] {d}")

    return empty


def main():
    debug = "--debug" in sys.argv
    dry_run = "--dry-run" in sys.argv

    new_cards_dir = Path(NEW_CARDS_DIR)

    if not new_cards_dir.exists():
        print(f"ERROR: New Cards directory not found: {new_cards_dir}")
        sys.exit(1)

    print(f"Scanning {new_cards_dir} for empty folders...\n")

    empty_dirs = find_empty_dirs(new_cards_dir, debug)

    if not empty_dirs:
        print("\nNo empty folders found. Nothing to do.")
        return

    print(f"\nFound {len(empty_dirs)} empty folder(s):\n")
    for d in empty_dirs:
        print(f"  {d}")

    if dry_run:
        print(f"\nDry run: {len(empty_dirs)} folder(s) would be deleted.")
        return

    # Confirmation
    answer = input(f"\nDelete these {len(empty_dirs)} empty folder(s)? [y/N] ").strip().lower()
    if answer not in ("y", "yes"):
        print("Aborted. Nothing deleted.")
        return

    # Delete
    deleted = 0
    for d in empty_dirs:
        try:
            d.rmdir()  # rmdir only works on empty dirs — safe
            deleted += 1
            print(f"  [deleted] {d}")
        except OSError as e:
            print(f"  [failed ] {d}  ({e})")

    print(f"\nDone. Deleted {deleted} of {len(empty_dirs)} empty folder(s).")


if __name__ == "__main__":
    main()
