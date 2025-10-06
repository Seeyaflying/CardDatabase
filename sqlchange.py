import os
import re
import sqlite3
import csv
import time

# ------------------------------
# Paths
# ------------------------------
BASE_DIR = r"G:\My Drive\models\CardData"
DB_PATH = os.path.join(BASE_DIR, "skipped_images.sqlite")
JSON_PATH = os.path.join(BASE_DIR, "tcg_database.jap_skipped_images.json")

# ------------------------------
# Database Helpers
# ------------------------------
def connect_db(path=DB_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    ensure_tables(conn)
    return conn

def ensure_tables(conn):
    cursor = conn.cursor()
    # Persistent card_ai table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS card_ai (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            genome INTEGER NOT NULL,
            total_steps INTEGER NOT NULL,
            full_iteration INTEGER NOT NULL
        );
    """)
    cursor.execute("SELECT COUNT(*) FROM card_ai WHERE id = 1;")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO card_ai (id, genome, total_steps, full_iteration) VALUES (1, 1, 0, 0);")
    # Image tables
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image_name TEXT UNIQUE
        );
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS skipped_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image_name TEXT UNIQUE
        );
    """)
    conn.commit()

# ------------------------------
# DB Operations
# ------------------------------
def list_tables(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    if not tables:
        print("No tables found.")
    else:
        print("Tables in database:")
        for t in tables: print(f"  - {t[0]}")

def show_columns(conn, table_name):
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name});")
    cols = cursor.fetchall()
    if not cols:
        print(f"No table named '{table_name}' found.")
        return
    print(f"Columns in '{table_name}':")
    for col in cols:
        print(f"  {col[1]} ({col[2]})")

def show_first_rows(conn, table_name, n=5):
    cursor = conn.cursor()
    try:
        cursor.execute(f"PRAGMA table_info({table_name});")
        cols = [c[1] for c in cursor.fetchall()]
        cursor.execute(f"SELECT * FROM {table_name} LIMIT {n};")
        rows = cursor.fetchall()
        if not rows:
            print(f"No data in '{table_name}'.")
            return
        print(f"First {n} rows of '{table_name}':")
        for r in rows:
            print(dict(zip(cols,r)))
    except sqlite3.Error as e:
        print(f"Error: {e}")

def show_first_and_last_rows(conn, n=5):
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [t[0] for t in cursor.fetchall()]
    if not tables:
        print("No tables found.")
        return
    for table in tables:
        print(f"\n=== TABLE: {table} ===")
        cursor.execute(f"PRAGMA table_info({table});")
        cols = [c[1] for c in cursor.fetchall()]
        try:
            cursor.execute(f"SELECT * FROM {table} ORDER BY id ASC LIMIT {n}")
        except sqlite3.Error:
            cursor.execute(f"SELECT * FROM {table} LIMIT {n}")
        first = cursor.fetchall()
        try:
            cursor.execute(f"SELECT * FROM {table} ORDER BY id DESC LIMIT {n}")
        except sqlite3.Error:
            cursor.execute(f"SELECT * FROM {table} LIMIT {n}")
        last = cursor.fetchall()
        print("-- First rows --")
        for r in first: print(dict(zip(cols,r)))
        print("-- Last rows --")
        for r in reversed(last): print(dict(zip(cols,r)))

def drop_table(conn, table_name):
    cursor = conn.cursor()
    cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
    conn.commit()
    print(f"Table '{table_name}' deleted.")

def delete_row(conn):
    table_name = input("Enter table name to delete a row from: ").strip()
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name});")
    cols = [c[1] for c in cursor.fetchall()]
    if not cols:
        print(f"No table named '{table_name}' found.")
        return
    row_id = input("Enter ID of row to delete: ").strip()
    cursor.execute(f"DELETE FROM {table_name} WHERE id = ?", (row_id,))
    conn.commit()
    print(f"Row {row_id} deleted from '{table_name}'.")

def add_skipped_image(conn):
    name = input("Enter image name to mark as skipped: ").strip()
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO skipped_images (image_name) VALUES (?)", (name,))
    cursor.execute("DELETE FROM images WHERE image_name = ?", (name,))
    conn.commit()
    print(f"Image '{name}' marked as skipped.")

