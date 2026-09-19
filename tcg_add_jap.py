import sys
from pathlib import Path

# Find utilities/config.py no matter where this script is saved
def find_utilities(start=None):
    start = Path(start or __file__).resolve()
    for folder in [start] + list(start.parents):
        candidate = folder / "utilities"
        if (candidate / "config.py").exists():
            return candidate
    return None

utils_dir = find_utilities()
if utils_dir is None:
    raise SystemExit("Could not find utilities/config.py")
sys.path.insert(0, str(utils_dir))

import time
from pymongo import MongoClient
import config

client = MongoClient(config.MONGO_URI, serverSelectionTimeoutMS=5000)
db = client[config.DB_NAME]
coll = db["tcg_master"]


def add_tcg(tcg_display_name, language, folder_name, site_id, total_pages):
    result = coll.update_one(
        {"tcg_display_name": tcg_display_name, "language": language},
        {
            "$set": {"language": language, "last_run": time.strftime("%Y-%m-%d %H:%M")},
            "$setOnInsert": {
                "tcg_display_name": tcg_display_name,
                "folder_name": folder_name,
                "site_id": site_id,
                "total_pages": total_pages,
            },
        },
        upsert=True,
    )
    return result.upserted_id is not None


def ask_int(prompt, default=None):
    while True:
        raw = input(prompt).strip()
        if raw == "" and default is not None:
            return default
        try:
            return int(raw)
        except ValueError:
            print("  Please enter a whole number.")


def add_new_entry():
    print("\n--- New entry (blank name to finish) ---")
    name = input("TCG display name: ").strip()
    if not name:
        print("Nothing added.")
        return

    language = input("Language (english/japanese): ").strip().lower()
    if language not in ("english", "japanese"):
        print("  Invalid language, defaulting to english.")
        language = "english"

    folder = name
    site_id = ask_int("Site id / number: ", default=0)

    total_pages = 0
    if language == "japanese":
        total_pages = ask_int("Total pages: ", default=0)

    new = add_tcg(name, language, folder, site_id, total_pages)
    print(f"  {'INSERTED new entry' if new else 'Updated existing entry'}: "
          f"{name} ({language})")


def edit_japanese_pages():
    print("\n--- Japanese entries ---")
    jap = list(coll.find({"language": "japanese"}).sort("tcg_display_name", 1))
    if not jap:
        print("No Japanese entries found.")
        return

    for i, doc in enumerate(jap, start=1):
        print(f"  {i}. {doc['tcg_display_name']}  |  pages: {doc.get('total_pages', 0)}")

    print("\nEnter the number of the entry to edit its page count.")
    print("Enter 0 to go back to the menu.")
    while True:
        choice = ask_int("\nSelection: ", default=0)
        if choice == 0:
            return
        if 1 <= choice <= len(jap):
            doc = jap[choice - 1]
            name = doc["tcg_display_name"]
            print(f"\nEditing: {name} (currently {doc.get('total_pages', 0)} pages)")
            new_pages = ask_int("New total pages: ", default=doc.get("total_pages", 0))
            coll.update_one(
                {"tcg_display_name": name, "language": "japanese"},
                {"$set": {"total_pages": new_pages,
                          "last_run": time.strftime("%Y-%m-%d %H:%M")}},
            )
            print(f"  Updated {name} to {new_pages} pages.")
            return
        print("  Invalid selection.")


def main():
    while True:
        print("\n" + "=" * 50)
        print("TCG MASTER")
        print("=" * 50)
        print(" 1. Add a new TCG entry")
        print(" 2. Find & edit Japanese page numbers")
        print(" 0. Exit")
        choice = input("Select: ").strip()

        if choice == "1":
            add_new_entry()
        elif choice == "2":
            edit_japanese_pages()
        elif choice == "0":
            print("Goodbye.")
            break
        else:
            print("Invalid choice.")


if __name__ == "__main__":
    main()


