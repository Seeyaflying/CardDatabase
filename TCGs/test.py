import sys
import os
# Make config/db importable from Utilities/
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Utilities"))
import config
import db

coll = db.get_db()["progress"]

coll.drop_index("image_name_1")
print("Dropped image_name_1")

print("=== Remaining indexes ===")
for idx in coll.list_indexes():
    print(idx)
