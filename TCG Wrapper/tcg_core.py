import os
import sys
import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageTk
from datetime import datetime
import time
from pynput import keyboard

# Make config/db importable from Utilities/ (tcg_core.py lives in TCG Wrapper/)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Utilities"))
import config
import db

IS_WINDOWS = os.name == 'nt'

if IS_WINDOWS:
    import msvcrt
    DRIVE_SOURCE = r"G:\My Drive\New Cards"
    SKIPPED_ROOT_DIR = r"G:\My Drive\Skipped Cards"
    CARD_DATABASE_ROOT = r"G:\My Drive\Card Database"
    CLEAR_SCREEN = 'cls'
else:
    DRIVE_SOURCE = os.path.expanduser("~/Desktop/GDrive/New Cards")
    SKIPPED_ROOT_DIR = os.path.expanduser("~/Desktop/GDrive/Skipped Cards")
    CARD_DATABASE_ROOT = os.path.expanduser("~/Desktop/GDrive/Card Database")
    CLEAR_SCREEN = 'clear'


class Color:
    PURPLE = '\033[95m'; CYAN = '\033[96m'; GREEN = '\033[92m'
    YELLOW = '\033[93m'; RED = '\033[91m'; BOLD = '\033[1m'; END = '\033[0m'
    DG = '\033[2m\033[92m'


def clear_buffers():
    if IS_WINDOWS:
        while msvcrt.kbhit():
            msvcrt.getch()
    else:
        try:
            import termios
            termios.tcflush(sys.stdin, termios.TCIOFLUSH)
        except (ImportError, Exception):
            pass


def wait_for_user():
    print(f"\n{Color.YELLOW}>>> Press ANY KEY to return to menu... {Color.END}")
    clear_buffers()
    def on_press(key): return False
    with keyboard.Listener(on_press=on_press) as listener:
        listener.join()
    time.sleep(0.1)
    clear_buffers()


def _coll(name):
    return db.get_db()[name]


def skipped_coll():
    return _coll(config.SKIPPED_IMAGES_COLLECTION)

def progress_coll():
    return _coll(config.PROGRESS_COLLECTION)

def tcg_master_coll():
    return _coll(config.TCG_MASTER_COLLECTION)


