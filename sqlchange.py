import sqlite3
import re
import os
import csv
import time

DB_PATH = "skipped_images.sqlite"
JSON_PATH = "tcg_database.jap_skipped_images.json"
5
# Global debug flag
DEBUG_MODE = False


def connect_db(path=DB_PATH):
    abs_path = os.path.abspath(path)
    print(f"[DB] Connecting to database at: {abs_path}")
    conn = sqlite3.connect(path)
    print("[DB] Connection successful.")
    return conn


def enable_debug(conn, enable=True):
    """Turn SQL trace printing on or off."""
    global DEBUG_MODE
    DEBUG_MODE = enable
    if enable:
        conn.set_trace_callback(lambda stmt: print(f"[SQL TRACE] {stmt}"))
        print("✅ Live Debug View ENABLED — all SQL statements will be shown.")
    else:
        conn.set_trace_callback(None)
        print("🛑 Live Debug View DISABLED.")


def create_default_tables(conn):
    cursor = conn.cursor()
    cursor.execute("""
                   CREATE TABLE IF NOT EXISTS images
                   (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       image_name TEXT UNIQUE
                   );
                   """)
    cursor.execute("""
                   CREATE TABLE IF NOT EXISTS skipped_images
                   (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       image_name TEXT UNIQUE
                   );
                   """)
    conn.commit()


