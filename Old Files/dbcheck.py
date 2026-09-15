import os
import shutil
from pathlib import Path
from pymongo import MongoClient

MONGO_URI = "mongodb://card_manager:1369@100.80.179.119:27018/carddb"
DB_NAME = "carddb"
COLLECTION_NAME = "card_index"

SOURCE = Path(r"T:\Card Database")
DEST = Path(r"G:\My Drive\Card Database")
DONE_CARDS = Path(r"T:\Cards Database")

client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
col = client[DB_NAME][COLLECTION_NAME]

print("=" * 60)
print("VERIFY: source vs Google Drive, archive filename matches")
print("=" * 60)

moved = 0
no_match = 0
errors = 0
total = 0

for game_folder in SOURCE.iterdir():
    if not game_folder.is_dir():
        continue
    game = game_folder.name
    drive_folder = DEST / game
    done_folder = DONE_CARDS / game
    if not drive_folder.is_dir():
        continue  # no matching Drive folder -> can't verify

    for f in game_folder.iterdir():
        if not f.is_file():
            continue
        total += 1
        drive_file = drive_folder / f.name

        if not drive_file.exists():
            no_match += 1
            print(f"  NO MATCH in Drive: {game} / {f.name}")
            continue

        # Filename match found -> move source file into Cards Done
        done_folder.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(f), str(done_folder / f.name))
            moved += 1
            print(f"  MOVED: {game} / {f.name} -> Cards Done")
        except Exception as e:
            errors += 1
            print(f"  ERROR moving {game} / {f.name}: {type(e).__name__}: {e}")

print("\n" + "=" * 60)
print(f"Total source files checked: {total}")
print(f"Moved to Cards Done:        {moved}")
print(f"No match in Drive:          {no_match}")
print(f"Errors:                     {errors}")
