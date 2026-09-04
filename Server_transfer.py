import os
import shutil
from pathlib import Path

# ============================================================
# Configuration — edit these
# ============================================================

SOURCE = Path(r"T:\Cards Done")
BACKUP_MEMORY = SOURCE / "Backed Up"
DEST = Path(r"G:\My Drive\Card Database")

REPORT_FILE = Path.home() / "card-database-manager" / "verification-report.txt"
DIFFERENCES_FILE = Path.home() / "card-database-manager" / "verification-differences.txt"
COMBINED_FILE = Path.home() / "card-database-manager" / "verification-combined.txt"


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
    BACKUP_MEMORY.mkdir(parents=True, exist_ok=True)
    DEST.mkdir(parents=True, exist_ok=True)
    (Path.home() / "card-database-manager").mkdir(parents=True, exist_ok=True)


def _write_report(message):
    with open(REPORT_FILE, "a", encoding="utf-8") as f:
        f.write(message + "\n")


def _write_difference(message):
    with open(DIFFERENCES_FILE, "a", encoding="utf-8") as f:
        f.write(message + "\n")


def _write_combined(message):
    with open(COMBINED_FILE, "a", encoding="utf-8") as f:
        f.write(message + "\n")


def _progress(done, total):
    """Draw a single-line progress bar that updates in place."""
    width = 30
    if total == 0:
        return
    filled = int(width * done / total)
    bar = "#" * filled + "-" * (width - filled)
    pct = done / total * 100
    print(f"\r  [{bar}] {done:,}/{total:,} ({pct:.1f}%)", end="", flush=True)
    if done == total:
        print()


def game_folders():
    return sorted(
        [p for p in SOURCE.iterdir() if p.is_dir() and p.name != "Backed Up"],
        key=lambda p: p.name.lower(),
    )


# ============================================================
# Actions
# ============================================================

def copy_and_archive():
    clear_screen()
    print("=" * 70)
    print("COPY & ARCHIVE (full run)")
    print("=" * 70)
    print(f"\nSource:      {SOURCE}")
    print(f"Destination: {DEST}")
    print("\nCopies every active file to the destination, then moves")
    print("the original into Backed Up if the copy succeeded.")
    print("\nStarting...\n")

    copied = archived = skipped = errors = 0

    for folder in game_folders():
        dest_folder = DEST / folder.name
        dest_folder.mkdir(parents=True, exist_ok=True)

        files = [f for f in folder.iterdir() if f.is_file()]
        total = len(files)
        done = 0

        print(f"\n{folder.name} ({total} files)")

        for file in files:
            if (BACKUP_MEMORY / file.name).exists():
                skipped += 1
                done += 1
                continue

            dest_file = dest_folder / file.name
            try:
                shutil.copy2(str(file), str(dest_file))
                copied += 1
                if file.stat().st_size != dest_file.stat().st_size:
                    raise RuntimeError("size mismatch after copy")
                shutil.move(str(file), str(BACKUP_MEMORY / file.name))
                archived += 1
                _write_combined(f"COPIED & ARCHIVED: {folder.name} / {file.name}")
            except Exception as e:
                errors += 1
                print(f"\n  ERROR: {file.name}: {e}")
                _write_difference(f"ERROR: {folder.name} / {file.name} - {e}")

            done += 1
            _progress(done, total)

    print("\n" + "=" * 70)
    print("COMPLETE")
    print("=" * 70)
    print(f"  Copied:   {copied}")
    print(f"  Archived: {archived}")
    print(f"  Skipped:  {skipped}")
    print(f"  Errors:   {errors}")
    pause()


