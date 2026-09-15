import os
import tcg_core
mgr = tcg_core.CardDBManager()
os.system(tcg_core.CLEAR_SCREEN)
sid = input("Search ID: ")
with mgr.get_conn() as conn:
    res = conn.execute("SELECT * FROM skipped_images WHERE image_name LIKE ?", (f"%{sid}%",)).fetchall()
    for r in res: print(f"-> {r['image_name']} | {r['game_name']} | {r['language']}")
tcg_core.wait_for_user()
