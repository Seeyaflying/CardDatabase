import os
import time
import tcg_core
mgr = tcg_core.CardDBManager()
os.system(tcg_core.CLEAR_SCREEN)
with mgr.get_conn() as conn:
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
    for i, t in enumerate(tables, 1): print(f"{i}. {t['name']}")
    idx = input("\nDelete Table #: ")
    if idx.isdigit() and 0 < int(idx) <= len(tables):
        target = tables[int(idx) - 1]['name']
        if input(f"Type 'DELETE' to confirm: ") == "DELETE":
            conn.execute(f"DROP TABLE {target}")
            print("Deleted.")
            time.sleep(1)
