import time
import re
import requests
from pathlib import Path
from pymongo import MongoClient

MONGO_URI = "mongodb://card_manager:1369@100.80.179.119:27018/carddb"
DB_NAME   = "carddb"
TCG_MASTER_COLLECTION = "tcg_master"
META_COLLECTION       = "cards_meta"

HEADERS = {"User-Agent": "CardDatabaseManager/1.0.0"}
SLEEP = 0.1

client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000)
db = client[DB_NAME]
card_index = db["card_index"]
meta = db[META_COLLECTION]
tcg_master = db[TCG_MASTER_COLLECTION]

def normalize(s):
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return s

def fetch(url):
    print(f"    [GET] {url}")
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    data = r.json()["results"]
    print(f"    [OK] returned {len(data)} items")
    return data

session = requests.Session()
session.headers.update(HEADERS)

# Read all English games with a real site_id from tcg_master
games = list(tcg_master.find({"language": "english", "site_id": {"$ne": 0}}))
print(f"Found {len(games)} English games with site_id in tcg_master.")

# SAFETY LIMIT: uncomment to test on only the first N games
# games = games[:3]

for entry in games:
    GAME_NAME = entry["tcg_display_name"]
    SITE_ID   = entry["site_id"]

    print(f"\n{'='*60}")
    print(f"=== {GAME_NAME} (site {SITE_ID}) ===")
    print("=" * 60)

    # 1. Pull groups (sets)
    print("\n[STEP 1] Fetching groups (sets)...")
    try:
        groups = fetch(f"https://tcgcsv.com/tcgplayer/{SITE_ID}/groups")
    except Exception as e:
        print(f"  ERROR fetching groups: {e}")
        continue
    for g in groups:
        print(f"    - groupId={g['groupId']}  name={g['name']}")

    # 2. Pull products, store metadata
    print("\n[STEP 2] Fetching products and storing metadata...")
    card_meta = {}
    for g in groups:
        gid = g["groupId"]
        print(f"\n  Processing set: {g['name']} (groupId={gid})")
        try:
            products = fetch(f"https://tcgcsv.com/tcgplayer/{SITE_ID}/{gid}/products")
        except Exception as e:
            print(f"    ERROR fetching products: {e}")
            continue
        for p in products:
            ext = {e.get("name", ""): e.get("value", "") for e in p.get("extendedData", [])}
            meta.update_one(
                {"productId": p["productId"]},
                {"$set": {
                    "productId": p["productId"],
                    "game": GAME_NAME,
                    "name": p["name"],
                    "cleanName": p.get("cleanName", ""),
                    "imageUrl": p.get("imageUrl", ""),
                    "groupId": gid,
                    "setName": g.get("name", ""),
                    "rarity": ext.get("Rarity", ""),
                    "number": ext.get("Number", ""),
                    "cardType": ext.get("Card Type", ""),
                }},
                upsert=True,
            )
            card_meta[normalize(p["name"])] = p
        print(f"    Stored {len(products)} products from this set")
        time.sleep(SLEEP)

    print(f"\n  Done. {len(card_meta)} unique cards in cards_meta for {GAME_NAME}.")

    # 3. Join to card_index by productId from filename
    print("\n[STEP 3] Joining to card_index by productId...")
    matched = unmatched = 0
    unmatched_examples = []
    total_cards = card_index.count_documents({"game": GAME_NAME})
    print(f"  {total_cards} {GAME_NAME} cards in card_index to process.")

    for i, doc in enumerate(card_index.find({"game": GAME_NAME}), 1):
        fn = Path(doc["filename"]).stem
        num_part = re.sub(r"[^0-9]", "", fn)
        p = None
        if num_part:
            p = meta.find_one({"productId": int(num_part)})
        if p:
            card_index.update_one(
                {"_id": doc["_id"]},
                {"$set": {
                    "card_name": p["name"],
                    "set_name": p.get("setName", ""),
                    "rarity": p.get("rarity", ""),
                    "card_number": p.get("number", ""),
                    "image_url": p.get("imageUrl", ""),
                    "product_id": p["productId"],
                }},
            )
            matched += 1
            print(f"  [{i}/{total_cards}] MATCH  {doc['filename']} -> {p['name']}")
        else:
            unmatched += 1
            if len(unmatched_examples) < 10:
                unmatched_examples.append(doc["filename"])
            print(f"  [{i}/{total_cards}] NO MATCH  {doc['filename']}")
        time.sleep(SLEEP)

    print(f"\n  RESULT: Matched {matched}   Unmatched {unmatched}   (of {total_cards})")
    if unmatched_examples:
        print(f"  Example unmatched filenames: {unmatched_examples}")

client.close()
print("\nAll games done.")
