import os
import sqlite3
import signal
import sys
from datetime import datetime

# --- COLORS ---
G = '\033[92m'  # Green (Match)
DG = '\033[2m\033[92m'  # Dim Green (Skipped)
W = '\033[97m'  # White (New)
C = '\033[96m'  # Cyan (Headers)
Y = '\033[93m'  # Yellow (Timestamp)
R = '\033[91m'  # Red (Error)
RESET = '\033[0m'

IS_WINDOWS = os.name == 'nt'
SKIPPED_DB = "skipped_images.sqlite"
SAVE_THRESHOLD = 50  # Save every 50 new items to balance speed/safety

if IS_WINDOWS:
    os.system('color')
    BASE_LOCAL_PATH = r"G:\My Drive\Card Database"
else:
    BASE_LOCAL_PATH = "/home/seeyaflying/Desktop/GDrive/Card Database"


def signal_handler(sig, frame):
    print(f"\n{R}[!] MANUAL OVERRIDE: SAVING FINAL BUFFER AND EXITING...{RESET}")
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)


def get_dynamic_folders():
    """Scans the actual folder structure to populate the menu."""
    if not os.path.exists(BASE_LOCAL_PATH):
        print(f"{R}[!] ERROR: Path not found: {BASE_LOCAL_PATH}{RESET}")
        sys.exit(1)

    print(f"{C}Fetching folder structure from GDrive...{RESET}")
    folders = sorted([d for d in os.listdir(BASE_LOCAL_PATH) if os.path.isdir(os.path.join(BASE_LOCAL_PATH, d))])

    print(f"\n{C}--- TCG SECTOR SELECTOR ---{RESET}")
    print(f"{W}0) [SCAN ALL FOLDERS]{RESET}")
    for i, fld in enumerate(folders, 1):
        print(f"{G}{i}) {fld}{RESET}")

    choice = input(f"\n{Y}Select Sector (Number): {RESET}")
    if choice == "0": return folders
    try:
        return [folders[int(choice) - 1]]
    except:
        print(f"{R}Invalid Choice. Exiting.{RESET}")
        sys.exit(1)


def matrix_dynamic_audit():
    targets = get_dynamic_folders()

    # Pre-index existing data for O(1) speed
    print(f"{DG}Loading Database Matrices...{RESET}")
    conn = sqlite3.connect(SKIPPED_DB)
    cursor = conn.cursor()
    cursor.execute("SELECT image_name, game_name, language FROM progress")
    progress_set = set(cursor.fetchall())
    cursor.execute("SELECT image_name, game_name, language FROM skipped_images")
    skipped_set = set(cursor.fetchall())
    conn.close()

    total_count = 0
    buffer = []

    for tcg_folder in targets:
        current_path = os.path.join(BASE_LOCAL_PATH, tcg_folder)
        print(f"\n{C}>>> INITIATING STREAM: {G}{tcg_folder}{RESET}")

        for root, _, files in os.walk(current_path):
            for f in files:
                if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                    total_count += 1

                    name_only = os.path.splitext(f)[0]
                    lang = "english" if "_200w" in name_only else "japanese"
                    clean_id = name_only.replace("_200w", "") if lang == "english" else name_only

                    card_key = (clean_id, tcg_folder, lang)
                    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    prefix = f"{Y}[{ts}] {C}#{total_count:<7}{RESET}"

                    if card_key in progress_set:
                        print(f"{prefix}{G} [MATCH]   | {tcg_folder[:15]:<15} | {clean_id[:25]:<25}{RESET}")
                    elif card_key in skipped_set:
                        print(f"{prefix}{DG} [SKIPPED] | {tcg_folder[:15]:<15} | {clean_id[:25]:<25}{RESET}")
                    else:
                        print(f"{prefix}{W} [NEW]     | {tcg_folder[:15]:<15} | {clean_id[:25]:<25}{RESET}")

                        # Add to save buffer
                        buffer.append(
                            (card_key[0], card_key[1], card_key[2], "yes", datetime.now().strftime("%Y-%m-%d %H:%M")))
                        progress_set.add(card_key)

                        # Threshold Save (keeps the blur fast)
                        if len(buffer) >= SAVE_THRESHOLD:
                            conn_save = sqlite3.connect(SKIPPED_DB)
                            conn_save.cursor().executemany('INSERT OR REPLACE INTO progress VALUES (?, ?, ?, ?, ?)',
                                                           buffer)
                            conn_save.commit()
                            conn_save.close()
                            buffer = []

    # Final Save
    if buffer:
        conn_save = sqlite3.connect(SKIPPED_DB)
        conn_save.cursor().executemany('INSERT OR REPLACE INTO progress VALUES (?, ?, ?, ?, ?)', buffer)
        conn_save.commit()
        conn_save.close()

    print(f"\n{G}--- STREAM COMPLETE: {(total_count):,} ITEMS ACCOUNTED FOR ---{RESET}")


if __name__ == "__main__":
    matrix_dynamic_audit()