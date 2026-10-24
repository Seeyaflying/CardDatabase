"""
main.py
=======
Card Sorter — unified menu.

card_tracker is the single source of truth, shared by:
  - scan_folders_v2.py  (baseline + new card scans)
  - web_app.py       (review cards)
  - uploader.py      (upload approved cards to Immich)

Flow:
  1. Scan Folder Database (one-time baseline)
  2. Scan New Cards (add pending)
  3. Review cards in the web app
  4. Run the Immich uploader
  5. Status report
"""
from pathlib import Path

import subprocess
import sys
import scan_folders_v2
import os



def run(script, *args):
    print(f"\n=== Running {script} {' '.join(args)} ===")
    subprocess.run([sys.executable, script, *args])


def status_report():
    import db_v2
    total = db_v2.tracker_total()
    pending = db_v2.tracker_coll().count_documents({"status": "pending"})
    yes = db_v2.tracker_coll().count_documents({"status": "yes"})
    no = db_v2.tracker_coll().count_documents({"status": "no"})
    uploaded = db_v2.tracker_coll().count_documents({"uploaded": True})
    done = db_v2.tracker_done()
    print(f"\n=== STATUS REPORT ===")
    print(f"  Total tracked:   {total}")
    print(f"  Pending review:  {pending}")
    print(f"  Approved (yes):  {yes}")
    print(f"  Rejected (no):   {no}")
    print(f"  Uploaded:        {uploaded}")
    print(f"  Fully done:      {done}")
    print(f"=====================")


def main():
    while True:
        print("\n=== CARD SORTER MENU ===")
        print("  1. Scan Folder Database (baseline)")
        print("  2. Scan New Cards (add pending)")
        print("  3. Start web app (review cards)")
        print("  4. Run Immich uploader")
        print("  5. Status report")
        print("  0. Exit")
        choice = input("Choice: ").strip()

        if choice == "1":
            scan_folders_v2.baseline()
        elif choice == "2":
            scan_folders_v2.scan_new()
        elif choice == "3":
            run("web_base_v2.py")
        elif choice == "4":
            run("uploader_v2.py")
        elif choice == "5":
            status_report()
        elif choice == "0":
            print("Goodbye.")
            break
        else:
            print("Invalid choice.")


if __name__ == "__main__":
    main()
