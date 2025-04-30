import csv
import logging
from datetime import date
from pymongo import MongoClient
import os

# Create a logger
today = date.today()
log_filename = f"{today.strftime('%Y-%m-%d')}_csv_importer.log"
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

def import_to_mongo(skipped_image_ids):
    """Imports the skipped image IDs into the MongoDB database."""
    MONGO_URI ='mongodb+srv://seeyaflying:Riversong1969@cluster0.7fugd.mongodb.net/'
    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client["tcg_database"]
    db["skipped_images"].create_index("image_name", unique=True)

    added_count = 0
    for image_id in skipped_image_ids:
        try:
            db["skipped_images"].insert_one({"image_name": image_id})
            print(f"Added {image_id} to the database")
            logger.info(f"Inserted skipped image ID: {image_id}")
            added_count += 1
        except Exception as e:
            logger.error(f"Error inserting skipped image ID: {e}")
    print(f"Added {added_count} skipped image IDs to the database")

def main():
    csv_filepath = os.path.join("json", "skipped.csv")
    skipped_image_ids = read_skipped_csv(csv_filepath)
    import_to_mongo(skipped_image_ids)

if __name__ == "__main__":
    main()