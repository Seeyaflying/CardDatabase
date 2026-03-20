import os
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
from datetime import datetime
import time
import msvcrt
import sys
from pynput import keyboard

# ==============================================================
# CONFIGURATION
# ==============================================================
SKIPPED_ROOT_DIR = r"G:\My Drive\Skipped Cards"
CARD_DATABASE_ROOT = r"G:\My Drive\Card Database"
DB_FILE = "skipped_images.sqlite"


class Color:
    PURPLE = '\033[95m';
    CYAN = '\033[96m';
    GREEN = '\033[92m'
    YELLOW = '\033[93m';
    RED = '\033[91m';
    BOLD = '\033[1m';
    END = '\033[0m'


# ==============================================================
# THE STABILIZER (No more double menus)
# ==============================================================
def clear_buffers():
    """Vaccum out any leftover keypresses from the terminal buffer."""
    while msvcrt.kbhit():
        msvcrt.getch()


def wait_for_user():
    """Flushes ghost inputs and waits for a fresh hardware-level keypress."""
    print(f"\n{Color.YELLOW}>>> Press ANY KEY to return to menu... {Color.END}")
    clear_buffers()  # Flush before waiting

    def on_press(key): return False

    with keyboard.Listener(on_press=on_press) as listener:
        listener.join()

    time.sleep(0.1)
    clear_buffers()  # Flush after waiting


