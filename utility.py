import os
import json
import csv
import sqlite3
import subprocess
from datetime import datetime
import audit_database

# ==============================================================
# CONFIGURATION SECTION
# ==============================================================
JSON_FILE_PATH = r"skipped_output.json"
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
            conn.execute(
                "CREATE TABLE IF NOT EXISTS progress (img_path TEXT PRIMARY KEY, processed_at TEXT, status TEXT, game_name TEXT)")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS global_skips (filename TEXT PRIMARY KEY, game_name TEXT, reason TEXT)")
            # Ensure the Japanese TCG table exists for the update utility
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
            conn.commit()

    def get_tables(self):
        with self.get_conn() as conn:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            return [row[0] for row in cursor.fetchall()]

    def get_columns(self, table):
        with self.get_conn() as conn:
            cursor = conn.execute(f"PRAGMA table_info({table})")
            return [row[1] for row in cursor.fetchall()]

    # ==============================================================
    # JAP_UPDATE UTILITY
    # ==============================================================
    def jap_update(self):
        """Utility to modify Site IDs and Page counts for Japanese TCGs."""
        print("\n" + "═" * 30)
        print("  JAPANESE TCG SETTINGS")
        print("═" * 30)

        with self.get_conn() as conn:
            rows = conn.execute("SELECT tcg_name, site_id, total_pages FROM jap_tcgs ORDER BY tcg_name").fetchall()

        if not rows:
            print("⚠️ No Japanese TCGs found in database.")
            name = input("Enter new TCG name to add (e.g., Nivel Arena): ")
            if not name: return
            sid = input("Enter Site ID: ")
            pgs = input("Enter Page Count: ")
            with self.get_conn() as conn:
                conn.execute("INSERT INTO jap_tcgs (tcg_name, site_id, total_pages) VALUES (?,?,?)", (name, sid, pgs))
            return

        for i, row in enumerate(rows, 1):
            print(f"{i}. {row['tcg_name']:<15} [ID: {row['site_id']}] [Pages: {row['total_pages']}]")

        choice = input("\nSelect TCG # to edit (or 'n' for new, 'Enter' to cancel): ")

        if choice.lower() == 'n':
            name = input("New TCG Name: ")
            sid = input("Site ID: ")
            pgs = input("Pages: ")
            with self.get_conn() as conn:
                conn.execute("INSERT INTO jap_tcgs (tcg_name, site_id, total_pages) VALUES (?,?,?)", (name, sid, pgs))
            print("✅ Added.")

        elif choice.isdigit() and int(choice) <= len(rows):
            target = rows[int(choice) - 1]
            print(f"\nEditing: {target['tcg_name']}")
            new_id = input(f"New Site ID [{target['site_id']}] (Enter to keep): ") or target['site_id']
            new_pgs = input(f"New Page Count [{target['total_pages']}] (Enter to keep): ") or target['total_pages']

            with self.get_conn() as conn:
                conn.execute("UPDATE jap_tcgs SET site_id = ?, total_pages = ? WHERE tcg_name = ?",
                             (new_id, new_pgs, target['tcg_name']))
            print("✅ Updated.")

    def import_scanner_json(self):
        target_path = JSON_FILE_PATH
        if not target_path:
            target_path = input("\nNo path found. Enter path to JSON file: ").strip().replace('"', '')

        if not os.path.exists(target_path):
            print(f"❌ File not found at: {target_path}");
            return

        print(f"\n>>> Loading data from: {target_path}")
        try:
            with open(target_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(f"❌ Read Error: {e}");
            return

        tables = self.get_tables()
        for i, t in enumerate(tables, 1): print(f"{i}. {t}")
        table = tables[int(input("\nSelect destination table: ")) - 1]
        cols = self.get_columns(table)

        mapping = {}
        print(f"\n[Target: {table}] Map JSON keys to columns:")
        for j_key in ["image_name", "language"]:
            for i, col_name in enumerate(cols, 1): print(f" {i}. {col_name}")
            idx = input(f"Select column for '{j_key}': ")
            if idx.isdigit(): mapping[j_key] = cols[int(idx) - 1]

        defaults = {}
        for col in cols:
            if col not in mapping.values():
                val = input(f"Default value for '{col}' (Enter to skip): ")
                if val: defaults[col] = val

        print("\n" + "!" * 15 + " PRE-IMPORT PREVIEW " + "!" * 15)
        for entry in data[:3]:
            row = {db_col: entry.get(j_key) for j_key, db_col in mapping.items()}
            row.update(defaults)
            for col in cols:
                if col not in row and any(x in col.lower() for x in ["date", "at", "timestamp"]):
                    row[col] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"Preview: {row}")

        if input("\nProceed with import? (y/n): ").lower() != 'y': return

        success, errors = 0, 0
        with self.get_conn() as conn:
            for entry in data:
                row_data = {db_col: entry.get(j_key) for j_key, db_col in mapping.items()}
                row_data.update(defaults)
                for col in cols:
                    if col not in row_data and any(x in col.lower() for x in ["date", "at", "timestamp"]):
                        row_data[col] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                keys = list(row_data.keys())
                sql = f"INSERT OR IGNORE INTO {table} ({', '.join(keys)}) VALUES ({', '.join(['?'] * len(keys))})"
                try:
                    conn.execute(sql, list(row_data.values()))
                    success += 1
                except:
                    errors += 1
            conn.commit()
        print(f"✅ Finished: {success} added, {errors} ignored.")

    def manual_add(self):
        tables = self.get_tables()
        for i, t in enumerate(tables, 1): print(f"{i}. {t}")
        table = tables[int(input("\nSelect table: ")) - 1]
        cols = self.get_columns(table)
        vals = []
        for c in cols:
            if any(x in c.lower() for x in ["date", "at", "timestamp"]):
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                vals.append(input(f"{c} [{now}]: ") or now)
            else:
                vals.append(input(f"{c}: "))
        with self.get_conn() as conn:
            conn.execute(f"INSERT INTO {table} VALUES ({','.join(['?'] * len(vals))})", vals)
            conn.commit()

    def modify_record(self):
        tables = self.get_tables()
        for i, t in enumerate(tables, 1): print(f"{i}. {t}")
        table = tables[int(input("\nTable: ")) - 1]
        cols = self.get_columns(table)
        for i, c in enumerate(cols, 1): print(f"{i}. {c}")
        col = cols[int(input("Search column index: ")) - 1]
        val = input("Value: ")
        act = input("[E]dit or [D]elete? ").upper()
        if act == 'D':
            with self.get_conn() as conn:
                conn.execute(f"DELETE FROM {table} WHERE {col} = ?", (val,))
        elif act == 'E':
            for i, c in enumerate(cols, 1): print(f"{i}. {c}")
            up_col = cols[int(input("Column to update: ")) - 1]
            new_v = input("New value: ")
            with self.get_conn() as conn:
                conn.execute(f"UPDATE {table} SET {up_col} = ? WHERE {col} = ?", (new_v, val))

    def backup(self, format="json"):
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        for t in self.get_tables():
            with self.get_conn() as conn:
                rows = [dict(r) for r in conn.execute(f"SELECT * FROM {t}").fetchall()]
            if not rows: continue

            path = os.path.join(BACKUP_FOLDER, f"{t}_{ts}.{format}")
            with open(path, 'w', encoding='utf-8') as f:
                if format == "json":
                    f.write("[\n")
                    for i, row in enumerate(rows):
                        comma = "," if i < len(rows) - 1 else ""
                        f.write(f"  {json.dumps(row)}{comma}\n")
                    f.write("]")
                else:
                    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)
            print(f"📦 Backup: {path}")


