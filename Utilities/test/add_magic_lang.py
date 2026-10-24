import re
from pathlib import Path
import db_v2
from pymongo import UpdateOne

LANG_SOURCE_STR = r"T:\Full Card Database\Folder Database"
_ROOT_RE = "^" + re.escape(LANG_SOURCE_STR)
MAGIC_GAME = "Magic the Gathering"

# Filename suffix (the part after the last "_", before the extension) -> language.
# Add/remove entries to match your naming.
SUFFIX_TO_LANG = {
    "en": "english",
    "de": "german",
    "es": "spanish",
    "fr": "french",
    "it": "italian",
    "ja": "japanese",
    "jp": "japanese",
    "pt": "portuguese",
    "ru": "russian",
    "zh": "chinese",
    "zhs": "chinese",   # simplified
    "zht": "chinese",   # traditional
    "cn": "chinese",
    "ko": "korean",
}

# The main (set-less) folder to SKIP — adjust if yours is called something else.
MAIN_FOLDER_NAMES = {"Main", "main", ""}


def lang_from_filename(name):
    """Language name for a card filename, or None if the suffix isn't known."""
    stem = Path(name).stem                      # "Aarakocra Sneak_de" (no ext)
    parts = stem.split("_")
    if len(parts) < 2:
        return None
    return SUFFIX_TO_LANG.get(parts[-1].lower())


def main():
    coll = db_v2.tracker_coll()

    query = {
        "status": "pending",
        "game_name": MAGIC_GAME,
        "file_path": {"$regex": f"^{_ROOT_RE}"},
    }
    print("[MAGIC] scanning pending Magic cards under Folder Database...")

    ops = []
    done_count = 0
    main_skipped = 0
    no_lang = 0
    sample = []

    for doc in coll.find(query):
        fp = doc.get("file_path", "")
        p = Path(fp)
        set_name = doc.get("set_name")

        # SKIP the main folder: cards with no set, or the pseudo-set "Main".
        if not set_name or set_name in MAIN_FOLDER_NAMES:
            main_skipped += 1
            continue

        lang = lang_from_filename(p.name)
        if lang is None:
            no_lang += 1
            sample.append(p.name)
            continue

        ops.append(UpdateOne(
            {"_id": doc["_id"]},
            {"$set": {"language": lang, "status": "done"}},
        ))
        done_count += 1

    print(f"[MAGIC] detected lang:      {done_count}")
    print(f"[MAGIC] skipped main folder: {main_skipped}")
    print(f"[MAGIC] unrecognized suffix (left pending): {no_lang}")

    if sample:
        print("[MAGIC] sample unrecognized filenames:")
        for n in sample[:20]:
            print("   ", n)

    # Write in chunks so we don't hold hundreds of thousands in memory.
    BULK = 1000
    for i in range(0, len(ops), BULK):
        res = coll.bulk_write(ops[i:i + BULK], ordered=False)
        db_v2.bookkeeping_inc("total_done", res.modified_count)
        print(f"[MAGIC] wrote {res.modified_count} (progress {i + BULK}/{len(ops)})...")

    print(f"[MAGIC] DONE — {done_count} cards assigned")


if __name__ == "__main__":
    main()
