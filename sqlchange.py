import sqlite3
import re
import os

DB_PATH = "skipped_images.sqlite"
JSON_PATH = "tcg_database.jap_skipped_images.json"


def connect_db(path=DB_PATH):
    return sqlite3.connect(path)


def create_default_tables(conn):
    """Create default tables if they don't exist"""
    cursor = conn.cursor()
    cursor.execute("""
                   CREATE TABLE IF NOT EXISTS images
                   (
                       id
                       INTEGER
                       PRIMARY
                       KEY
                       AUTOINCREMENT,
                       image_name
                       TEXT
                       UNIQUE
                   );
                   """)
    cursor.execute("""
                   CREATE TABLE IF NOT EXISTS skipped_images
                   (
                       id
                       INTEGER
                       PRIMARY
                       KEY
                       AUTOINCREMENT,
                       image_name
                       TEXT
                       UNIQUE
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

    # Create table if it doesn't exist
    cursor = conn.cursor()
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image_name TEXT UNIQUE
        );
    """)
    conn.commit()

    # Read JSON and extract image names
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
    """Manually move an image to skipped_images table"""
    image_name = input("Enter image name to mark as skipped: ").strip()
    cursor = conn.cursor()
    # Insert into skipped_images
    cursor.execute("INSERT OR IGNORE INTO skipped_images (image_name) VALUES (?)", (image_name,))
    # Remove from images table if exists
    cursor.execute("DELETE FROM images WHERE image_name = ?", (image_name,))
    conn.commit()
    print(f"Image '{image_name}' marked as skipped.")


def add_manual_entry(conn):
    """Manually add an entry into any table"""
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

        col_names = [col[1] for col in columns if col[1] != "id"]  # skip autoincrement id
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
        print("8. Exit")
        choice = input("Choose an option (1-8): ").strip()

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
            break
        else:
            print("Invalid choice. Try again.")

    conn.close()
    print("Goodbye!")


if __name__ == "__main__":
    main()
