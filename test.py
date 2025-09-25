import requests
import requests
import os
import time
import json

# -----------------------------
# Settings
# -----------------------------
OUTPUT_FOLDER = "G:/My Drive/New Cards/Magic the Gathering"
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

JSON_FILE = "scryfall_all_cards.json"  # local copy of the 2GB JSON
REQUEST_DELAY = 0.05  # throttle image requests

# -----------------------------
# Step 1: Download bulk JSON once
# -----------------------------
if not os.path.exists(JSON_FILE):
    print("Downloading bulk JSON file from Scryfall...")
    bulk_data_url = "https://api.scryfall.com/bulk-data"
    bulk_data = requests.get(bulk_data_url).json()

    cards_json_url = None
    for data in bulk_data['data']:
        if data['type'] == 'all_cards':
            cards_json_url = data['download_uri']
            break

    if not cards_json_url:
        raise Exception("Could not find all_cards bulk data URL")

    # Stream download to disk
    with requests.get(cards_json_url, stream=True) as r:
        r.raise_for_status()
        with open(JSON_FILE, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)

    print(f"Downloaded bulk JSON to {JSON_FILE}")
else:
    print(f"Using existing JSON file: {JSON_FILE}")

# -----------------------------
# Step 2: Load JSON from disk
# -----------------------------
print("Loading JSON (this may take a minute)...")
with open(JSON_FILE, "r", encoding="utf-8") as f:
    cards_data = json.load(f)

print(f"Total cards in JSON: {len(cards_data)}")

# -----------------------------
# Step 3: Filter and download foreign cards
# -----------------------------
download_count = 0
for idx, card in enumerate(cards_data):
    try:
        if card["lang"] != "en" and "image_uris" in card:
            img_url = card["image_uris"]["normal"]
            filename = f"{card['name'].replace('/', '-')}_{card['lang']}.jpg"
            path = os.path.join(OUTPUT_FOLDER, filename)

            if not os.path.exists(path):
                img_data = requests.get(img_url).content
                with open(path, "wb") as f:
                    f.write(img_data)

                download_count += 1
                if download_count % 50 == 0:
                    print(f"Downloaded {download_count} images so far")

                time.sleep(REQUEST_DELAY)

    except Exception as e:
        print(f"Error processing card {card.get('name', 'unknown')}: {e}")
        continue

print(f"Done! Total foreign card images downloaded: {download_count}")

