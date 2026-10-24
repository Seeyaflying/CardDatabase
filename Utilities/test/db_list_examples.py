#!/usr/bin/env python3
"""
db_reader.py
============
Dump 5 example documents from every collection in the Card Database
MongoDB, so we can see what data exists before the v2 merge.
"""

from pprint import pprint

import config_v2
import db_v2


def summarize_doc(doc, max_fields=15):
    """Return a compact, readable version of a document."""
    out = {}
    for k, v in list(doc.items())[:max_fields]:
        if k == "_id":
            out[k] = str(v)
        elif isinstance(v, (dict, list)):
            out[k] = f"<{type(v).__name__} len={len(v)}>"
        else:
            out[k] = v
    return out


def main():
    db = db_v2.get_db()

    print(f"Database: {config_v2.DB_NAME}")
    print(f"Server:   {config_v2.MONGO_URI}")
    print("=" * 60)

    collections = sorted(db.list_collection_names())
    if not collections:
        print("No collections found.")
        return

    for name in collections:
        coll = db[name]
        count = coll.count_documents({})
        print(f"\n### {name}  ({count:,} docs)")

        if count == 0:
            print("    (empty)")
            continue

        # Show the distinct fields present (schema hint)
        sample = coll.find_one()
        fields = sorted(sample.keys())
        print(f"    fields: {', '.join(fields)}")

        print(f"    examples (up to 5):")
        for doc in coll.find().limit(5):
            pprint(summarize_doc(doc))
            print()

    # Summary
    print("=" * 60)
    print("SUMMARY")
    total = 0
    for name in collections:
        count = db[name].count_documents({})
        total += count
        print(f"  {name:30s} {count:>8,} docs")
    print(f"  {'TOTAL':30s} {total:>8,} docs")


if __name__ == "__main__":
    main()
