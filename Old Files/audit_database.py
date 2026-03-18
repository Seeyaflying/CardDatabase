import os
import sqlite3
from datetime import datetime

# ==============================================================
# CONFIGURATION
# ==============================================================
DB_FILE = "../skipped_images.sqlite"
CARD_DATABASE_ROOT = r"G:/My Drive/Card Database"


# ==============================================================

def get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def audit_and_sync(conn):
    """Adds missing folder items to progress without deleting existing records."""
    print(f"\n🔍 Auditing folder: {CARD_DATABASE_ROOT}")
    print("✨ Only new/missing files will be added to progress.")

    count = 0
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    extensions = ('.png', '.jpg', '.jpeg', '.webp')

    if not os.path.exists(CARD_DATABASE_ROOT):
        print(f"⚠️ Error: Path not found: {CARD_DATABASE_ROOT}")
        return 0

    for game_folder in os.listdir(CARD_DATABASE_ROOT):
        game_path = os.path.join(CARD_DATABASE_ROOT, game_folder)
        if os.path.isdir(game_path):
            print(f"  -> Auditing: {game_folder}")
            game_new_count = 0
            for filename in os.listdir(game_path):
                if filename.lower().endswith(extensions):
                    name_only = os.path.splitext(filename)[0]

                    # Logic: _200w = English, else Japanese
                    if "_200w" in name_only:
                        image_id = name_only.replace("_200w", "")
                        lang = "english"
                    else:
                        image_id = name_only
                        lang = "japanese"

                    try:
                        # INSERT OR IGNORE ensures we don't overwrite or delete existing entries
                        cursor = conn.execute(
                            "INSERT OR IGNORE INTO progress (image_name, game_name, language, status, processed_at) VALUES (?,?,?,?,?)",
                            (image_id, game_folder, lang, "approved", timestamp)
                        )
                        if cursor.rowcount > 0:
                            game_new_count += 1
                            count += 1
                    except Exception as e:
                        print(f"Error checking {filename}: {e}")

            if game_new_count > 0:
                print(f"     ✅ Found {game_new_count} new cards.")

    conn.commit()
    return count


def show_summary(conn, new_total):
    print("\n" + "═" * 55)
    print("              AUDIT SUMMARY")
    print("═" * 55)

    with conn:
        total_p = conn.execute("SELECT COUNT(*) FROM progress").fetchone()[0]
        total_s = conn.execute("SELECT COUNT(*) FROM skipped_images").fetchone()[0]

        print(f" New records added today:  {new_total:,}")
        print(f" Total in Progress table:  {total_p:,}")
        print(f" Total in Banned list:    {total_s:,}")
    print("═" * 55)


def main():
    print("=" * 50)
    print("      DATABASE PROGRESS AUDIT")
    print("=" * 50)
    print("This will only add NEW files from your Drive to the DB.")
    print("Existing records will NOT be touched or deleted.")

    confirm = input(f"\nProceed with Audit? (y/n): ")
    if confirm.lower() != 'y':
        print("Aborted.")
        return

    conn = get_conn()
    newly_indexed = audit_and_sync(conn)
    show_summary(conn, newly_indexed)

    conn.close()
    input("\nAudit complete. Press Enter to exit...")


if __name__ == "__main__":
    main()