class CardDBManager:
    def __init__(self, db_path=None):
        self._ensure_tables()

    def _ensure_tables(self):
        # Create indexes to mirror the old PRIMARY KEYs
        skipped_coll().create_index([("image_name", 1), ("game_name", 1), ("language", 1)], unique=True)
        progress_coll().create_index([("image_name", 1), ("game_name", 1), ("language", 1)], unique=True)
        tcg_master_coll().create_index([("tcg_display_name", 1), ("language", 1)], unique=True)

    def show_table_summary(self):
        os.system(CLEAR_SCREEN)
        print(f"\n{Color.CYAN}{'═' * 45}{Color.END}\n{Color.BOLD}         DATABASE TABLE SUMMARY{Color.END}\n{Color.CYAN}{'═' * 45}{Color.END}")
        tables = [
            (config.SKIPPED_IMAGES_COLLECTION, skipped_coll().count_documents({})),
            (config.PROGRESS_COLLECTION, progress_coll().count_documents({})),
            (config.TCG_MASTER_COLLECTION, tcg_master_coll().count_documents({})),
        ]
        print(f" {'TABLE NAME':<25} | {'RECORDS':<10}\n" + "-" * 45)
        for name, count in tables:
            print(f" {name:<25} | {count:,}")
        wait_for_user()

    def smart_inspect(self):
        os.system(CLEAR_SCREEN)
        print(f"{Color.PURPLE}--- DEEP INSPECTION INDEX ---{Color.END}")
        tables = [
            (config.TCG_MASTER_COLLECTION, tcg_master_coll().count_documents({})),
            (config.SKIPPED_IMAGES_COLLECTION, skipped_coll().count_documents({})),
            (config.PROGRESS_COLLECTION, progress_coll().count_documents({})),
        ]
        for i, (name, count) in enumerate(tables, 1):
            print(f" {i:2}. {Color.BOLD}{name:<20}{Color.END} ({count:,} records)")
        idx = input(f"\nSelect Table # for Deep View: ")
        if not idx.isdigit() or not (0 < int(idx) <= len(tables)): return
        target = tables[int(idx) - 1][0]
        os.system(CLEAR_SCREEN)
        if target == config.TCG_MASTER_COLLECTION:
            print(f"{Color.CYAN}--- FULL REGISTRY VIEW: {target.upper()} ---{Color.END}\n")
            rows = list(tcg_master_coll().find({}).sort("tcg_display_name", 1))
            print(f" {'NAME':<25} | {'LANG':<8} | {'ID':<8} | {'PGS':<4} | {'PATH'}\n" + "-" * 90)
            for r in rows:
                print(f" {r.get('tcg_display_name',''):<25} | {r.get('language',''):<8} | {str(r.get('site_id','')):<8} | {str(r.get('total_pages','')):<4} | {r.get('folder_name','')}")
        else:
            print(f"{Color.CYAN}--- DATA SNAPSHOT: {target.upper()} ---{Color.END}")
            cursor = _coll(target).find({})
            f5 = list(cursor.limit(5))
            total = _coll(target).count_documents({})
            l5 = list(_coll(target).find({}).skip(max(total - 5, 0)).limit(5)) if total > 5 else f5
            if f5:
                keys = [k for k in f5[0] if k != "_id"]
                print(f"\n{Color.GREEN}[ FIRST 5 ]{Color.END}\n {Color.BOLD}{' | '.join(keys)}{Color.END}")
                for r in f5: print(f" {' | '.join(str(r.get(k, '')) for k in keys)}")
                print(f"\n{Color.RED}[ LAST 5 ]{Color.END}")
                for r in reversed(l5): print(f" {' | '.join(str(r.get(k, '')) for k in keys)}")
            else:
                print("\nTable is empty.")
        wait_for_user()

    def run_duplicate_audit(self):
        os.system(CLEAR_SCREEN)
        print(f"{Color.CYAN}{'═' * 45}\n  STARTING DUPLICATE AUDIT\n{'═' * 45}{Color.END}")
        print(f"[1/3] Reading database history...")
        processed_keys = set()
        for r in progress_coll().find({}, {"image_name": 1, "game_name": 1, "language": 1}):
            processed_keys.add((r["image_name"].lower(), r["game_name"].lower(), r["language"].lower()))
        print(f"      - Found {len(processed_keys):,} processed records.")
        print(f"[2/3] Scanning Card Database for physical files...")
        existing_on_disk = set()
        if os.path.exists(CARD_DATABASE_ROOT):
            for root, dirs, files in os.walk(CARD_DATABASE_ROOT):
                game_name = os.path.basename(root).lower()
                for f in files:
                    if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                        name_only = os.path.splitext(f)[0].lower()
                        lang = "english" if "_200w" in name_only else "japanese"
                        clean_id = name_only.replace("_200w", "")
                        existing_on_disk.add((clean_id, game_name, lang))
        print(f"      - Found {len(existing_on_disk):,} files in library.")
        print(f"[3/3] Auditing 'New Cards' for duplicates...\n")
        deleted_count = 0
        if os.path.exists(DRIVE_SOURCE):
            for root, dirs, files in os.walk(DRIVE_SOURCE):
                game_name = os.path.basename(root).lower()
                for f in files:
                    if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                        name_only = os.path.splitext(f)[0].lower()
                        lang = "english" if "_200w" in name_only else "japanese"
                        clean_id = name_only.replace("_200w", "")
                        file_key = (clean_id, game_name, lang)
                        if file_key in processed_keys or file_key in existing_on_disk:
                            try:
                                full_path = os.path.join(root, f)
                                reason = "Database" if file_key in processed_keys else "Physical Library"
                                print(f"  {Color.RED}[DELETE]{Color.END} {game_name}/{f} (Match: {reason})")
                                os.remove(full_path)
                                deleted_count += 1
                            except Exception as e:
                                print(f"  {Color.YELLOW}[ERROR]{Color.END} Failed to delete {f}: {e}")
        print(f"\n{Color.GREEN}{'═' * 45}\n  AUDIT COMPLETE\n{'═' * 45}{Color.END}")
        print(f"  Total Duplicates Purged: {deleted_count}")
        wait_for_user()

    def run_matrix_sync_audit(self):
        os.system(CLEAR_SCREEN)
        if not os.path.exists(CARD_DATABASE_ROOT):
            print(f"{Color.RED}[!] ERROR: Path not found: {CARD_DATABASE_ROOT}{Color.END}")
            return
        folders = sorted([d for d in os.listdir(CARD_DATABASE_ROOT) if os.path.isdir(os.path.join(CARD_DATABASE_ROOT, d))])
        print(f"\n{Color.CYAN}--- TCG SECTOR SELECTOR (SYNC PHYSICAL -> DB) ---{Color.END}")
        print(f"0) [SCAN ALL FOLDERS]")
        for i, fld in enumerate(folders, 1): print(f"{Color.GREEN}{i}) {fld}{Color.END}")
        choice = input(f"\n{Color.YELLOW}Select Sector (Number): {Color.END}").strip()
        targets = folders if choice == "0" else [folders[int(choice) - 1]] if (choice.isdigit() and 0 < int(choice) <= len(folders)) else None
        if targets is None: return
        print(f"{Color.DG}Loading Database Matrices...{Color.END}")
        progress_set = {(r["image_name"].lower(), r["game_name"].lower(), r["language"].lower())
                        for r in progress_coll().find({}, {"image_name": 1, "game_name": 1, "language": 1})}
        skipped_set = {(r["image_name"].lower(), r["game_name"].lower(), r["language"].lower())
                       for r in skipped_coll().find({}, {"image_name": 1, "game_name": 1, "language": 1})}
        total_count = 0
        buffer = []
        for tcg_folder in targets:
            current_path = os.path.join(CARD_DATABASE_ROOT, tcg_folder)
            print(f"\n{Color.CYAN}>>> INITIATING STREAM: {Color.GREEN}{tcg_folder}{Color.END}")
            for root, _, files in os.walk(current_path):
                for f in files:
                    if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                        total_count += 1
                        name_only = os.path.splitext(f)[0]
                        lang = "english" if "_200w" in name_only else "japanese"
                        clean_id = name_only.replace("_200w", "")
                        card_key = (clean_id.lower(), tcg_folder.lower(), lang.lower())
                        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                        prefix = f"{Color.YELLOW}[{ts}] {Color.CYAN}#{total_count:<7}{Color.END}"
                        if card_key in progress_set:
                            print(f"{prefix}{Color.GREEN} [MATCH]   | {tcg_folder[:15]:<15} | {clean_id[:25]:<25}{Color.END}")
                        elif card_key in skipped_set:
                            print(f"{prefix}{Color.DG} [SKIPPED] | {tcg_folder[:15]:<15} | {clean_id[:25]:<25}{Color.END}")
                        else:
                            print(f"{prefix}{Color.BOLD}{Color.PURPLE} [NEW]     | {tcg_folder[:15]:<15} | {clean_id[:25]:<25}{Color.END}")
                            buffer.append({
                                "image_name": clean_id, "game_name": tcg_folder, "language": lang,
                                "status": "yes", "processed_at": datetime.now().strftime("%Y-%m-%d %H:%M")
                            })
                            progress_set.add(card_key)
                            if len(buffer) >= 50:
                                _flush_progress(buffer)
                                buffer = []
        if buffer:
            _flush_progress(buffer)
        print(f"\n{Color.GREEN}--- SYNC COMPLETE: {total_count:,} ITEMS ACCOUNTED FOR ---{Color.END}")
        wait_for_user()


