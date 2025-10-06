import os
import json
import sqlite3

# ------------------------------
# Paths
# ------------------------------
BASE_DIR = r"G:\My Drive\models\CardData"
JSON_PATH = os.path.join(BASE_DIR, "values.json")
DB_PATH = os.path.join(BASE_DIR, "skipped_images.sqlite")
TABLE_NAME = "card_ai"

# ------------------------------
# Ensure Database & Table
# ------------------------------
def ensure_database():
    """Ensure database and card_ai table exist."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            genome INTEGER NOT NULL,
            total_steps INTEGER NOT NULL,
            full_iteration INTEGER NOT NULL
        )
    """)
    conn.commit()
    return conn

# ------------------------------
# Upsert JSON to Database
# ------------------------------
def upsert_json_to_db(conn):
    """Read JSON file and upsert values into card_ai table."""
    if not os.path.exists(JSON_PATH):
        print(f"❌ JSON file not found at: {JSON_PATH}")
        return

    try:
        with open(JSON_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"❌ Failed to read JSON: {e}")
        return

    genome = data.get("genome", 1)
    total_steps = data.get("total_steps", 0)
    full_iteration = data.get("full_iteration", 0)

    cursor = conn.cursor()
    cursor.execute(f"""
        INSERT INTO {TABLE_NAME} (id, genome, total_steps, full_iteration)
        VALUES (1, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            genome=excluded.genome,
            total_steps=excluded.total_steps,
            full_iteration=excluded.full_iteration
    """, (genome, total_steps, full_iteration))
    conn.commit()

    print(f"✅ Updated '{TABLE_NAME}' with JSON values:")
    print(f"   Genome: {genome}")
    print(f"   Total Steps: {total_steps}")
    print(f"   Full Iteration: {full_iteration}")

# ------------------------------
# Check Current Table Contents
# ------------------------------
def check_table(conn):
    """Display current values in the card_ai table."""
    cursor = conn.cursor()
    cursor.execute(f"SELECT id, genome, total_steps, full_iteration FROM {TABLE_NAME}")
    rows = cursor.fetchall()

    print(f"\n📋 Current contents of '{TABLE_NAME}':")
    if not rows:
        print("   (no records found)")
    else:
        for row in rows:
            print(f"   ID={row[0]} | Genome={row[1]} | Total Steps={row[2]} | Full Iteration={row[3]}")

# ------------------------------
# Main Function
# ------------------------------
def main():
    print(f"--- Syncing JSON → SQLite ({DB_PATH}) ---\n")
    conn = ensure_database()
    upsert_json_to_db(conn)
    check_table(conn)
    conn.close()
    print("\n✅ Done — values.json synced to card_ai table successfully.")

# ------------------------------
# Entry Point
# ------------------------------
if __name__ == "__main__":
    main()