def make_skipped_images_json():
    """Triggers the external skipped_json_maker.py script."""
    script_name = "skipped_json_maker.py"
    if os.path.exists(script_name):
        print(f"\n--- Running {script_name} ---")
        subprocess.run(["python", script_name])
    else:
        print(f"❌ Error: {script_name} not found in the current directory.")


def main():
    mgr = CardDBManager()
    while True:
        print("\n" + "=" * 40 + "\n  DATABASE MANAGER\n" + "=" * 40)
        print("1. Statistics\n2. Search\n3. Manual Add\n4. Edit/Delete\n5. Backup")
        print("6. IMPORT FROM JSON PATH\n7. Make Skipped Images JSON\n8. Audit")
        print("9. UPDATE JAP TCG IDs (jap_update)\n10. Exit")

        cmd = input("\nSelect Option: ")
        if cmd == '1':
            for t in mgr.get_tables():
                count = mgr.get_conn().execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                print(f" -> [{t}]: {count} records")
        elif cmd == '2':
            term = input("Search term: ")
            for t in mgr.get_tables():
                cols = mgr.get_columns(t)
                where = " OR ".join([f"{c} LIKE ?" for c in cols])
                with mgr.get_conn() as conn:
                    res = conn.execute(f"SELECT * FROM {t} WHERE {where}", [f"%{term}%"] * len(cols)).fetchall()
                    if res:
                        print(f"\n[{t}]:")
                        for r in res: print(f"  {dict(r)}")
        elif cmd == '3':
            mgr.manual_add()
        elif cmd == '4':
            mgr.modify_record()
        elif cmd == '5':
            mgr.backup(input("json/csv: ").lower())
        elif cmd == '6':
            mgr.import_scanner_json()
        elif cmd == '7':
            make_skipped_images_json()
        elif cmd == '8':
            audit_database.run_audit_and_repair()
        elif cmd == '9':
            mgr.jap_update()
        elif cmd == '10':
            print("Exiting...")
            break



if __name__ == "__main__":
    main()