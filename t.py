import os
import sqlite3
from datetime import datetime

# ==============================================================
# CONFIGURATION
# ==============================================================
DB_FILE = "skipped_images.sqlite"
CARD_DATABASE_ROOT = r"G:/My Drive/Card Database"
# ==============================================================

def get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def rebuild_progress_table(conn):
    print("\n" + "═"*50)
    print("🧹 Wiping old progress table...")
    conn.execute("DROP TABLE IF EXISTS progress")
    conn.execute("""CREATE TABLE progress(
                    image_name TEXT, 
                    game_name TEXT, 
                    language TEXT,
                    status TEXT,
                    processed_at TEXT,
                    PRIMARY KEY (image_name, game_name, language))""")
    conn.commit()

def sync_approved_cards(conn):
    print(f"🔍 Scanning: {CARD_DATABASE_ROOT}")
    count = 0
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    extensions = ('.png', '.jpg', '.jpeg', '.webp')

    if not os.path.exists(CARD_DATABASE_ROOT):
        print(f"⚠️ Error: Path not found: {CARD_DATABASE_ROOT}")
        return 0

    for game_folder in os.listdir(CARD_DATABASE_ROOT):
        game_path = os.path.join(CARD_DATABASE_ROOT, game_folder)
        if os.path.isdir(game_path):
            print(f"  -> Indexing: {game_folder}")
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
                        conn.execute("INSERT OR IGNORE INTO progress VALUES (?,?,?,?,?)",
                                     (image_id, game_folder, lang, "approved", timestamp))
                        count += 1
                    except Exception as e:
                        print(f"Error indexing {filename}: {e}")
    conn.commit()
    return count

def verify_data(conn):
    print("\n" + "═"*50)
    print("📋 DATA VERIFICATION (First 5 Records)")
    print("═"*50)
    print(f"{'IMAGE ID':<15} | {'GAME':<12} | {'LANG':<10} | {'STATUS'}")
    print("-" * 55)

    rows = conn.execute("SELECT * FROM progress LIMIT 5").fetchall()
    for r in rows:
        print(f"{r['image_name']:<15} | {r['game_name']:<12} | {r['language']:<10} | {r['status']}")
    print("-" * 55)

def main():
    print("=" * 50)
    print("      PROGRESS TABLE SANITIZER")
    print("=" * 50)

    if input(f"\nRebuild 'progress' table from folders? (y/n): ").lower() != 'y':
        return

    conn = get_conn()
    rebuild_progress_table(conn)
    total = sync_approved_cards(conn)

    # Run the verification printout
    verify_data(conn)

    print(f"\n✅ DONE! Total Cards Indexed: {total:,}")
    print("=" * 50)
    conn.close()

if __name__ == "__main__":
    main()