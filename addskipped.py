import csv
import logging
import sqlite3
from datetime import date
import os

# Create a logger
today = date.today()
log_folder = 'log'
log_filename = f"{log_folder}/{today.strftime('%Y-%m-%d')}_csv_importer.log"

if not os.path.exists(log_folder):
    os.makedirs(log_folder)

logger = logging.getLogger('csv_importer')
logger.setLevel(logging.INFO)
handler = logging.FileHandler(log_filename)
handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(handler)

DB_FILE = "skipped_images.sqlite"


def init_db():
    """Initialize SQLite database and create tables if not exist."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS skipped_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image_name TEXT UNIQUE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jap_skipped_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image_name TEXT UNIQUE
        )
    """)

    conn.commit()
    conn.close()


def read_skipped_csv(csv_filepath):
    """Reads a CSV file of skipped image numbers and returns a list of filenames with '.jpg' appended."""
    try:
        with open(csv_filepath, mode='r', encoding='utf-8') as file:
            reader = csv.reader(file)
            skipped_images = []
            for row in reader:
                if row and len(row) > 0:
                    number = row[0].strip()
                    skipped_images.append(number + ".jpg")
            return skipped_images
    except Exception as e:
        logger.error(f"Error reading skipped images file: {e}")
        return []


def import_to_sqlite(skipped_image_ids, table_name):
    """Imports skipped image IDs into SQLite database."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    added_count = 0

    for image_id in skipped_image_ids:
        try:
            cursor.execute(f"INSERT OR IGNORE INTO {table_name} (image_name) VALUES (?)", (image_id,))
            if cursor.rowcount > 0:
                print(f"Added {image_id} to {table_name}")
                logger.info(f"Inserted skipped image ID: {image_id}")
                added_count += 1
        except Exception as e:
            logger.error(f"Error inserting {image_id}: {e}")

    conn.commit()
    conn.close()
    print(f"Added {added_count} skipped image IDs to {table_name}")


def delete_from_sqlite(image_id, table_name):
    """Deletes a skipped image ID from SQLite database."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute(f"DELETE FROM {table_name} WHERE image_name = ?", (image_id,))
    conn.commit()
    deleted = cursor.rowcount
    conn.close()

    if deleted > 0:
        print(f"Deleted {image_id} from {table_name}")
        logger.info(f"Deleted skipped image ID: {image_id}")
    else:
        print(f"{image_id} not found in {table_name}")
        logger.warning(f"Attempted to delete non-existent ID: {image_id}")


def main():
    init_db()

    while True:
        print("\nMenu:")
        print("1. Import skipped images from CSV file")
        print("2. Add skipped image manually")
        print("3. Delete skipped image ID")  # moved up
        print("4. Quit")  # moved down
        choice = input("Enter your choice: ")

        if choice == "1":
            csv_filepath = input("Enter the path to the CSV file: ")
            skipped_image_ids = read_skipped_csv(csv_filepath)
            print("\nSelect a collection to import into:")
            print("1. Regular skipped images")
            print("2. Japanese skipped images")
            collection_choice = input("Enter your choice (1/2): ")
            if collection_choice == "1":
                import_to_sqlite(skipped_image_ids, "skipped_images")
            elif collection_choice == "2":
                import_to_sqlite(skipped_image_ids, "jap_skipped_images")
            else:
                print("Invalid choice. Please try again.")
        elif choice == "2":
            image_id = input("Enter the skipped image ID (with '.jpg' extension): ")
            print("\nSelect a collection to import into:")
            print("1. Regular skipped images")
            print("2. Japanese skipped images")
            collection_choice = input("Enter your choice (1/2): ")
            if collection_choice == "1":
                import_to_sqlite([image_id], "skipped_images")
            elif collection_choice == "2":
                import_to_sqlite([image_id], "jap_skipped_images")
            else:
                print("Invalid choice. Please try again.")
        elif choice == "3":
            image_id = input("Enter the skipped image ID (with '.jpg' extension) to delete: ")
            print("\nSelect a collection to delete from:")
            print("1. Regular skipped images")
            print("2. Japanese skipped images")
            collection_choice = input("Enter your choice (1/2): ")
            if collection_choice == "1":
                delete_from_sqlite(image_id, "skipped_images")
            elif collection_choice == "2":
                delete_from_sqlite(image_id, "jap_skipped_images")
            else:
                print("Invalid choice. Please try again.")
        elif choice == "4":
            break
        else:
            print("Invalid choice. Please try again.")


if __name__ == "__main__":
    main()
