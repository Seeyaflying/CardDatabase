"""
check_new_vs_others.py — one-time check + cleanup
Finds files in New Cards that already exist (same image id) in
Card Upload, Folder Database, or Skipped Cards. Ignores the _200w suffix.

Usage:
    python check_new_vs_others.py            # clean output (default)
    python check_new_vs_others.py --debug    # verbose, one line per card
"""
import os
import sys

NEW_DIR = r"T:\Full Card Database\New Cards"
UPLOAD_DIR = r"T:\Full Card Database\Card Upload"
DB_DIR = r"T:\Full Card Database\Folder Database"
SKIP_DIR = r"T:\Full Card Database\Skipped Cards"

DEBUG = "--debug" in sys.argv


def image_id(filename):
    """Strip extension and the _200w suffix -> the card's id."""
    base = os.path.splitext(filename)[0]
    if base.lower().endswith("_200w"):
        base = base[:-5]
    return base


def collect_ids(root, label):
    """Return set of image ids under a folder. Per-card lines only in debug."""
    ids = set()
    if not os.path.isdir(root):
        print(f"[WARN] Path does not exist: {root}")
        return ids
    n = 0
    for game in sorted(os.listdir(root), key=str.lower):
        game_dir = os.path.join(root, game)
        if not os.path.isdir(game_dir):
            continue
        for dirpath, _, files in os.walk(game_dir):
            for fname in sorted(files):
                n += 1
                ids.add(image_id(fname))
                if DEBUG:
                    print(f"  [{label}] {n}  {game}/{fname}")
    print(f"  {label} total: {n}")
    return ids


def main():
    print("=" * 70)
    print("NEW CARDS vs UPLOAD/FOLDER DB/SKIPPED DUPLICATE CHECK")
    if DEBUG:
        print("  (debug mode: one line per card)")
    print("=" * 70)

    print("\nScanning Card Upload...")
    upload_ids = collect_ids(UPLOAD_DIR, "UPLOAD")

    print("\nScanning Folder Database...")
    db_ids = collect_ids(DB_DIR, "FD")

    print("\nScanning Skipped Cards...")
    skip_ids = collect_ids(SKIP_DIR, "SKIP")

    print("\nScanning New Cards...")
    if not os.path.isdir(NEW_DIR):
        print(f"[WARN] Path does not exist: {NEW_DIR}")
        return
    new_count = 0
    dup_upload = []
    dup_db = []
    dup_skip = []
    for game in sorted(os.listdir(NEW_DIR), key=str.lower):
        game_dir = os.path.join(NEW_DIR, game)
        if not os.path.isdir(game_dir):
            continue
        for dirpath, _, files in os.walk(game_dir):
            for fname in sorted(files):
                iid = image_id(fname)
                new_count += 1
                in_up = iid in upload_ids
                in_db = iid in db_ids
                in_skip = iid in skip_ids
                if in_up:
                    dup_upload.append(os.path.join(dirpath, fname))
                if in_db:
                    dup_db.append(os.path.join(dirpath, fname))
                if in_skip:
                    dup_skip.append(os.path.join(dirpath, fname))
                if DEBUG:
                    if in_up:
                        status = "DUP-UPLOAD"
                    elif in_db:
                        status = "DUP-FD"
                    elif in_skip:
                        status = "DUP-SKIP"
                    else:
                        status = "OK"
                    print(f"[{new_count}] {game}/{fname}  ->  {status}")
    print(f"\nTotal New Cards files: {new_count}")
    print(f"  {len(dup_upload)} already in Card Upload")
    print(f"  {len(dup_db)} already in Folder Database")
    print(f"  {len(dup_skip)} already in Skipped Cards")

    if dup_upload:
        print("\n>>> In Card Upload:")
        for i, p in enumerate(dup_upload, 1):
            print(f"    [{i}] {p}")
    if dup_db:
        print("\n>>> In Folder Database:")
        for i, p in enumerate(dup_db, 1):
            print(f"    [{i}] {p}")
    if dup_skip:
        print("\n>>> In Skipped Cards:")
        for i, p in enumerate(dup_skip, 1):
            print(f"    [{i}] {p}")

    # --- Cleanup with confirmation ---
    to_delete = dup_upload + dup_db + dup_skip
    total = len(to_delete)
    if total == 0:
        print("\nNo duplicates to delete.")
        print("=" * 70)
        return

    print("\n" + "=" * 70)
    print(f"Ready to delete {total} duplicate New Cards file(s).")
    print("These files already exist in Card Upload / Folder Database / Skipped Cards.")
    print("=" * 70)
    answer = input(f"\nDelete {total} duplicate file(s) from New Cards? [y/N]: ").strip().lower()
    if answer not in ("y", "yes"):
        print("\nCancelled. No files were deleted.")
        print("=" * 70)
        return

    deleted = 0
    for i, path in enumerate(to_delete, 1):
        try:
            os.remove(path)
            deleted += 1
            print(f"[{i}/{total}] DELETED  {path}")
        except FileNotFoundError:
            print(f"[{i}/{total}] SKIP (already gone)  {path}")
        except OSError as e:
            print(f"[{i}/{total}] ERROR  {path}: {e}")

    print("\n" + "=" * 70)
    print(f"DONE. Deleted {deleted} of {total} duplicate file(s).")
    print("=" * 70)


if __name__ == "__main__":
    main()


