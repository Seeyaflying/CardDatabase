import sqlite3
import json
import logging
import os
import sys  # Still needed for sys.stdout, but used cleanly now
from datetime import datetime

# ------------------------------
# Config
# ------------------------------
DB_FILE = "skipped_images.sqlite"
TABLE_NAME = "skipped_images"
JSON_UPLOAD_FILE = 'skipped_images.json'

# Set up logging for output
LOG_FOLDER = "log"
# Generate a unique log file name
log_file_path = os.path.join(LOG_FOLDER, datetime.now().strftime('%Y-%m-%d_%H-%M-%S') + '_db_utility.log')

# Configure logging
logger = logging.getLogger("db_utility")
logger.setLevel(logging.INFO)
os.makedirs(LOG_FOLDER, exist_ok=True)

# File Handler (Encoding is often handled correctly for files, but setting it explicitly is safer)
file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
file_handler.setFormatter(logging.Formatter('%(message)s'))
logger.addHandler(file_handler)

# Stream Handler (for console output)
# Fix for UnicodeEncodeError: We create the handler with a stream that is guaranteed to be UTF-8.
# The simplest, most direct fix is to pass a wrapper stream or use the 'encoding' parameter
# if available in your logging implementation.
# Here we use an explicit stream creation trick or rely on the best available method.
try:
    # Python 3.9+ might handle StreamHandler(..., encoding='utf-8') directly,
    # but the following works more reliably across Python 3 versions for console output.
    import io

    # Create a wrapper around sys.stdout that forces UTF-8 encoding
    utf8_stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    stream_handler = logging.StreamHandler(utf8_stdout)
except Exception:
    # Fallback for complex environments: just use the default StreamHandler
    stream_handler = logging.StreamHandler(sys.stdout)

stream_handler.setFormatter(logging.Formatter('%(message)s'))
logger.addHandler(stream_handler)


# ------------------------------
# Database Helpers
# ------------------------------