def copy_only():
    """Copy to destination but leave originals in place (no archive)."""
    clear_screen()
    print("=" * 70)
    print("COPY ONLY (no archive)")
    print("=" * 70)

    copied = skipped = errors = 0

    for folder in game_folders():
        dest_folder = DEST / folder.name
        dest_folder.mkdir(parents=True, exist_ok=True)

        files = [f for f in folder.iterdir() if f.is_file()]
        total = len(files)
        done = 0

        print(f"\n{folder.name} ({total} files)")

        for file in files:
            dest_file = dest_folder / file.name
            if dest_file.exists() and dest_file.stat().st_size == file.stat().st_size:
                skipped += 1
                done += 1
                _progress(done, total)
                continue
            try:
                shutil.copy2(str(file), str(dest_file))
                copied += 1
                _write_combined(f"COPIED: {folder.name} / {file.name}")
            except Exception as e:
                errors += 1
                print(f"\n  ERROR: {file.name}: {e}")
                _write_difference(f"ERROR: {folder.name} / {file.name} - {e}")
            done += 1
            _progress(done, total)

    print("\n" + "=" * 70)
    print("COMPLETE")
    print("=" * 70)
    print(f"  Copied:  {copied}")
    print(f"  Skipped: {skipped}")
    print(f"  Errors:  {errors}")
    pause()


def archive_only():
    """Move files that already exist on the destination into Backed Up."""
    clear_screen()
    print("=" * 70)
    print("ARCHIVE ONLY (no copy)")
    print("=" * 70)

    archived = skipped = errors = 0

    for folder in game_folders():
        dest_folder = DEST / folder.name
        files = [f for f in folder.iterdir() if f.is_file()]
        total = len(files)
        done = 0

        print(f"\n{folder.name} ({total} files)")

        for file in files:
            if (BACKUP_MEMORY / file.name).exists():
                skipped += 1
                done += 1
                _progress(done, total)
                continue

            dest_file = dest_folder / file.name
            if not dest_file.exists():
                # Not on destination yet — leave it in place.
                skipped += 1
                done += 1
                _progress(done, total)
                continue

            try:
                if file.stat().st_size == dest_file.stat().st_size:
                    shutil.move(str(file), str(BACKUP_MEMORY / file.name))
                    archived += 1
                    _write_combined(f"ARCHIVED: {folder.name} / {file.name}")
                else:
                    errors += 1
                    print(f"\n  SIZE MISMATCH: {file.name}")
                    _write_difference(f"SIZE MISMATCH: {folder.name} / {file.name}")
            except Exception as e:
                errors += 1
                print(f"\n  ERROR: {file.name}: {e}")
                _write_difference(f"ERROR: {folder.name} / {file.name} - {e}")

            done += 1
            _progress(done, total)

    print("\n" + "=" * 70)
    print("COMPLETE")
    print("=" * 70)
    print(f"  Archived: {archived}")
    print(f"  Skipped:  {skipped}")
    print(f"  Errors:   {errors}")
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
    print(f"\n1. Combined results:  {COMBINED_FILE}")
    print(f"2. Differences:      {DIFFERENCES_FILE}")
    print(f"3. Summary report:   {REPORT_FILE}")
    choice = input("\nWhich report? (1-3): ").strip()
    path = {1: COMBINED_FILE, 2: DIFFERENCES_FILE, 3: REPORT_FILE}.get(int(choice) if choice.isdigit() else 0)
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
    print("\n  1. Copy & Archive (full run)")
    print("  2. Copy only (no archive)")
    print("  3. Archive only (no copy)")
    print("  4. Remove empty folders")
    print("  5. View reports")
    print("  6. Exit")


def main():
    ensure_directories()
    while True:
        show_menu()
        choice = input("\nEnter your choice (1-6): ").strip()

        if choice == "1":
            copy_and_archive()
        elif choice == "2":
            copy_only()
        elif choice == "3":
            archive_only()
        elif choice == "4":
            clean_empty_folders()
        elif choice == "5":
            view_reports()
        elif choice == "6":
            print("\nGoodbye.")
            break
        else:
            print("\nInvalid choice. Please enter 1-6.")
            input("\nPress Enter to continue...")
            clear_screen()


if __name__ == "__main__":
    main()