def _flush_progress(buffer):
    for doc in buffer:
        progress_coll().update_one(
            {"image_name": doc["image_name"], "game_name": doc["game_name"], "language": doc["language"]},
            {"$set": doc}, upsert=True)


class TCGGuiWizard:
    def __init__(self, root, folder_list, db_manager):
        self.root = root
        self.root.title("TCG Discovery Wizard")
        self.root.geometry("800x950")
        self.root.configure(bg="#1a1a1a")
        self.folder_list = folder_list
        self.db_mgr = db_manager
        self.current_idx = 0
        font_main = ("Helvetica", 16, "bold") if not IS_WINDOWS else ("Segoe UI", 16, "bold")
        self.label_folder = tk.Label(root, text="", font=font_main, fg="#00ffcc", bg="#1a1a1a")
        self.label_folder.pack(pady=15)
        self.canvas = tk.Canvas(root, width=500, height=650, bg="#111", highlightthickness=1)
        self.canvas.pack(pady=10)
        tk.Label(root, text="Site ID (Category ID):", fg="white", bg="#1a1a1a").pack()
        self.entry_sid = tk.Entry(root, width=20, bg="#333", fg="white", insertbackground="white")
        self.entry_sid.pack(pady=5)
        tk.Label(root, text="Total Pages (Japan Only):", fg="white", bg="#1a1a1a").pack()
        self.entry_pages = tk.Entry(root, width=20, bg="#333", fg="white", insertbackground="white")
        self.entry_pages.insert(0, "0")
        self.entry_pages.pack(pady=5)
        btn_frame = tk.Frame(root, bg="#1a1a1a")
        btn_frame.pack(pady=20)
        tk.Button(btn_frame, text="JAPANESE", bg="#c0392b", fg="white", width=15, height=2,
                  command=lambda: self.save("japanese")).grid(row=0, column=0, padx=5)
        tk.Button(btn_frame, text="ENGLISH", bg="#27ae60", fg="white", width=15, height=2,
                  command=lambda: self.save("english")).grid(row=0, column=1, padx=5)
        tk.Button(btn_frame, text="BOTH", bg="#2980b9", fg="white", width=15, height=2,
                  command=lambda: self.save("both")).grid(row=0, column=2, padx=5)
        self.load_folder()

    def load_folder(self):
        if self.current_idx >= len(self.folder_list):
            messagebox.showinfo("Complete", "Discovery Complete!")
            self.root.destroy()
            return
        folder = self.folder_list[self.current_idx]
        self.label_folder.config(text=f"Mapping Folder: {folder}")
        path = os.path.join(CARD_DATABASE_ROOT, folder)
        if os.path.exists(path):
            files = [f for f in os.listdir(path) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
            if files:
                img_path = os.path.join(path, files[0])
                img = Image.open(img_path).resize((500, 650))
                self.photo = ImageTk.PhotoImage(img)
                self.canvas.create_image(250, 325, image=self.photo)
        self.current_idx += 1

    def save(self, mode):
        folder = self.folder_list[self.current_idx - 1]
        clean_name = folder.replace(" Japan", "").replace(" English", "").replace(" Japanese", "").strip()
        sid = self.entry_sid.get().strip() or 0
        pgs = self.entry_pages.get().strip() or 0
        if mode in ["japanese", "both"]:
            tcg_master_coll().update_one(
                {"tcg_display_name": clean_name, "language": "japanese"},
                {"$set": {"site_id": sid, "total_pages": pgs, "folder_name": folder, "last_run": "Never"}},
                upsert=True)
        if mode in ["english", "both"]:
            tcg_master_coll().update_one(
                {"tcg_display_name": clean_name, "language": "english"},
                {"$set": {"site_id": sid, "total_pages": 0, "folder_name": folder, "last_run": "Never"}},
                upsert=True)
        self.entry_sid.delete(0, tk.END)
        self.entry_pages.delete(0, tk.END)
        self.entry_pages.insert(0, "0")
        self.load_folder()
