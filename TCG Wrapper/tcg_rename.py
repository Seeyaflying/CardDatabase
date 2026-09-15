import os
import time
import tcg_core
mgr = tcg_core.CardDBManager()
os.system(tcg_core.CLEAR_SCREEN)
old = input("Current Name: "); new = input("New Name: ")
with mgr.get_conn() as conn:
    conn.execute("UPDATE tcg_master SET tcg_display_name=? WHERE tcg_display_name=?", (new, old))
    conn.execute("UPDATE skipped_images SET game_name=? WHERE game_name=?", (new, old))
    conn.execute("UPDATE progress SET game_name=? WHERE game_name=?", (new, old))
    conn.commit()
    print("Updated.")
    time.sleep(1.5)
