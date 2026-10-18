"""
seed_done_number.py
===================
Store your old DONE count as a single settings doc in card_tracker.
The web app reads this number for the DONE counter.

Run once:  python seed_done_number.py
"""
import config_v2 as config
import db_v2 as db

DONE_COUNT = 1880868  # <-- your old done number


def main():
    coll = db.tracker_coll()
    coll.update_one(
        {"_id": "done_count"},
        {"$set": {"value": DONE_COUNT}},
        upsert=True,
    )
    print(f"Stored done count: {DONE_COUNT}")
    print("Verification:", coll.find_one({"_id": "done_count"}))


if __name__ == "__main__":
    main()