# ==============================================================
# UNIFIED GUI WIZARD (OPTION 4)
# ==============================================================
class TCGGuiWizard:
    def __init__(self, root, folder_list, db_manager):
        self.root = root
        self.root.title("TCG Discovery Wizard")
        self.root.geometry("800x950")
        self.root.configure(bg="#1a1a1a")
        self.folder_list = folder_list
        self.db_mgr = db_manager
        self.current_idx = 0

        self.label_folder = tk.Label(root, text="", font=("Segoe UI", 16, "bold"), fg="#00ffcc", bg="#1a1a1a")
        self.label_folder.pack(pady=15)
        self.canvas = tk.Canvas(root, width=500, height=650, bg="#111", highlightthickness=1)
        self.canvas.pack(pady=10)

        tk.Label(root, text="Site ID (Category ID):", fg="white", bg="#1a1a1a").pack()
        self.entry_sid = tk.Entry(root, width=20, font=("Segoe UI", 11), bg="#333", fg="white",
                                  insertbackground="white")
        self.entry_sid.pack(pady=5)

        tk.Label(root, text="Total Pages (Japan Only):", fg="white", bg="#1a1a1a").pack()
        self.entry_pages = tk.Entry(root, width=20, font=("Segoe UI", 11), bg="#333", fg="white",
                                    insertbackground="white")
        self.entry_pages.insert(0, "0")
        self.entry_pages.pack(pady=5)

        btn_frame = tk.Frame(root, bg="#1a1a1a")
        btn_frame.pack(pady=20)

        tk.Button(btn_frame, text="JAPANESE", bg="#c0392b", fg="white", width=15, height=2, font=("bold"),
                  command=lambda: self.save("japanese")).grid(row=0, column=0, padx=5)
        tk.Button(btn_frame, text="ENGLISH", bg="#27ae60", fg="white", width=15, height=2, font=("bold"),
                  command=lambda: self.save("english")).grid(row=0, column=1, padx=5)
        tk.Button(btn_frame, text="BOTH", bg="#2980b9", fg="white", width=15, height=2, font=("bold"),
                  command=lambda: self.save("both")).grid(row=0, column=2, padx=5)

        self.load_folder()

    def load_folder(self):
        if self.current_idx >= len(self.folder_list):
            messagebox.showinfo("Complete", "Discovery Complete!");
            self.root.destroy();
            return
        folder = self.folder_list[self.current_idx]
        self.label_folder.config(text=f"📁 Mapping Folder: {folder}")
        path = os.path.join(CARD_DATABASE_ROOT, folder)
        files = [f for f in os.listdir(path) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
        if files:
            img = Image.open(os.path.join(path, files[0])).resize((500, 650))
            self.photo = ImageTk.PhotoImage(img)
            self.canvas.create_image(250, 325, image=self.photo)
        self.current_idx += 1

    def save(self, mode):
        folder = self.folder_list[self.current_idx - 1]
        clean_name = folder.replace(" Japan", "").replace(" English", "").replace(" Japanese", "").strip()
        sid = self.entry_sid.get().strip() or 0
        pgs = self.entry_pages.get().strip() or 0

        with self.db_mgr.get_conn() as conn:
            if mode in ["japanese", "both"]:
                conn.execute(
                    "INSERT OR REPLACE INTO tcg_master (tcg_display_name, language, site_id, total_pages, folder_name, last_run) VALUES (?, 'japanese', ?, ?, ?, 'Never')",
                    (clean_name, sid, pgs, folder))
            if mode in ["english", "both"]:
                conn.execute(
                    "INSERT OR REPLACE INTO tcg_master (tcg_display_name, language, site_id, total_pages, folder_name, last_run) VALUES (?, 'english', ?, 0, ?, 'Never')",
                    (clean_name, sid, folder))
            conn.commit()
        self.entry_sid.delete(0, tk.END);
        self.entry_pages.delete(0, tk.END);
        self.entry_pages.insert(0, "0")
        self.load_folder()


# ==============================================================
# DATABASE MANAGER
# ==============================================================
class CardDBManager:
    def __init__(self, db_path=DB_FILE):
        self.db_path = db_path
        self._ensure_tables()

    def get_conn(self):
        conn = sqlite3.connect(self.db_path);
        conn.row_factory = sqlite3.Row;
        return conn

    def _ensure_tables(self):
        with self.get_conn() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS skipped_images (image_name TEXT, game_name TEXT, language TEXT, added_at TEXT, PRIMARY KEY (image_name, game_name, language))")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS progress (image_name TEXT, game_name TEXT, language TEXT, status TEXT, processed_at TEXT, PRIMARY KEY(image_name, game_name, language))")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS tcg_master (tcg_display_name TEXT, language TEXT, site_id INTEGER, total_pages INTEGER, folder_name TEXT, last_run TEXT, PRIMARY KEY (tcg_display_name, language))")
            conn.commit()

    def show_table_summary(self):
        os.system('cls');
        print(
            f"\n{Color.CYAN}{'═' * 45}{Color.END}\n{Color.BOLD}         DATABASE TABLE SUMMARY{Color.END}\n{Color.CYAN}{'═' * 45}{Color.END}")
        with self.get_conn() as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
            print(f" {'TABLE NAME':<25} | {'RECORDS':<10}\n" + "-" * 45)
            for t in tables:
                count = conn.execute(f"SELECT COUNT(*) FROM {t['name']}").fetchone()[0]
                print(f" {t['name']:<25} | {count:,}")
        wait_for_user()

    def smart_inspect(self):
        os.system('cls');
        print(f"{Color.PURPLE}--- DEEP INSPECTION INDEX ---{Color.END}")
        with self.get_conn() as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
            for i, t in enumerate(tables, 1):
                count = conn.execute(f"SELECT COUNT(*) FROM {t['name']}").fetchone()[0]
                print(f" {i:2}. {Color.BOLD}{t['name']:<20}{Color.END} ({count:,} records)")
            idx = input(f"\nSelect Table # for Deep View: ");
            if not idx.isdigit() or not (0 < int(idx) <= len(tables)): return
            target = tables[int(idx) - 1]['name'];
            os.system('cls')
            if target == 'tcg_master':
                print(f"{Color.CYAN}--- FULL REGISTRY VIEW: {target.upper()} ---{Color.END}\n")
                rows = conn.execute("SELECT * FROM tcg_master ORDER BY tcg_display_name ASC").fetchall()
                print(f" {'NAME':<25} | {'LANG':<8} | {'ID':<8} | {'PGS':<4} | {'PATH'}\n" + "-" * 90)
                for r in rows: print(
                    f" {r['tcg_display_name']:<25} | {r['language']:<8} | {str(r['site_id']):<8} | {str(r['total_pages']):<4} | {r['folder_name']}")
            else:
                print(f"{Color.CYAN}--- DATA SNAPSHOT: {target.upper()} ---{Color.END}")
                f5 = conn.execute(f"SELECT * FROM {target} LIMIT 5").fetchall()
                l5 = conn.execute(
                    f"SELECT * FROM {target} WHERE rowid IN (SELECT rowid FROM {target} ORDER BY rowid DESC LIMIT 5)").fetchall()
                if f5:
                    print(f"\n{Color.GREEN}[ FIRST 5 ]{Color.END}\n {Color.BOLD}{' | '.join(f5[0].keys())}{Color.END}")
                    for r in f5: print(f" {' | '.join(str(v) for v in r)}")
                    print(f"\n{Color.RED}[ LAST 5 ]{Color.END}")
                    for r in reversed(l5): print(f" {' | '.join(str(v) for v in r)}")
                else:
                    print("\nTable is empty.")
        wait_for_user()


