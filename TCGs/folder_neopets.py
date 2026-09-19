import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import requests

# Point Python at the utilities folder (one level up from TCGs/)
UTILS = Path(__file__).resolve().parent.parent / "utilities"
sys.path.insert(0, str(UTILS))

import config
import db

BASE_URL = "https://my.upperdeck.com/public/neopets/cards"
IMAGE_BASE = "https://my.upperdeck.com"

# Where NEW downloads land (each set gets its own subfolder below this)
SAVE_ROOT = Path(r"T:\Full Card Database\New Cards\NeoPets Battledome")
SAVE_ROOT.mkdir(parents=True, exist_ok=True)

# Existing archive folder to also check before downloading
ARCHIVE_DIR = Path(r"T:\Full Card Database\Card Database\NeoPets Battledome")

# Mongo collection for Neopets card metadata + download tracking
META_COLLECTION = "neopets_cards"


def get_props(page):
    """Fetch one page and return the parsed Inertia JSON props."""
    print(f"  Fetching page {page}...", flush=True)
    r = requests.get(BASE_URL, params={"page": page}, timeout=30)
    r.raise_for_status()
    m = re.search(r'<div id="app" data-page="([^"]+)"', r.text)
    if not m:
        raise RuntimeError(f"No data-page JSON found on page {page}")
    raw = m.group(1).replace("&quot;", '"').replace("&amp;", "&")
    props = json.loads(raw)["props"]
    print(f"    -> page {page} OK", flush=True)
    return props


def image_url(card):
    """Absolute URL for the card image (webp preferred, png fallback.)"""
    path = card.get("image_webp") or card.get("image_url")
    return urljoin(IMAGE_BASE, path) if path else None


def upsert_card(card, downloaded, local_path):
    """Save or update one card's record in Mongo."""
    coll = db.get_db()[META_COLLECTION]
    doc = {
        "card_id": card.get("id"),
        "name": card.get("name"),
        "number": card.get("number"),
        "rarity": card.get("rarity"),
        "type": card.get("type"),
        "type_special": card.get("type_special"),
        "color": card.get("color"),
        "team": card.get("team"),
        "set": card.get("set"),
        "artist": card.get("artist_name"),
        "attack": card.get("attack"),
        "defence": card.get("defence"),
        "agility": card.get("agility"),
        "health": card.get("health"),
        "text": card.get("text"),
        "image_url": image_url(card),
        "downloaded": downloaded,
        "local_path": str(local_path) if local_path else None,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    coll.update_one({"card_id": card.get("id")}, {"$set": doc}, upsert=True)


def get_all_sets():
    """Return a dict of set name -> list of card dicts, by scanning all pages once."""
    print("\n[1/2] Scanning all pages to build set list...", flush=True)
    props = get_props(1)
    cards_obj = props.get("cards")
    last_page = cards_obj.get("last_page", 97) if isinstance(cards_obj, dict) else 97

    sets = {}
    total_cards = 0
    for page in range(1, last_page + 1):
        cards = get_props(page).get("cards")
        if isinstance(cards, dict):
            cards = cards.get("data", [])
        for card in cards:
            set_name = card.get("set", "Unknown")
            sets.setdefault(set_name, []).append(card)
            total_cards += 1
        print(f"    page {page}/{last_page} — running total: {total_cards} cards", flush=True)
    print(f"  Done scanning. Found {len(sets)} sets, {total_cards} total cards.", flush=True)
    return sets


def safe_set_name(name):
    """Make a set name safe for use as a folder name."""
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip()


def main():
    parser = argparse.ArgumentParser(description="NeoPets Battledome card harvester")
    parser.add_argument("set_name", nargs="?", default=None,
                        help="Name of the set to download (omit for all sets)")
    parser.add_argument("--list", action="store_true",
                        help="List all available sets and exit")
    args = parser.parse_args()

    db.init_db()
    coll = db.get_db()[META_COLLECTION]
    coll.create_index("card_id", unique=True)

    # Discover total pages from page 1's paginator metadata
    props = get_props(1)
    cards_obj = props.get("cards")
    last_page = cards_obj.get("last_page", 97) if isinstance(cards_obj, dict) else 97
    total = cards_obj.get("total", 0) if isinstance(cards_obj, dict) else 0
    print(f"Found {total} cards across {last_page} pages.\n")

    # Build the set -> cards map
    sets = get_all_sets()

    if args.list:
        print("\nAvailable sets:")
        for name in sorted(sets):
            print(f"  {name}  ({len(sets[name])} cards)")
        db.close()
        return

    # Decide which cards to download
    if args.set_name:
        target = args.set_name
        if target not in sets:
            print(f"Set '{target}' not found. Available sets:")
            for name in sorted(sets):
                print(f"  {name}")
            db.close()
            return
        cards = sets[target]
        print(f"\n[2/2] Downloading set '{target}' — {len(cards)} cards.\n", flush=True)
    else:
        # No set name given -> download everything
        cards = [card for set_cards in sets.values() for card in set_cards]
        print(f"\n[2/2] Downloading ALL sets — {len(cards)} cards.\n", flush=True)

    new_count = existing_count = skipped_count = failed_count = 0
    for idx, card in enumerate(cards, start=1):
        number = card.get("number") or str(card.get("id"))
        safe = re.sub(r'[\\/:*?"<>|]', "_", card.get("name", "unknown"))
        set_name = card.get("set", "Unknown")
        safe_set = safe_set_name(set_name)

        # Per-set destination folder
        dest_dir = SAVE_ROOT / safe_set
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{number}_{safe}.webp"

        if dest.exists():
            status = "EXISTING"
            downloaded = True
            local_path = None
            existing_count += 1
        elif ARCHIVE_DIR.exists() and (ARCHIVE_DIR / dest.name).exists():
            status = "SKIPPED"
            downloaded = True
            local_path = None
            skipped_count += 1
        else:
            try:
                url = image_url(card)
                print(f"  [{idx}/{len(cards)}] DOWNLOADING {number} - {card.get('name', 'unknown')} ({set_name})...", flush=True)
                r = requests.get(url, timeout=30)
                r.raise_for_status()
                dest.write_bytes(r.content)
                status = "NEW"
                downloaded = True
                local_path = dest
                new_count += 1
                print(f"    -> saved to {dest}", flush=True)
            except Exception as e:
                status = "FAILED"
                downloaded = False
                local_path = None
                failed_count += 1
                print(f"    -> FAILED: {e}", flush=True)

        if status in ("EXISTING", "SKIPPED"):
            print(f"  [{idx}/{len(cards)}] {status} {number} - {card.get('name', 'unknown')} ({set_name})", flush=True)

        upsert_card(card, downloaded, local_path)
        time.sleep(0.3)

        # Running tally every 25 cards so you know it's alive
        if idx % 25 == 0:
            print(f"  --- progress: {idx}/{len(cards)} | new: {new_count} | existing: {existing_count} | skipped: {skipped_count} | failed: {failed_count}", flush=True)

    print(f"\nDone. New: {new_count}   Existing: {existing_count}   "
          f"Skipped: {skipped_count}   Failed: {failed_count}")
    db.close()


if __name__ == "__main__":
    main()

