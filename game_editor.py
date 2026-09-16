from pymongo import MongoClient
import requests
import re

MONGO_URI = "mongodb://card_manager:1369@100.80.179.119:27018/carddb"
DB_NAME   = "carddb"

def normalize(s):
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return s

client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000)
db = client[DB_NAME]
tcg_master = db["tcg_master"]

# ============ MAIN MENU ============
print("=" * 60)
print("TCG MASTER MANAGER")
print("=" * 60)
print(" 1. Add a new TCG entry")
print(" 2. Delete a TCG entry")
print(" 0. Exit")
print("=" * 60)
action = input("Select: ").strip()

if action == "0":
    client.close()
    print("Goodbye.")
    raise SystemExit

# ============ ADD ============
if action == "1":
    print("\n--- ADD NEW TCG ENTRY ---")

    name = input("Game display name (e.g. Gundam): ").strip()
    if not name:
        print("No name entered. Exiting.")
        client.close()
        raise SystemExit

    lang = input("Language (english / japanese) [english]: ").strip().lower() or "english"
    if lang not in ("english", "japanese"):
        print("Invalid language. Use 'english' or 'japanese'.")
        client.close()
        raise SystemExit

    folder = input(f"Folder name [{name}]: ").strip() or name

    print("\nSearching TCGCSV for matching categories...")
    r = requests.get("https://tcgcsv.com/tcgplayer/categories", headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    categories = r.json()["results"]

    matches = []
    for c in categories:
        cname = c.get("name", "")
        cdisplay = c.get("displayName", "")
        if normalize(name) in normalize(cname) or normalize(name) in normalize(cdisplay):
            matches.append(c)

    if matches:
        print(f"\nFound {len(matches)} matching category(ies):")
        for i, c in enumerate(matches, 1):
            print(f"  {i}. categoryId={c['categoryId']}  name={c.get('name')}  displayName={c.get('displayName')}")
        choice = input("Select # (or press Enter to type the ID manually): ").strip()
        if choice and choice.isdigit() and 1 <= int(choice) <= len(matches):
            site_id = matches[int(choice) - 1]["categoryId"]
        else:
            site_id = int(input("Enter the categoryId manually: ").strip())
    else:
        print("No matching categories found in TCGCSV.")
        site_id = int(input("Enter the categoryId manually: ").strip())

    print("\nSummary:")
    print(f"  Name:     {name}")
    print(f"  Language: {lang}")
    print(f"  Folder:   {folder}")
    print(f"  Site ID:  {site_id}")

    confirm = input("\nInsert this row into tcg_master? (y/N): ").strip().lower()
    if confirm != "y":
        print("Cancelled.")
        client.close()
        raise SystemExit

    existing = tcg_master.find_one({"tcg_display_name": name, "language": lang})
    if existing:
        print(f"Warning: a row already exists for '{name}' ({lang}) with site_id={existing.get('site_id')}.")
        overwrite = input("Overwrite it with the new site_id? (y/N): ").strip().lower()
        if overwrite == "y":
            tcg_master.update_one(
                {"_id": existing["_id"]},
                {"$set": {"site_id": site_id, "folder_name": folder}}
            )
            print("Updated existing row.")
        else:
            print("Cancelled.")
    else:
        tcg_master.insert_one({
            "tcg_display_name": name,
            "site_id": site_id,
            "folder_name": folder,
            "language": lang,
            "total_pages": 0,
            "last_run": None,
        })
        print("Inserted new row.")

# ============ DELETE ============
elif action == "2":
    print("\n--- DELETE TCG ENTRY ---")

    print("Current entries in tcg_master:")
    rows = list(tcg_master.find({}).sort("tcg_display_name", 1))
    for i, r in enumerate(rows, 1):
        print(f"  {i}. {r.get('tcg_display_name')} | lang={r.get('language')} | site_id={r.get('site_id')}")

    if not rows:
        print("  (none)")
        client.close()
        raise SystemExit

    choice = input("\nSelect # to delete (or type a name, or 'all'): ").strip()

    targets = []
    if choice.lower() == "all":
        targets = rows
    else:
        if choice.isdigit() and 1 <= int(choice) <= len(rows):
            targets = [rows[int(choice) - 1]]
        else:
            matches = [r for r in rows if choice.lower() in r.get("tcg_display_name", "").lower()]
            if not matches:
                print("No matching entry found.")
                client.close()
                raise SystemExit
            if len(matches) == 1:
                targets = matches
            else:
                print("\nMultiple matches:")
                for i, m in enumerate(matches, 1):
                    print(f"  {i}. {m.get('tcg_display_name')} | lang={m.get('language')} | site_id={m.get('site_id')}")
                sel = input("Select #: ").strip()
                if sel.isdigit() and 1 <= int(sel) <= len(matches):
                    targets = [matches[int(sel) - 1]]
                else:
                    print("Invalid selection.")
                    client.close()
                    raise SystemExit

    print("\nYou are about to delete:")
    for t in targets:
        print(f"  - {t.get('tcg_display_name')} | lang={t.get('language')} | site_id={t.get('site_id')}")

    confirm = input("\nDelete these? (y/N): ").strip().lower()
    if confirm != "y":
        print("Cancelled.")
        client.close()
        raise SystemExit

    for t in targets:
        result = tcg_master.delete_one({"_id": t["_id"]})
        print(f"Deleted: {t.get('tcg_display_name')} (lang={t.get('language')}) - {result.deleted_count} row(s)")

else:
    print("Invalid choice.")

client.close()
print("Done.")
