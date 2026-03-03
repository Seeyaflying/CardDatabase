import os
import time
import json
import csv
import sqlite3
import requests
import io
import sys
from datetime import datetime
from urllib.parse import urljoin
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

# ------------------------------
# 1. CONFIGURATION & PATHS
# ------------------------------
DB_FILE = "skipped_images.sqlite"
CHROMEDRIVER_PATH = './utils/chromedriver.exe'
BACKUP_FOLDER = "backups"
LOG_FOLDER = "log"

os.makedirs(BACKUP_FOLDER, exist_ok=True)
os.makedirs(LOG_FOLDER, exist_ok=True)


# ------------------------------
# 2. DATABASE MANAGER CLASS
# ------------------------------
class CardDBManager:
    def __init__(self, db_path=DB_FILE):
        self.db_path = db_path
        self._ensure_core_tables()

    def get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_core_tables(self):
        """Ensures fundamental tables exist without overwriting others."""
        with self.get_conn() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS progress (img_path TEXT PRIMARY KEY, processed_at TEXT, status TEXT, game_name TEXT)")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS global_skips (filename TEXT PRIMARY KEY, game_name TEXT, reason TEXT)")
            conn.commit()

    def get_tables(self):
        """Dynamically fetch all non-system tables."""
        with self.get_conn() as conn:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            return [row[0] for row in cursor.fetchall()]

    def get_columns(self, table):
        """Get column names for any table."""
        with self.get_conn() as conn:
            cursor = conn.execute(f"PRAGMA table_info({table})")
            return [row[1] for row in cursor.fetchall()]

    # --- Step-by-Step Manual Add ---
    def manual_add(self):
        tables = self.get_tables()
        for i, t in enumerate(tables, 1): print(f"{i}. {t}")
        table_idx = input("\nSelect table number: ")
        if not table_idx.isdigit(): return

        table = tables[int(table_idx) - 1]
        cols = self.get_columns(table)

        values = []
        print(f"\n[Adding to {table}] Enter values for each column:")
        for col in cols:
            # Auto-timestamp for date/time columns
            if any(x in col.lower() for x in ["date", "at", "timestamp"]):
                auto_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                val = input(f" -> {col} (Enter for '{auto_now}'): ") or auto_now
            else:
                val = input(f" -> {col}: ")
            values.append(val)

        try:
            with self.get_conn() as conn:
                conn.execute(f"INSERT INTO {table} VALUES ({','.join(['?'] * len(values))})", values)
                conn.commit()
            print("✅ Record successfully added.")
        except Exception as e:
            print(f"❌ SQL Error: {e}")

    # --- Step-by-Step Edit/Delete ---
    def modify_record(self):
        tables = self.get_tables()
        for i, t in enumerate(tables, 1): print(f"{i}. {t}")
        table = tables[int(input("\nSelect table: ")) - 1]
        cols = self.get_columns(table)

        print("\nWhich column should we use to find the record?")
        for i, c in enumerate(cols, 1): print(f"{i}. {c}")
        look_col = cols[int(input("Column index: ")) - 1]
        look_val = input(f"Enter the search value for {look_col}: ")

        action = input("\n[E]dit or [D]elete? ").upper()
        if action == 'D':
            with self.get_conn() as conn:
                conn.execute(f"DELETE FROM {table} WHERE {look_col} = ?", (look_val,))
            print("✅ Deleted.")
        elif action == 'E':
            for i, c in enumerate(cols, 1): print(f"{i}. {c}")
            up_col = cols[int(input("Column to update: ")) - 1]
            new_v = input(f"Enter new value for {up_col}: ")
            with self.get_conn() as conn:
                conn.execute(f"UPDATE {table} SET {up_col} = ? WHERE {look_col} = ?", (new_v, look_val))
            print("✅ Record updated.")

    # --- Robust Backup System ---
    def backup(self, format="json"):
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        for t in self.get_tables():
            with self.get_conn() as conn:
                rows = [dict(r) for r in conn.execute(f"SELECT * FROM {t}").fetchall()]
            if not rows: continue

            f_path = os.path.join(BACKUP_FOLDER, f"{t}_{ts}.{format}")
            try:
                if format == "json":
                    with open(f_path, 'w', encoding='utf-8') as f:
                        json.dump(rows, f, indent=4, ensure_ascii=False)
                else:
                    with open(f_path, 'w', newline='', encoding='utf-8') as f:
                        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                        writer.writeheader()
                        writer.writerows(rows)
                print(f"📦 Backup created: {f_path}")
            except Exception as e:
                print(f"❌ Backup failed for {t}: {e}")


# ------------------------------
# 3. SCRAPER HELPER
# ------------------------------
def setup_chrome():
    """Returns a pre-configured headless Chrome driver."""
    opts = Options()
    opts.add_argument("--headless")
    opts.add_argument("--disable-gpu")
    service = Service(executable_path=CHROMEDRIVER_PATH)
    return webdriver.Chrome(service=service, options=opts)


# ------------------------------
# 4. MAIN INTERFACE
# ------------------------------
def main():
    mgr = CardDBManager()

    while True:
        print("\n" + "=" * 40)
        print("  CARD DATABASE & SCRAPER UTILITY ")
        print("=" * 40)
        print("1. View Tables & Row Counts")
        print("2. Search All Tables (Universal)")
        print("3. Manual Add (Step-by-Step)")
        print("4. Edit/Delete Record")
        print("5. Export All Backups (JSON/CSV)")
        print("6. Exit")

        cmd = input("\nSelect Option: ")

        if cmd == '1':
            print("\nDatabase Statistics:")
            for t in mgr.get_tables():
                count = mgr.get_conn().execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                print(f" -> [{t}]: {count} records")

        elif cmd == '2':
            term = input("Search term (Filename, Path, ID): ")
            found = False
            for t in mgr.get_tables():
                cols = mgr.get_columns(t)
                where = " OR ".join([f"{c} LIKE ?" for c in cols])
                with mgr.get_conn() as conn:
                    res = conn.execute(f"SELECT * FROM {t} WHERE {where}", [f"%{term}%"] * len(cols)).fetchall()
                    if res:
                        found = True
                        print(f"\nMatches in [{t}]:")
                        for r in res: print(f"  {dict(r)}")
            if not found: print("No results found.")

        elif cmd == '3':
            mgr.manual_add()
        elif cmd == '4':
            mgr.modify_record()
        elif cmd == '5':
            fmt = input("Export format (json/csv): ").lower()
            if fmt in ['json', 'csv']:
                mgr.backup(fmt)
            else:
                print("Invalid format.")
        elif cmd == '6':
            break


if __name__ == "__main__":
    main()