def import_images_to_table(conn):
    if not os.path.exists(JSON_PATH):
        print(f"JSON file not found: {JSON_PATH}")
        return

    table_name = input("Enter the table to import images into (it will be created if it doesn't exist): ").strip()
    if not table_name:
        print("Invalid table name.")
        return

    cursor = conn.cursor()
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image_name TEXT UNIQUE
        );
    """)
    conn.commit()

    with open(JSON_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    pattern = re.compile(r'"image_name"\s*:\s*"([^"]+)"')
    image_names = pattern.findall(content)
    print(f"Found {len(image_names)} image names.")

    for name in image_names:
        cursor.execute(f"INSERT OR IGNORE INTO {table_name} (image_name) VALUES (?)", (name,))
    conn.commit()
    print(f"Finished importing image names into '{table_name}' table!")


def list_tables(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    if not tables:
        print("No tables found.")
    else:
        print("Tables in database:")
        for table in tables:
            print(f" - {table[0]}")


def show_columns(conn, table_name):
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name});")
    columns = cursor.fetchall()
    if not columns:
        print(f"No table named '{table_name}' found.")
    else:
        print(f"Columns in '{table_name}':")
        for col in columns:
            print(f" - {col[1]} ({col[2]})")


def show_first_rows(conn, table_name, n=5):
    cursor = conn.cursor()
    try:
        cursor.execute(f"SELECT * FROM {table_name} LIMIT {n};")
        rows = cursor.fetchall()
        cursor.execute(f"PRAGMA table_info({table_name});")
        columns = [col[1] for col in cursor.fetchall()]
        if not rows:
            print(f"No data found in table '{table_name}'.")
        else:
            print(f"First {n} rows of '{table_name}':")
            for row in rows:
                row_dict = dict(zip(columns, row))
                print(row_dict)
    except sqlite3.Error as e:
        print(f"Error: {e}")


def drop_table(conn, table_name):
    cursor = conn.cursor()
    cursor.execute(f"DROP TABLE IF EXISTS {table_name};")
    conn.commit()
    print(f"Table '{table_name}' deleted (if it existed).")


def add_skipped_image(conn):
    image_name = input("Enter image name to mark as skipped: ").strip()
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO skipped_images (image_name) VALUES (?)", (image_name,))
    cursor.execute("DELETE FROM images WHERE image_name = ?", (image_name,))
    conn.commit()
    print(f"Image '{image_name}' marked as skipped.")


def add_manual_entry(conn):
    table_name = input("Enter table name to insert into: ").strip()
    if not table_name:
        print("Invalid table name.")
        return

    cursor = conn.cursor()
    try:
        cursor.execute(f"PRAGMA table_info({table_name});")
        columns = cursor.fetchall()
        if not columns:
            print(f"No table named '{table_name}' found.")
            return

        col_names = [col[1] for col in columns if col[1] != "id"]
        values = []
        for col in col_names:
            val = input(f"Enter value for '{col}': ").strip()
            values.append(val)

        placeholders = ",".join("?" for _ in values)
        cursor.execute(f"INSERT OR IGNORE INTO {table_name} ({','.join(col_names)}) VALUES ({placeholders})", values)
        conn.commit()
        print(f"Entry added to '{table_name}'.")
    except sqlite3.Error as e:
        print(f"Error: {e}")


def export_table_to_csv(conn):
    table_name = input("Enter table name to export: ").strip()
    if not table_name:
        print("Invalid table name.")
        return

    cursor = conn.cursor()
    try:
        cursor.execute(f"SELECT * FROM {table_name};")
        rows = cursor.fetchall()
        cursor.execute(f"PRAGMA table_info({table_name});")
        columns = [col[1] for col in cursor.fetchall()]

        if not rows:
            print(f"No data found in table '{table_name}'. Nothing to export.")
            return

        csv_filename = f"{table_name}.csv"
        with open(csv_filename, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(columns)
            writer.writerows(rows)

        print(f"✅ Table '{table_name}' exported to '{csv_filename}' successfully!")
    except sqlite3.Error as e:
        print(f"Error exporting table: {e}")

def live_data_viewer(conn, refresh_interval=3):
    """Continuously display data from a chosen table in real time"""
    cursor = conn.cursor()
    table_name = input("Enter the table name to watch live: ").strip()
    if not table_name:
        print("Invalid table name.")
        return

    try:
        cursor.execute(f"SELECT * FROM {table_name} LIMIT 1;")
    except sqlite3.Error as e:
        print(f"Error: {e}")
        return

    print(f"\nWatching table '{table_name}' for changes. Press Ctrl+C to stop.\n")

    last_rows = None
    try:
        while True:
            cursor.execute(f"SELECT * FROM {table_name};")
            rows = cursor.fetchall()
            cursor.execute(f"PRAGMA table_info({table_name});")
            columns = [col[1] for col in cursor.fetchall()]

            if rows != last_rows:  # Only print when new data appears
                os.system('cls' if os.name == 'nt' else 'clear')
                print(f"--- Live View: {table_name} ---")
                for row in rows[-10:]:  # Show only last 10 rows
                    print(dict(zip(columns, row)))
                print(f"\nRefreshing every {refresh_interval} seconds...")

                last_rows = rows

            time.sleep(refresh_interval)
    except KeyboardInterrupt:
        print("\nStopped live viewing.")

def main():
    conn = connect_db()
    create_default_tables(conn)

    while True:
        print("\n--- SQLite Manager ---")
        print("1. Import image names from JSON")
        print("2. List tables")
        print("3. Show columns in a table")
        print("4. Show row info of a table")
        print("5. Delete a table")
        print("6. Mark an image as skipped")
        print("7. Add manual entry to a table")
        print("8. Export table to CSV")
        print("9. Live data viewer (watch tables in real time)")
        print("10. Exit")

        choice = input("Choose an option (1-10): ").strip()

        if choice == "1":
            import_images_to_table(conn)
        elif choice == "2":
            list_tables(conn)
        elif choice == "3":
            table_name = input("Enter table name: ").strip()
            show_columns(conn, table_name)
        elif choice == "4":
            table_name = input("Enter table name: ").strip()
            show_first_rows(conn, table_name)
        elif choice == "5":
            table_name = input("Enter table name to delete: ").strip()
            drop_table(conn, table_name)
        elif choice == "6":
            add_skipped_image(conn)
        elif choice == "7":
            add_manual_entry(conn)
        elif choice == "8":
            export_table_to_csv(conn)
        elif choice == "9":
            live_data_viewer(conn)
        elif choice == "10":
            break
        else:
            print("Invalid choice. Try again.")

    conn.close()
    print("Goodbye!")



if __name__ == "__main__":
    main()
