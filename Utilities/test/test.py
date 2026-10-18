import db_v2 as db
coll = db.tracker_coll()
print("pending:", coll.count_documents({"status": "pending"}))
