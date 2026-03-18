import sqlite3
from datetime import datetime

DB_NAME = "skipped_images.sqlite"

def jap_cards_get_conn():
    return sqlite3.connect(DB_NAME)

def jap_cards_init_db(full_mapping):
    conn = jap_cards_get_conn()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS jap_cards_tcgs (
            tcg_name TEXT PRIMARY KEY,
            site_id INTEGER,
            total_pages INTEGER,
            last_run TEXT
        )
    ''')
    for name, data in full_mapping.items():
        cursor.execute('''
            INSERT INTO jap_cards_tcgs (tcg_name, site_id, total_pages)
            VALUES (?, ?, ?)
            ON CONFLICT(tcg_name) DO UPDATE SET total_pages = excluded.total_pages
        ''', (name, data['id'], data['total_pages']))
    conn.commit()
    conn.close()

def jap_cards_get_list():
    conn = jap_cards_get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT tcg_name, site_id, total_pages, last_run FROM jap_cards_tcgs ORDER BY tcg_name ASC")
    rows = cursor.fetchall()
    conn.close()
    return rows

def jap_cards_update_run_time(name):
    conn = jap_cards_get_conn()
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("UPDATE jap_cards_tcgs SET last_run = ? WHERE tcg_name = ?", (now, name))
    conn.commit()
    conn.close()