def add_manual_entry(conn):
    table_name = input("Enter table name to insert into: ").strip()
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name});")
    cols = [c[1] for c in cursor.fetchall() if c[1]!="id"]
    if not cols:
        print(f"No table named '{table_name}' found.")
        return
    values = [input(f"{c}: ").strip() for c in cols]
    placeholders = ",".join("?"*len(values))
    cursor.execute(f"INSERT OR IGNORE INTO {table_name} ({','.join(cols)}) VALUES ({placeholders})", values)
    conn.commit()
    print(f"Entry added to '{table_name}'.")

def export_table_to_csv(conn):
    table_name = input("Enter table name to export: ").strip()
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM {table_name}")
    rows = cursor.fetchall()
    cursor.execute(f"PRAGMA table_info({table_name});")
    cols = [c[1] for c in cursor.fetchall()]
    if not rows:
        print(f"No data in '{table_name}' to export.")
        return
    with open(f"{table_name}.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(cols)
        writer.writerows(rows)
    print(f"Table '{table_name}' exported to '{table_name}.csv'.")

def import_images_to_table(conn):
    if not os.path.exists(JSON_PATH):
        print(f"JSON file not found: {JSON_PATH}")
        return
    table_name = input("Enter table to import images into: ").strip()
    cursor = conn.cursor()
    cursor.execute(f"CREATE TABLE IF NOT EXISTS {table_name} (id INTEGER PRIMARY KEY AUTOINCREMENT, image_name TEXT UNIQUE);")
    conn.commit()
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    names = re.findall(r'"image_name"\s*:\s*"([^"]+)"', content)
    for name in names:
        cursor.execute(f"INSERT OR IGNORE INTO {table_name} (image_name) VALUES (?)", (name,))
    conn.commit()
    print(f"Imported {len(names)} image names into '{table_name}' table.")

def live_data_viewer(conn, refresh=3):
    table_name = input("Enter table name to watch live (default 'card_ai'): ").strip() or "card_ai"
    cursor = conn.cursor()
    print(f"Watching table '{table_name}' (Ctrl+C to stop)...")
    last_rows = None
    try:
        while True:
            cursor.execute(f"SELECT * FROM {table_name}")
            rows = cursor.fetchall()
            cursor.execute(f"PRAGMA table_info({table_name});")
            cols = [c[1] for c in cursor.fetchall()]
            if rows != last_rows:
                os.system("cls" if os.name=="nt" else "clear")
                print(f"--- {table_name} ---")
                for r in rows[-10:]:
                    print(dict(zip(cols,r)))
                last_rows = rows
            time.sleep(refresh)
    except KeyboardInterrupt:
        print("Stopped live viewing.")

# ------------------------------
# Main Menu
# ------------------------------
def main():
    conn = connect_db()
    while True:
        print("\n===== SQLite Manager Menu =====")
        print("1. Import image names from JSON")
        print("2. List tables")
        print("3. Show columns in a table")
        print("4. Show first 5 rows of a table")
        print("5. Delete a table")
        print("6. Delete a row from a table")
        print("7. Mark an image as skipped")
        print("8. Add manual entry to a table")
        print("9. Export table to CSV")
        print("10. Live data viewer")
        print("11. Show first 5 and last 5 rows of each table")
        print("12. Exit")
        choice = input("Choose an option (1-12): ").strip()

        if choice == "1": import_images_to_table(conn)
        elif choice == "2": list_tables(conn)
        elif choice == "3": show_columns(conn, input("Enter table name: ").strip())
        elif choice == "4": show_first_rows(conn, input("Enter table name (default 'card_ai'): ").strip() or "card_ai")
        elif choice == "5": drop_table(conn, input("Enter table name to delete: ").strip())
        elif choice == "6": delete_row(conn)
        elif choice == "7": add_skipped_image(conn)
        elif choice == "8": add_manual_entry(conn)
        elif choice == "9": export_table_to_csv(conn)
        elif choice == "10": live_data_viewer(conn)
        elif choice == "11": show_first_and_last_rows(conn)
        elif choice == "12": break
        else: print("Invalid choice.")

    conn.close()
    print("Goodbye!")

if __name__=="__main__":
    main()