# ==============================================================
# MAIN PROGRAM LOOP
# ==============================================================
def main():
    mgr = CardDBManager()
    while True:
        # Pre-Menu Buffer Flush
        clear_buffers()

        os.system('cls');
        print(f"{Color.CYAN}{'═' * 45}\n  GLOBAL TCG DATABASE MANAGER\n{'═' * 45}{Color.END}")
        print(" 1. 📊 VIEW TABLE SUMMARY")
        print(" 2. 🔍 SEARCH BANNED LIST")
        print(" 3. 📥 IMPORT FROM SKIPPED CARDS")
        print(f" 4. {Color.YELLOW}📂 DISCOVERY WIZARD (AUTO-SCAN){Color.END}")
        print(" 5. 🔎 DEEP TABLE INSPECTION")
        print(" 6. 🔄 RENAME TCG / SWAP LANG")
        print(" 7. 🗑️  DELETE TABLES")
        print(" 8. ❌ EXIT")

        cmd = input(f"\nSelect Option (1-8) > ").strip()

        if cmd == '1':
            mgr.show_table_summary()
        elif cmd == '2':
            os.system('cls');
            sid = input("Search ID: ")
            with mgr.get_conn() as conn:
                res = conn.execute("SELECT * FROM skipped_images WHERE image_name LIKE ?", (f"%{sid}%",)).fetchall()
                for r in res: print(f"-> {r['image_name']} | {r['game_name']} | {r['language']}")
            wait_for_user()
        elif cmd == '3':
            os.system('cls');
            print(f"{Color.BLUE}--- SKIPPED IMPORT ---{Color.END}")
            with mgr.get_conn() as conn:
                configs = conn.execute("SELECT * FROM tcg_master ORDER BY tcg_display_name ASC").fetchall()
            for i, c in enumerate(configs, 1): print(f" {i:2}. {c['tcg_display_name']} [{c['language']}]")
            choice = input(f"\nSelect #: ");
            if choice.isdigit() and 0 < int(choice) <= len(configs):
                cfg = configs[int(choice) - 1];
                target = os.path.join(SKIPPED_ROOT_DIR, cfg['folder_name'])
                if os.path.exists(target):
                    files = [f for f in os.listdir(target) if f.lower().endswith(('.png', '.jpg'))]
                    with mgr.get_conn() as conn:
                        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
                        for f in files:
                            iid = os.path.splitext(f)[0]
                            conn.execute("INSERT OR IGNORE INTO skipped_images VALUES (?, ?, ?, ?)",
                                         (iid, cfg['tcg_display_name'], cfg['language'], ts))
                            conn.execute("INSERT OR IGNORE INTO progress VALUES (?, ?, ?, 'rejected', ?)",
                                         (iid, cfg['tcg_display_name'], cfg['language'], ts))
                    print(f"✅ Imported {len(files)} items.");
                    time.sleep(1)
            wait_for_user()
        elif cmd == '4':
            os.system('cls');
            mode = input("1. New | 2. All: ")
            with mgr.get_conn() as conn:
                reg = [r[0] for r in conn.execute("SELECT folder_name FROM tcg_master").fetchall()]
            all_f = sorted(
                [d for d in os.listdir(CARD_DATABASE_ROOT) if os.path.isdir(os.path.join(CARD_DATABASE_ROOT, d))])
            final_f = all_f if mode == '2' else [f for f in all_f if f not in reg]
            if final_f: root = tk.Tk(); TCGGuiWizard(root, final_f, mgr); root.mainloop()
        elif cmd == '5':
            mgr.smart_inspect()
        elif cmd == '6':
            os.system('cls');
            old = input("Current Name: ");
            new = input("New Name: ")
            with mgr.get_conn() as conn:
                conn.execute("UPDATE tcg_master SET tcg_display_name=? WHERE tcg_display_name=?", (new, old))
                conn.execute("UPDATE skipped_images SET game_name=? WHERE game_name=?", (new, old))
                conn.execute("UPDATE progress SET game_name=? WHERE game_name=?", (new, old))
                conn.commit();
                print("✅ Updated.");
                time.sleep(1.5)
        elif cmd == '7':
            os.system('cls');
            with mgr.get_conn() as conn:
                tables = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
                for i, t in enumerate(tables, 1): print(f"{i}. {t['name']}")
                idx = input("\nDelete Table #: ")
                if idx.isdigit() and 0 < int(idx) <= len(tables):
                    target = tables[int(idx) - 1]['name']
                    if input(f"Type 'DELETE' to confirm: ") == "DELETE":
                        conn.execute(f"DROP TABLE {target}");
                        print("✅ Deleted.");
                        time.sleep(1)
        elif cmd == '8':
            break


if __name__ == "__main__":
    main()