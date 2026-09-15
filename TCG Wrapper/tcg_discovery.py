import os
import tkinter as tk
import tcg_core
mgr = tcg_core.CardDBManager()
os.system(tcg_core.CLEAR_SCREEN)
mode = input("1. New | 2. All: ")
with mgr.get_conn() as conn:
    reg = [r[0] for r in conn.execute("SELECT folder_name FROM tcg_master").fetchall()]
if os.path.exists(tcg_core.CARD_DATABASE_ROOT):
    all_f = sorted([d for d in os.listdir(tcg_core.CARD_DATABASE_ROOT) if os.path.isdir(os.path.join(
        tcg_core.CARD_DATABASE_ROOT, d))])
    final_f = all_f if mode == '2' else [f for f in all_f if f not in reg]
    if final_f:
        root = tk.Tk()
        tcg_core.TCGGuiWizard(root, final_f, mgr)
        root.mainloop()
tcg_core.wait_for_user()
