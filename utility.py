import os
import sqlite3
from datetime import datetime

# ==============================================================
# CONFIGURATION SECTION
# ==============================================================
SKIPPED_ROOT_DIR = r"G:/My Drive/Skipped Cards"
CARD_DATABASE_ROOT = r"G:/My Drive/Card Database"
DB_FILE = "skipped_images.sqlite"
# ==============================================================

class CardDBManager:
    def __init__(self, db_path=DB_FILE):
        self.db_path = db_path
        self._ensure_core_tables()

    def get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_core_tables(self):
        """Initializes tables using the unified schema."""
        with self.get_conn() as conn:
            # 1. BANNED LIST
            conn.execute("""CREATE TABLE IF NOT EXISTS skipped_images
                            (image_name TEXT, game_name TEXT, language TEXT, added_at TEXT,
                            PRIMARY KEY (image_name, game_name, language))""")

            # 2. PROGRESS TRACKER
            conn.execute("""CREATE TABLE IF NOT EXISTS progress
                            (image_name TEXT,game_name TEXT,language TEXT,status TEXT,processed_at TEXT,
                             PRIMARY KEY(image_name,game_name,language))""")

            # 3. HARVESTER CONFIG (Jap)
            conn.execute("""CREATE TABLE IF NOT EXISTS jap_tcgs
                            (tcg_name TEXT PRIMARY KEY, site_id INTEGER, total_pages INTEGER,
                            last_run TEXT, last_duration TEXT, lifetime_dl INTEGER DEFAULT 0)""")

            # 4. HARVESTER CONFIG (Eng)
            conn.execute("""CREATE TABLE IF NOT EXISTS eng_tcgs
                            (tcg_name TEXT PRIMARY KEY,site_id INTEGER,total_pages INTEGER,
                             last_run TEXT,last_duration TEXT,lifetime_dl INTEGER DEFAULT 0)""")
            conn.commit()

    def show_all_stats(self):
        print("\n" + "═" * 60)
        print("              DATABASE GLOBAL DASHBOARD")
        print("═" * 60)
        with self.get_conn() as conn:
            # Stats for Banned List
            print(f"\n 🚫 BANNED CARDS (skipped_images)")
            print(f" {'GAME NAME':<20} | {'LANG':<10} | {'COUNT'}")
            print("-" * 50)
            skips = conn.execute("SELECT game_name, language, COUNT(*) as c FROM skipped_images GROUP BY game_name, language").fetchall()
            skip_total = 0
            for r in (skips or []):
                print(f" {str(r['game_name']):<20} | {str(r['language']):<10} | {r['c']:>7,}")
                skip_total += r['c']
            if not skips: print("  [No banned cards indexed]")
            print(f" TOTAL BANNED: {skip_total:,}")

            # Stats for Progress
            print(f"\n 🟢 TOTAL REVIEWED (progress)")
            print(f" {'GAME NAME':<20} | {'LANG':<10} | {'COUNT'}")
            print("-" * 50)
            progs = conn.execute("SELECT game_name, language, COUNT(*) as c FROM progress GROUP BY game_name, language").fetchall()
            prog_total = 0
            for r in (progs or []):
                print(f" {str(r['game_name']):<20} | {str(r['language']):<10} | {r['c']:>7,}")
                prog_total += r['c']
            print(f" TOTAL PROGRESS: {prog_total:,}")
        print("\n" + "═" * 60)

    def run_folder_search_import(self):
        """Scans Skipped folders and adds them as 'rejected'."""
        print("\n" + "=" * 45)
        print("      TCG FOLDER SCANNER & IMPORT")
        print("=" * 45)

        if not os.path.exists(SKIPPED_ROOT_DIR):
            print(f"❌ Error: Root not found: {SKIPPED_ROOT_DIR}")
            return

        subfolders = [d for d in os.listdir(SKIPPED_ROOT_DIR) if os.path.isdir(os.path.join(SKIPPED_ROOT_DIR, d))]
        if not subfolders:
            print("🟡 No TCG folders found in Skipped directory.")
            return

        for i, folder in enumerate(subfolders, 1):
            print(f" {i}. {folder}")

        choice = input("\nSelect TCG # (or paste path): ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(subfolders):
            game_name = subfolders[int(choice) - 1]
            target_dir = os.path.join(SKIPPED_ROOT_DIR, game_name)
        else:
            target_dir = choice.replace('"', '')
            game_name = os.path.basename(target_dir)

        if not os.path.exists(target_dir):
            print("❌ Invalid Path.")
            return

        lang_choice = input(f"Language for {game_name} [1] Japanese [2] English: ")
        language = "english" if lang_choice == "2" else "japanese"

        exts = ('.png', '.jpg', '.jpeg', '.webp')
        files = [f for f in os.listdir(target_dir) if f.lower().endswith(exts)]
        if not files:
            print("🟡 Folder is empty.")
            return

        if input(f"\nImport {len(files)} cards as 'REJECTED'? (y/n): ").lower() == 'y':
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            with self.get_conn() as conn:
                for filename in files:
                    name_only = os.path.splitext(filename)[0]
                    image_id = name_only.replace("_200w", "") if "_200w" in name_only else name_only
                    conn.execute("INSERT OR IGNORE INTO skipped_images VALUES (?,?,?,?)", (image_id, game_name, language, timestamp))
                    conn.execute("INSERT OR IGNORE INTO progress VALUES (?,?,?,?,?)", (image_id, game_name, language, "rejected", timestamp))
                conn.commit()
            print("✨ Success! Tables updated.")

    def run_progress_audit(self):
        """Audits the Card Database folder and adds missing files to 'progress' as 'approved'."""
        print("\n" + "=" * 45)
        print("      DATABASE PROGRESS AUDIT")
        print("=" * 45)
        print(f"Scanning: {CARD_DATABASE_ROOT}")
        print("This will add missing cards to 'progress' without deleting anything.")

        if not os.path.exists(CARD_DATABASE_ROOT):
            print(f"❌ Error: Path not found: {CARD_DATABASE_ROOT}")
            return

        new_count = 0
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        exts = ('.png', '.jpg', '.jpeg', '.webp')

        with self.get_conn() as conn:
            for game_folder in os.listdir(CARD_DATABASE_ROOT):
                game_path = os.path.join(CARD_DATABASE_ROOT, game_folder)
                if os.path.isdir(game_path):
                    print(f"  -> Auditing: {game_folder}")
                    for filename in os.listdir(game_path):
                        if filename.lower().endswith(exts):
                            name_only = os.path.splitext(filename)[0]
                            lang = "english" if "_200w" in name_only else "japanese"
                            image_id = name_only.replace("_200w", "") if lang == "english" else name_only

                            cursor = conn.execute("INSERT OR IGNORE INTO progress VALUES (?,?,?,?,?)",
                                         (image_id, game_folder, lang, "approved", timestamp))
                            if cursor.rowcount > 0:
                                new_count += 1
            conn.commit()

        print(f"\n✅ Audit Complete! Added {new_count:,} new approved cards to progress.")

    def jap_update(self):
        print("\n" + "═" * 30 + "\n  JAPANESE TCG SETTINGS\n" + "═" * 30)
        with self.get_conn() as conn:
            rows = conn.execute("SELECT tcg_name, site_id, total_pages FROM jap_tcgs ORDER BY tcg_name").fetchall()
        for i, r in enumerate(rows, 1):
            print(f"{i}. {r['tcg_name']:<15} [ID: {r['site_id']}] [Pages: {r['total_pages']}]")

        choice = input("\nEdit # (n=new): ")
        if choice.lower() == 'n':
            n, s, p = input("Name: "), input("Site ID: "), input("Pages: ")
            with self.get_conn() as conn:
                conn.execute("INSERT INTO jap_tcgs (tcg_name, site_id, total_pages) VALUES (?,?,?)", (n, s, p))
        elif choice.isdigit() and int(choice) <= len(rows):
            t = rows[int(choice) - 1]
            ni = input(f"New ID [{t['site_id']}]: ") or t['site_id']
            np = input(f"New Pages [{t['total_pages']}]: ") or t['total_pages']
            with self.get_conn() as conn:
                conn.execute("UPDATE jap_tcgs SET site_id=?, total_pages=? WHERE tcg_name=?", (ni, np, t['tcg_name']))

def main():
    mgr = CardDBManager()
    while True:
        print("\n" + "═" * 45 + "\n  TCG DATABASE GLOBAL MANAGER\n" + "═" * 45)
        print(" 1. 📊 GLOBAL DASHBOARD (View All Tables)")
        print(" 2. 🔍 Search Banned List (By ID)")
        print(" 3. 📥 SCAN SKIPPED FOLDERS (Add to Banned)")
        print(" 4. ⚙️  Update Japanese Harvester Config")
        print(" 5. 🛠️  AUDIT PROGRESS (Add Missing Approved Cards)")
        print(" 6. ❌ Exit")

        cmd = input("\nSelect Option: ")
        if cmd == '1': mgr.show_all_stats()
        elif cmd == '2':
            term = input("\nSearch Image ID: ").strip()
            with mgr.get_conn() as conn:
                res = conn.execute("SELECT * FROM skipped_images WHERE image_name LIKE ?", (f"%{term}%",)).fetchall()
                if res:
                    for r in res: print(f" -> {r['image_name']} | {r['game_name']} | {r['language']}")
                else: print("Not found.")
        elif cmd == '3': mgr.run_folder_search_import()
        elif cmd == '4': mgr.jap_update()
        elif cmd == '5': mgr.run_progress_audit()
        elif cmd == '6': break

if __name__ == "__main__":
    main()