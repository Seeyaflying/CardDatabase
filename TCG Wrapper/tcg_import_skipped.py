import os
import time
from datetime import datetime
import tcg_core
mgr = tcg_core.CardDBManager()
os.system(tcg_core.CLEAR_SCREEN)
print(f"{tcg_core.Color.CYAN}--- SKIPPED IMPORT ---{tcg_core.Color.END}")
with mgr.get_conn() as conn:
    configs = conn.execute("SELECT * FROM tcg_master ORDER BY tcg_display_name ASC").fetchall()
for i, c in enumerate(configs, 1): print(f" {i:2}. {c['tcg_display_name']} [{c['language']}]")
choice = input(f"\nSelect #: ")
if choice.isdigit() and 0 < int(choice) <= len(configs):
    cfg = configs[int(choice) - 1]
    target = os.path.join(tcg_core.SKIPPED_ROOT_DIR, cfg['folder_name'])
    if os.path.exists(target):
        files = [f for f in os.listdir(target) if f.lower().endswith(('.png', '.jpg'))]
        with mgr.get_conn() as conn:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M")
            for f in files:
                iid = os.path.splitext(f)[0]
                conn.execute("INSERT OR IGNORE INTO skipped_images VALUES (?, ?, ?, ?)", (iid, cfg['tcg_display_name'], cfg['language'], ts))
                conn.execute("INSERT OR IGNORE INTO progress VALUES (?, ?, ?, 'rejected', ?)", (iid, cfg['tcg_display_name'], cfg['language'], ts))
        print(f"Imported {len(files)} items.")
        time.sleep(1)
tcg_core.wait_for_user()
