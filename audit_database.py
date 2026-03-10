import os
import sqlite3

# ==========================
# CONFIGURATION
# ==========================
DRIVE_YES_DIR = r"G:\My Drive\Card Database"
SKIPPED_DB = "skipped_images.sqlite"


def run_audit_and_repair():
    if not os.path.exists(SKIPPED_DB):
        print(f"Error: {SKIPPED_DB} not found.")
        return

    print("\n" + "=" * 45)
    print("      DATABASE INTEGRITY & REPAIR")
    print("=" * 45)

    # 1. Connect and Fetch 'YES' records
    conn = sqlite3.connect(SKIPPED_DB)
    cursor = conn.execute("SELECT img_path FROM progress WHERE status = 'yes'")
    sql_records = [row[0] for row in cursor.fetchall()]

    print(f"Total 'YES' records in SQL: {len(sql_records)}")
    print("Scanning Google Drive for missing files... (This may take a minute)")

    # 2. Build a set of all filenames currently in the Card Database for fast lookup
    drive_files = set()
    for root, _, files in os.walk(DRIVE_YES_DIR):
        for f in files:
            drive_files.add(f.lower())

    # 3. Identify Ghost Records
    ghost_records = []
    for full_path in sql_records:
        filename = os.path.basename(full_path).lower()
        if filename not in drive_files:
            ghost_records.append(full_path)

    # 4. Report Findings
    print("-" * 45)
    if not ghost_records:
        print("✅ SUCCESS: Your SQL Database is 100% accurate.")
        conn.close()
        return

    print(f"⚠️  ALERT: Found {len(ghost_records)} 'Ghost Records'.")
    print("These are marked as 'DONE' in SQL but are MISSING from Drive.")
    print("-" * 45)

    # 5. Repair Option
    confirm = input("Would you like to DELETE these Ghost Records from SQL? (y/n): ").lower()

    if confirm == 'y':
        print(f"Repairing... Removing {len(ghost_records)} entries.")
        try:
            # Delete records where the path matches our ghost list
            conn.executemany("DELETE FROM progress WHERE img_path = ?", [(p,) for p in ghost_records])
            conn.commit()
            print("✅ REPAIR COMPLETE: Your 'DONE' count will now be accurate.")
        except Exception as e:
            print(f"❌ Error during repair: {e}")
    else:
        print("No changes made to the database.")

    conn.close()
    print("=" * 45 + "\n")


if __name__ == "__main__":
    run_audit_and_repair()