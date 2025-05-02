import ssl
from pymongo import MongoClient

MONGO_URI ='mongodb+srv://seeyaflying:Riversong1969@cluster0.7fugd.mongodb.net/?ssl=true'

try:
    mongo_client = MongoClient(MONGO_URI)
    print("Connected to MongoDB")
except Exception as e:
    print(f"Failed to connect to MongoDB: {e}")

try:
    db = mongo_client["tcg_database"]
    print("Connected to database")
except Exception as e:
    print(f"Failed to connect to database: {e}")

try:
    collection = db["jap_skipped_images"]
    print("Connected to collection")
except Exception as e:
    print(f"Failed to connect to collection: {e}")