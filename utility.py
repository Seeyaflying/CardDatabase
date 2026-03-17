import os
import json
import csv
import sqlite3
from datetime import datetime

# ==============================================================
# CONFIGURATION SECTION
# ==============================================================
DEFAULT_SCAN_ROOT = r"G:/My Drive/Skipped Cards"
OUTPUT_FILE = "skipped_output.json"
DB_FILE = "skipped_images.sqlite"
BACKUP_FOLDER = "backups"
# ==============================================================

os.makedirs(BACKUP_FOLDER, exist_ok=True)


class CardDBManager:
    def __init__(self, db_path=DB_FILE):
        self.db_path = db_path
        self._ensure_core_tables()

    def get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_core_tables(self):
        with self.get_conn() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS skipped_images
            (
                image_name
                TEXT,
                game_name
                TEXT,
                language
                TEXT,
                added_at
                TEXT,
                PRIMARY
                KEY
                            (
                image_name,
                game_name,
                language
                            ))""")

            conn.execute("""CREATE TABLE IF NOT EXISTS jap_tcgs
                            (
                                tcg_name
                                TEXT
                                PRIMARY
                                KEY,
                                site_id
                                INTEGER,
                                total_pages
                                INTEGER,
                                last_run
                                TEXT,
                                last_duration
                                TEXT,
                                lifetime_dl
                                INTEGER
                                DEFAULT
                                0
                            )""")

            conn.execute("""CREATE TABLE IF NOT EXISTS progress
                            (
                                img_path
                                TEXT
                                PRIMARY
                                KEY,
                                processed_at
                                TEXT,
                                status
                                TEXT,
                                game_name
                                TEXT
                            )""")
            conn.commit()

    # ==============================================================
    # OPTION 1: MULTI-TABLE DASHBOARD
    # ==============================================================
    def show_all_stats(self):
        print("\n" + "═" * 55)
        print("              DATABASE GLOBAL DASHBOARD")
        print("═" * 55)

        with self.get_conn() as conn:
            # --- 1. SKIPPED IMAGES (THE BANNED LIST) ---
            print(f"\n {os.path.basename(self.db_path)} > [skipped_images]")
            print(f" {'GAME NAME':<20} | {'LANG':<10} | {'BANNED'}")
            print("-" * 45)
            skips = conn.execute(
                "SELECT game_name, language, COUNT(*) as c FROM skipped_images GROUP BY game_name, language").fetchall()
            skip_total = 0
            for r in skips:
                g = str(r['game_name']) if r['game_name'] else "Unknown"
                l = str(r['language']) if r['language'] else "Unknown"
                print(f" {g:<20} | {l:<10} | {r['c']:>6,}")
                skip_total += r['c']
            print(f" TOTAL BANNED CARDS: {skip_total:,}")

            # --- 2. PROGRESS (WEB UI HISTORY) ---
            print(f"\n {os.path.basename(self.db_path)} > [progress]")
            prog_count = conn.execute("SELECT COUNT(*) FROM progress").fetchone()[0]
            print(f" Total Web UI Decisions Logged: {prog_count:,} records")

            # --- 3. JAP_TCGS (HARVESTER CONFIG) ---
            print(f"\n {os.path.basename(self.db_path)} > [jap_tcgs]")
            print(f" {'TCG NAME':<20} | {'S-ID':<6} | {'PAGES':<5} | {'LIFETIME'}")
            print("-" * 45)
            tcgs = conn.execute("SELECT tcg_name, site_id, total_pages, lifetime_dl FROM jap_tcgs").fetchall()
            for t in tcgs:
                print(f" {t['tcg_name']:<20} | {t['site_id']:<6} | {t['total_pages']:<5} | {t['lifetime_dl']:,}")

        print("\n" + "═" * 55)

    def run_manual_scan_and_import(self):
        print("\n" + "=" * 45)
        print("      SPECIFIC TCG IMPORT UTILITY")
        print("=" * 45)
        target_dir = input(f"Path to scan [Default: {DEFAULT_SCAN_ROOT}]: ").strip().replace('"',
                                                                                             '') or DEFAULT_SCAN_ROOT
        if not os.path.exists(target_dir): return

        game_name = input("Enter Game Name (e.g., Pokemon): ").strip()
        lang_choice = input("Select Language [1] Japanese [2] English: ")
        language = "english" if lang_choice == "2" else "japanese"

        skipped_data = []
        exts = ('.png', '.jpg', '.jpeg', '.webp')
        files = [f for f in os.listdir(target_dir) if f.lower().endswith(exts)]

        for filename in files:
            name_only = os.path.splitext(filename)[0]
            image_id = name_only.replace("_200w", "") if "_200w" in name_only else name_only
            skipped_data.append({"image_name": image_id, "game_name": game_name, "language": language})

        if not skipped_data: return

        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            f.write("[\n")
            for i, entry in enumerate(skipped_data):
                f.write(f"  {json.dumps(entry)}{',' if i < len(skipped_data) - 1 else ''}\n")
            f.write("]")

        if input(f"\nImport {len(skipped_data)} records to DB? (y/n): ").lower() == 'y':
            with self.get_conn() as conn:
                for e in skipped_data:
                    conn.execute("INSERT OR IGNORE INTO skipped_images VALUES (?,?,?,?)",
                                 (e['image_name'], e['game_name'], e['language'],
                                  datetime.now().strftime("%Y-%m-%d %H:%M")))
                conn.commit()
            print("✨ Import Complete.")

    def jap_update(self):
        print("\n" + "═" * 30 + "\n  JAPANESE TCG SETTINGS\n" + "═" * 30)
        with self.get_conn() as conn:
            rows = conn.execute("SELECT tcg_name, site_id, total_pages FROM jap_tcgs ORDER BY tcg_name").fetchall()
        for i, r in enumerate(rows, 1):
            print(f"{i}. {r['tcg_name']:<15} [ID: {r['site_id']}] [Pages: {r['total_pages']}]")

        choice = input("\nSelect TCG # to edit (n=new, Enter=cancel): ")
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
        print(" 2. 🔍 Search Banned List (Check for Image ID)")
        print(" 3. 📥 Manual Scan & Import (Add Banned Cards)")
        print(" 4. ⚙️  Update Japanese Harvester Config")
        print(" 5. ❌ Exit")

        cmd = input("\nSelect Option: ")
        if cmd == '1':
            mgr.show_all_stats()
        elif cmd == '2':
            term = input("\nSearch Image ID: ").strip()
            with mgr.get_conn() as conn:
                res = conn.execute("SELECT * FROM skipped_images WHERE image_name LIKE ?", (f"%{term}%",)).fetchall()
                if res:
                    for r in res: print(f" -> {r['image_name']} | {r['game_name']} | {r['language']}")
                else:
                    print("Not found.")
        elif cmd == '3':
            mgr.run_manual_scan_and_import()
        elif cmd == '4':
            mgr.jap_update()
        elif cmd == '5':
            break


if __name__ == "__main__":
    main()