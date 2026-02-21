import sqlite3

DB_PATH = "skipped_images.sqlite"  # point this at the exact DB your cache-mode run is using
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
cur.execute("DELETE FROM progress")
conn.commit()
conn.close()
print("Cleared progress table.")