import csv
import logging
from datetime import date
from pymongo import MongoClient
import os

# Create a logger
today = date.today()
log_folder = 'log'
log_filename = f"{log_folder}/{today.strftime('%Y-%m-%d')}_csv_importer.log"

# Create the log folder if it doesn't exist
if not os.path.exists(log_folder):
    os.makedirs(log_folder)

logger = logging.getLogger('csv_importer')
logger.setLevel(logging.INFO)
handler = logging.FileHandler(log_filename)
handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(handler)

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

def import_to_mongo(skipped_image_ids, collection_name):
    """Imports the skipped image IDs into the MongoDB database."""
    MONGO_URI ='mongodb+srv://seeyaflying:Riversong1969@cluster0.7fugd.mongodb.net/'
    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client["tcg_database"]
    db[collection_name].create_index("image_name", unique=True)

    added_count = 0
    for image_id in skipped_image_ids:
        try:
            db[collection_name].insert_one({"image_name": image_id})
            print(f"Added {image_id} to the database")
            logger.info(f"Inserted skipped image ID: {image_id}")
            added_count += 1
        except Exception as e:
            logger.error(f"Error inserting skipped image ID: {e}")
    print(f"Added {added_count} skipped image IDs to the database")

def main():
    while True:
        print("\nMenu:")
        print("1. Import skipped images from CSV file")
        print("2. Add skipped image manually")
        print("3. Quit")
        choice = input("Enter your choice: ")

        if choice == "1":
            csv_filepath = input("Enter the path to the CSV file: ")
            skipped_image_ids = read_skipped_csv(csv_filepath)
            print("\nSelect a collection to import into:")
            print("1. Regular skipped images")
            print("2. Japanese skipped images")
            collection_choice = input("Enter your choice (1/2): ")
            if collection_choice == "1":
                import_to_mongo(skipped_image_ids, "skipped_images")
            elif collection_choice == "2":
                import_to_mongo(skipped_image_ids, "jap_skipped_images")
            else:
                print("Invalid choice. Please try again.")
        elif choice == "2":
            image_id = input("Enter the skipped image ID (with '.jpg' extension): ")
            print("\nSelect a collection to import into:")
            print("1. Regular skipped images")
            print("2. Japanese skipped images")
            collection_choice = input("Enter your choice (1/2): ")
            if collection_choice == "1":
                import_to_mongo([image_id], "skipped_images")
            elif collection_choice == "2":
                import_to_mongo([image_id], "jap_skipped_images")
            else:
                print("Invalid choice. Please try again.")
        elif choice == "3":
            break
        else:
            print("Invalid choice. Please try again.")

if __name__ == "__main__":
    main()