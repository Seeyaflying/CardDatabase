import os
import re
import sqlite3
import csv
import json
import time

# ------------------------------
# Paths
# ------------------------------
DB_PATH = "skipped_images.sqlite"  # database in same folder as script
JSON_PATH = "skipped_images.json"  # change as needed

# Ensure JSON exists
if not os.path.exists(JSON_PATH):
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        f.write("[]")
    print(f"JSON file created at {JSON_PATH}")

# ------------------------------
# Database Helpers
# ------------------------------
def connect_db(path=DB_PATH):
    conn = sqlite3.connect(path)
    ensure_tables(conn)
    return conn

def ensure_tables(conn):
    cursor = conn.cursor()
    # card_ai table
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
        cursor.execute("INSERT INTO card_ai (id, genome, total_steps, full_iteration) VALUES (1,1,0,0);")

    # skipped_images table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS skipped_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image_name TEXT UNIQUE,
            language TEXT
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
        cursor.execute(f"SELECT * FROM {table} ORDER BY id ASC LIMIT {n}")
        first = cursor.fetchall()
        cursor.execute(f"SELECT * FROM {table} ORDER BY id DESC LIMIT {n}")
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

def add_single_image(conn):
    name = input("Enter image name (without extension): ").strip()
    lang = input("Enter language (english/japanese): ").strip().lower()
    if lang == "english":
        name = name + "_200w.jpg"
    else:
        name = name + ".jpg"
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO skipped_images (image_name, language) VALUES (?, ?)", (name, lang))
    conn.commit()
    print(f"Added skipped image: {name} ({lang})")

def import_images_from_json(conn):
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            print("Invalid JSON format.")
            return
    cursor = conn.cursor()
    count = 0
    for entry in data:
        name = entry.get("image_name", "").strip()
        lang = entry.get("language", "").strip().lower()
        if not name or lang not in {"english","japanese"}:
            continue
        if lang == "english":
            name = name + "_200w.jpg"
        else:
            name = name + ".jpg"
        cursor.execute("INSERT OR IGNORE INTO skipped_images (image_name, language) VALUES (?, ?)", (name, lang))
        count += 1
    conn.commit()
    print(f"Imported {count} images from JSON into skipped_images table.")

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

def live_data_viewer(conn, refresh=3):
    table_name = input("Enter table name to watch live (default 'skipped_images'): ").strip() or "skipped_images"
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
        print("1. Import images from JSON")
        print("2. Add single skipped image")
        print("3. List tables")
        print("4. Show columns in a table")
        print("5. Show first 5 rows of a table")
        print("6. Delete a table")
        print("7. Delete a row from a table")
        print("8. Export table to CSV")
        print("9. Live data viewer")
        print("10. Show first and last 5 rows of each table")
        print("11. Exit")
        choice = input("Choose an option (1-11): ").strip()
        if choice=="1": import_images_from_json(conn)
        elif choice=="2": add_single_image(conn)
        elif choice=="3": list_tables(conn)
        elif choice=="4": show_columns(conn, input("Enter table name: ").strip())
        elif choice=="5": show_first_rows(conn, input("Enter table name (default 'skipped_images'): ").strip() or "skipped_images")
        elif choice=="6": drop_table(conn, input("Enter table name to delete: ").strip())
        elif choice=="7": delete_row(conn)
        elif choice=="8": export_table_to_csv(conn)
        elif choice=="9": live_data_viewer(conn)
        elif choice=="10": show_first_and_last_rows(conn)
        elif choice=="11": break
        else: print("Invalid choice.")
    conn.close()
    print("Goodbye!")

if __name__=="__main__":
    main()
