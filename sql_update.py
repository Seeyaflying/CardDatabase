import sqlite3
import json
import logging
import os
import sys  # Still needed for sys.stdout, but used cleanly now
from datetime import datetime

# ------------------------------
# Config
# ------------------------------
DB_FILE = "skipped_images.sqlite"
TABLE_NAME = "skipped_images"
JSON_UPLOAD_FILE = 'skipped_images.json'

# Set up logging for output
LOG_FOLDER = "log"
# Generate a unique log file name
log_file_path = os.path.join(LOG_FOLDER, datetime.now().strftime('%Y-%m-%d_%H-%M-%S') + '_db_utility.log')

# Configure logging
logger = logging.getLogger("db_utility")
logger.setLevel(logging.INFO)
os.makedirs(LOG_FOLDER, exist_ok=True)

# File Handler (Encoding is often handled correctly for files, but setting it explicitly is safer)
file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
file_handler.setFormatter(logging.Formatter('%(message)s'))
logger.addHandler(file_handler)

# Stream Handler (for console output)
# Fix for UnicodeEncodeError: We create the handler with a stream that is guaranteed to be UTF-8.
# The simplest, most direct fix is to pass a wrapper stream or use the 'encoding' parameter
# if available in your logging implementation.
# Here we use an explicit stream creation trick or rely on the best available method.
try:
    # Python 3.9+ might handle StreamHandler(..., encoding='utf-8') directly,
    # but the following works more reliably across Python 3 versions for console output.
    import io

    # Create a wrapper around sys.stdout that forces UTF-8 encoding
    utf8_stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    stream_handler = logging.StreamHandler(utf8_stdout)
except Exception:
    # Fallback for complex environments: just use the default StreamHandler
    stream_handler = logging.StreamHandler(sys.stdout)

stream_handler.setFormatter(logging.Formatter('%(message)s'))
logger.addHandler(stream_handler)


# ------------------------------
# Database Helpers
# ------------------------------

def ensure_table(db_file=DB_FILE, table_name=TABLE_NAME):
    import sqlite3
    import os
    from datetime import datetime

    OLD_DB = "photo_history.db"
    NEW_DB = "skipped_images.sqlite"

    def migrate():
        if not os.path.exists(OLD_DB):
            print(f"[ERROR] {OLD_DB} not found.")
            return

        conn_old = sqlite3.connect(OLD_DB)
        conn_new = sqlite3.connect(NEW_DB)

        # 1. Create table with your exact column names
        print("[1/3] Setting up 'progress' table...")
        conn_new.execute("DROP TABLE IF EXISTS progress")
        conn_new.execute('''
                         CREATE TABLE progress
                         (
                             img_path     TEXT PRIMARY KEY,
                             processed_at TEXT,
                             status       TEXT
                         )
                         ''')

        # 2. Fetch old data
        print("[2/3] Fetching old records...")
        cursor = conn_old.execute("SELECT path, decision FROM processed")
        rows = cursor.fetchall()

        # 3. Insert with current timestamp
        print(f"[3/3] Migrating {len(rows)} items...")
        now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Prepare data: (path, timestamp, decision)
        migration_data = [(r[0], now_ts, r[1]) for r in rows]

        try:
            conn_new.executemany(
                "INSERT OR IGNORE INTO progress (img_path, processed_at, status) VALUES (?, ?, ?)",
                migration_data
            )
            conn_new.commit()
            print("✅ Migration to 'progress' table successful!")
        except Exception as e:
            print(f"❌ Migration failed: {e}")
        finally:
            conn_old.close()
            conn_new.close()

    if __name__ == "__main__":
        migrate()