def ensure_table(db_file=DB_FILE, table_name=TABLE_NAME):
    """Create the 'skipped_images' table if it doesn't exist."""
    conn = None
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                language TEXT NOT NULL,
                image_name TEXT NOT NULL,
                UNIQUE (language, image_name) 
            )
        """)
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Error ensuring table creation: {e}")
    finally:
        if conn:
            conn.close()


def upload_json_to_db(json_file_path, table_name=TABLE_NAME, db_file=DB_FILE):
    """
    Uploads data from a JSON file (list of {'image_name': X, 'language': Y} objects)
    to the specified table.
    """
    ensure_table(db_file, table_name)

    logger.info(f"\n--- Starting JSON Upload from: **{json_file_path}** ---")

    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            data_to_insert = json.load(f)
    except FileNotFoundError:
        logger.error(f"❌ JSON file not found: {json_file_path}. Please create it and try again.")
        return
    except json.JSONDecodeError as e:
        logger.error(f"❌ Error decoding JSON from file: {json_file_path}. Error: {e}")
        return

    if not isinstance(data_to_insert, list):
        logger.error("❌ JSON content must be a list of objects (an array).")
        return

    conn = None
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()

        insert_sql = f"INSERT OR IGNORE INTO {table_name} (language, image_name) VALUES (?, ?)"

        insert_data = []
        for item in data_to_insert:
            lang = item.get('language')
            img_name = item.get('image_name')

            if lang and img_name:
                insert_data.append((lang, img_name))
            else:
                logger.warning(f"⚠️ Skipping malformed entry (missing language or image_name): {item}")

        cursor.executemany(insert_sql, insert_data)
        rows_inserted = cursor.rowcount
        conn.commit()

        logger.info(f"✅ Successfully processed {len(insert_data)} records from JSON.")
        logger.info(f"🚀 **{rows_inserted}** new records were uploaded (duplicates ignored).")

    except sqlite3.Error as e:
        logger.error(f"❌ Database error during insertion: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()


def get_tables(db_file=DB_FILE):
    """Returns a list of all user tables in the database."""
    conn = None
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [t[0] for t in cursor.fetchall() if t[0] != 'sqlite_sequence']
        return tables
    except sqlite3.Error as e:
        logger.error(f"Error listing tables: {e}")
        return []
    finally:
        if conn:
            conn.close()


def get_database_schema(db_file=DB_FILE):
    """Lists all tables and prints their column structures."""
    tables = get_tables(db_file)
    if not tables:
        logger.info(f"❌ No user tables found in **{db_file}**.")
        return

    conn = None
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()

        print("\n--- 🔎 **Database Schema Inspection** ---")

        for table_name in tables:
            print(f"\n## 📋 Table: **{table_name}**")

            cursor.execute(f"PRAGMA table_info({table_name});")
            columns = cursor.fetchall()

            # Print formatted table header
            print(f"{'Column Name':<20} {'Data Type':<10} {'Nullable':<10} {'Primary Key':<5}")
            print("-" * 50)

            for column in columns:
                # Column structure: [0=cid, 1=name, 2=type, 3=notnull, 4=dflt_value, 5=pk]

                name = column[1]
                data_type = column[2]
                not_null = "NO" if column[3] else "YES"
                is_pk = "YES" if column[5] else ""

                print(f"{name:<20} {data_type:<10} {not_null:<10} {is_pk:<5}")

    except sqlite3.Error as e:
        logger.error(f"\n❌ A database error occurred during schema inspection: {e}")
    finally:
        if conn:
            conn.close()


def preview_table_data(db_file=DB_FILE, limit=5):
    """Allows user to select a table and prints the first N rows."""
    tables = get_tables(db_file)
    if not tables:
        logger.info(f"❌ No user tables found in **{db_file}**.")
        return

    print("\n--- 👁️ **Table Preview Menu** ---")

    # List tables for selection
    for i, name in enumerate(tables):
        print(f"[{i + 1}] {name}")

    choice = input(f"Enter the number of the table you want to preview (first {limit} rows): ")

    try:
        table_index = int(choice) - 1
        if 0 <= table_index < len(tables):
            table_name = tables[table_index]
        else:
            print("Invalid selection. Returning to main menu.")
            return
    except ValueError:
        print("Invalid input. Please enter a number.")
        return

    conn = None
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()

        # Fetch the column names first
        cursor.execute(f"PRAGMA table_info({table_name});")
        columns = [col[1] for col in cursor.fetchall()]

        # Fetch the data
        cursor.execute(f"SELECT * FROM {table_name} LIMIT {limit};")
        rows = cursor.fetchall()

        if not rows:
            print(f"\nTable **{table_name}** is empty.")
            return

        print(f"\n**First {len(rows)} rows of {table_name}:**")

        # Print column names
        header_line = [f"{col:<{max(len(col), 10)}}" for col in columns]
        print(" | ".join(header_line))
        print("-" * (sum(len(c) for c in header_line) + len(header_line) * 3))

        # Print rows
        for row in rows:
            row_output = [f"{str(item):<{max(len(col), 10)}}" for item, col in zip(row, columns)]
            print(" | ".join(row_output))

    except sqlite3.Error as e:
        logger.error(f"\n❌ A database error occurred during table preview: {e}")
    finally:
        if conn:
            conn.close()


# ------------------------------
# Main Execution Menu
# ------------------------------

def main_menu():
    """Displays the main menu and handles user choices."""
    while True:
        print("\n" + "=" * 50)
        print("       📝 **SQLite Database Utility Menu** 💻")
        print("=" * 50)
        print("[1] Upload JSON to skipped_images table")
        print("[2] Inspect Database Schema (List Tables and Columns)")
        print("[3] Preview Table Data (Show first 5 rows)")
        print("[4] Exit")
        print("-" * 50)

        choice = input("Enter your choice (1-4): ")

        if choice == '1':
            upload_json_to_db(JSON_UPLOAD_FILE)
        elif choice == '2':
            get_database_schema()
        elif choice == '3':
            preview_table_data()
        elif choice == '4':
            print("Exiting utility. Goodbye! 👋")
            break
        else:
            print("Invalid choice. Please enter a number between 1 and 4.")


if __name__ == '__main__':
    # Add a note about the external requirement for the best experience
    print(
        "NOTE: For best results with emojis, run this script using an external terminal (like Windows Terminal) set to UTF-8.")
    main_menu()