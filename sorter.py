import os
import sys
import tkinter as tk
from tkinter import filedialog
from PIL import Image, ImageTk
import random
import sqlite3
import threading
from datetime import datetime
import shutil
import tkinter.ttk as ttk

# ==========================
# Performance knobs
# ==========================
MAX_SESSION_IMAGES = 3000  # hard cap per run
IMAGE_BATCH_SIZE = 100  # preload/queue batch size (<= MAX_SESSION_IMAGES)

DISPLAY_W = 460
DISPLAY_H = 680
RESAMPLE = Image.BILINEAR  # faster than LANCZOS; change back if you prefer quality

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")

# ==========================
# Database Setup
# ==========================
if getattr(sys, "frozen", False):
    exe_folder = os.path.dirname(sys.executable)
    main_folder = exe_folder  # DB next to the exe (writable)
else:
    main_folder = os.path.dirname(os.path.abspath(__file__))

DB_FILE = os.path.join(main_folder, "skipped_images.sqlite")

conn_main = sqlite3.connect(DB_FILE, check_same_thread=False)
cursor_main = conn_main.cursor()

cursor_main.execute(
    """
    CREATE TABLE IF NOT EXISTS settings
    (
        key TEXT PRIMARY KEY,
        value TEXT
    )
"""
)

cursor_main.execute(
    """
    CREATE TABLE IF NOT EXISTS progress
    (
        img_path TEXT PRIMARY KEY,
        processed_at TEXT,
        status TEXT
    )
"""
)
conn_main.commit()

# ==========================
# Helper Functions (settings/progress)
# ==========================
def save_progress_setting(key, value):
    cursor_main.execute(
        """
        INSERT INTO settings (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, str(value)),
    )
    conn_main.commit()


def load_setting(key, default=None):
    cursor_main.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = cursor_main.fetchone()
    return row[0] if row else default


def mark_processed(img_path, status="yes"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor_main.execute(
        """
        INSERT OR REPLACE INTO progress (img_path, processed_at, status)
        VALUES (?, ?, ?)
        """,
        (img_path, timestamp, status),
    )
    conn_main.commit()


def unmark_processed(img_path):
    cursor_main.execute("DELETE FROM progress WHERE img_path=?", (img_path,))
    conn_main.commit()


def is_processed(img_path):
    cursor_main.execute("SELECT 1 FROM progress WHERE img_path=?", (img_path,))
    return cursor_main.fetchone() is not None


# ==========================
# Local Cache / Drive Sync helpers
# ==========================
def _is_image_file(name: str) -> bool:
    return name.lower().endswith(IMAGE_EXTS)


def _iter_images(root_folder: str):
    for root_dir, _, files in os.walk(root_folder):
        for f in files:
            if _is_image_file(f):
                yield os.path.join(root_dir, f)


def _compute_cache_paths(cache_root: str):
    inbox = os.path.join(cache_root, "inbox")
    yes = os.path.join(cache_root, "yes")
    no = os.path.join(cache_root, "no")
    return inbox, yes, no


def _safe_copy2(src: str, dst: str):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)


def _safe_remove(path: str):
    try:
        os.remove(path)
    except FileNotFoundError:
        return
    except Exception as e:
        print(f"Error deleting {path}: {e}")


def _safe_rmdir_empty_parents(start_dir: str, stop_dir: str):
    """
    Remove empty directories from start_dir upwards until stop_dir (exclusive).
    Never removes stop_dir itself.
    """
    try:
        stop_dir = os.path.abspath(stop_dir)
        cur = os.path.abspath(start_dir)

        while True:
            if cur == stop_dir:
                break
            if not os.path.isdir(cur):
                break
            if os.listdir(cur):
                break
            os.rmdir(cur)
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
    except Exception as e:
        print(f"Error pruning empty dirs from {start_dir}: {e}")


def sync_down_to_local(max_count: int, progress_cb=None) -> int:
    """
    Copy up to max_count images from Drive Source -> local inbox (preserve relpaths).
    progress_cb(copied, max_count) is called as files are copied.
    Runs in a worker thread.
    """
    if not drive_source_folder or not local_cache_root:
        return 0

    local_inbox, _, _ = _compute_cache_paths(local_cache_root)
    os.makedirs(local_inbox, exist_ok=True)

    copied = 0
    if progress_cb:
        progress_cb(copied, max_count)

    for src in _iter_images(drive_source_folder):
        rel = os.path.relpath(src, drive_source_folder)
        dst = os.path.join(local_inbox, rel)
        if os.path.exists(dst):
            continue

        _safe_copy2(src, dst)
        copied += 1

        if progress_cb:
            progress_cb(copied, max_count)

        if copied >= max_count:
            break

    return copied


def sync_up_to_drive_and_delete_originals():
    """
    Upload local yes/no -> Drive yes/no, then delete originals from Drive source.
    Cache mode expects YES and NO preserve relpaths.
    Runs in a worker thread.
    """
    if not (drive_source_folder and drive_yes_folder and drive_no_folder and local_cache_root):
        return

    _, local_yes, local_no = _compute_cache_paths(local_cache_root)

    # 1) Upload YES
    for src in _iter_images(local_yes):
        rel = os.path.relpath(src, local_yes)
        dst = os.path.join(drive_yes_folder, rel)
        _safe_copy2(src, dst)

    # 2) Upload NO
    for src in _iter_images(local_no):
        rel = os.path.relpath(src, local_no)
        dst = os.path.join(drive_no_folder, rel)
        _safe_copy2(src, dst)

    # 3) Delete originals from Drive Source based on relpaths present in YES/NO
    def delete_originals_from(local_folder: str):
        for processed_local in _iter_images(local_folder):
            rel = os.path.relpath(processed_local, local_folder)
            original = os.path.join(drive_source_folder, rel)
            _safe_remove(original)

    delete_originals_from(local_yes)
    delete_originals_from(local_no)


def sync_up_to_drive_delete_originals_and_cleanup_local():
    """
    "Sync Up + Cleanup" variant:
    - copy local yes/no -> Drive yes/no
    - verify destination exists + same file size
    - delete original from Drive Source
    - verify original is gone
    - delete the local processed file (cleanup) + prune empty directories
    """
    if not (drive_source_folder and drive_yes_folder and drive_no_folder and local_cache_root):
        return

    _, local_yes, local_no = _compute_cache_paths(local_cache_root)

    def _verify_same_size(a: str, b: str) -> bool:
        try:
            return os.path.getsize(a) == os.path.getsize(b)
        except OSError:
            return False

    def _sync_one_tree(local_folder: str, drive_dest_root: str, label_name: str):
        # Snapshot list so we can show an accurate "i/N" counter
        items = list(_iter_images(local_folder))
        total = len(items)

        uploaded = 0
        deleted_source = 0
        deleted_local = 0
        failed = 0

        print(f"\n=== Sync Up + Cleanup ({label_name}) ===")
        print(f"Items: {total}")
        print(f"Local: {local_folder}")
        print(f"Drive Dest: {drive_dest_root}")
        print(f"Drive Source: {drive_source_folder}\n")

        for i, local_src in enumerate(items, start=1):
            rel = os.path.relpath(local_src, local_folder)
            drive_dst = os.path.join(drive_dest_root, rel)
            drive_original = os.path.join(drive_source_folder, rel)

            prefix = f"[{label_name} {i}/{total}]"

            try:
                # 1) Upload (copy) to Drive Yes/No
                print(f"{prefix} UPLOAD {rel}")
                _safe_copy2(local_src, drive_dst)

                # 2) Confirm upload
                if not os.path.exists(drive_dst):
                    raise RuntimeError(f"Upload verification failed (missing dest): {drive_dst}")
                if not _verify_same_size(local_src, drive_dst):
                    raise RuntimeError(f"Upload verification failed (size mismatch): {drive_dst}")
                uploaded += 1
                print(f"{prefix}   -> OK uploaded")

                # 3) Delete original from Drive Source
                print(f"{prefix} DELETE SOURCE {rel}")
                _safe_remove(drive_original)

                # 4) Confirm original delete
                if os.path.exists(drive_original):
                    raise RuntimeError(f"Original delete verification failed: {drive_original}")
                deleted_source += 1
                print(f"{prefix}   -> OK deleted source")

                # 5) Cleanup local processed file (now safe)
                print(f"{prefix} DELETE LOCAL {rel}")
                _safe_remove(local_src)
                if os.path.exists(local_src):
                    raise RuntimeError(f"Local cleanup verification failed: {local_src}")
                deleted_local += 1
                print(f"{prefix}   -> OK deleted local")

                _safe_rmdir_empty_parents(os.path.dirname(local_src), stop_dir=local_folder)

            except Exception as e:
                failed += 1
                print(f"{prefix} FAILED {rel} :: {e}")

        print(
            f"\n=== Summary ({label_name}) ===\n"
            f"Uploaded: {uploaded}/{total}\n"
            f"Deleted from Drive Source: {deleted_source}/{total}\n"
            f"Deleted local: {deleted_local}/{total}\n"
            f"Failed: {failed}\n"
        )

    _sync_one_tree(local_yes, drive_yes_folder, "YES")
    _sync_one_tree(local_no, drive_no_folder, "NO")

# ==========================
# Tk + load settings
# ==========================
root = tk.Tk()
root.withdraw()

# Cache/sync settings
use_local_cache = load_setting("use_local_cache", "0") == "1"
local_cache_root = load_setting("local_cache_root", "")
drive_source_folder = load_setting("drive_source_folder", "")
drive_yes_folder = load_setting("drive_yes_folder", "")
drive_no_folder = load_setting("drive_no_folder", "")

# Normal-mode folders
source_folder = load_setting("source_folder")
yes_folder = load_setting("yes_folder")
no_folder = load_setting("no_folder")

# If cache mode is enabled, runtime paths point to local cache
if use_local_cache and local_cache_root:
    source_folder, yes_folder, no_folder = _compute_cache_paths(local_cache_root)
    os.makedirs(source_folder, exist_ok=True)
    os.makedirs(yes_folder, exist_ok=True)
    os.makedirs(no_folder, exist_ok=True)

# Keys/mouse bindings
yes_key = load_setting("yes_key", "y")
no_key = load_setting("no_key", "n")
back_key = load_setting("back_key", "b")
yes_mouse = load_setting("yes_mouse", "Button-1")
no_mouse = load_setting("no_mouse", "Button-3")


def ask_for_folders():
    global source_folder, yes_folder, no_folder
    source_folder = filedialog.askdirectory(title="Select Source Folder")
    if not source_folder:
        sys.exit()
    yes_folder = filedialog.askdirectory(title="Select 'Yes' Folder")
    if not yes_folder:
        sys.exit()
    no_folder = filedialog.askdirectory(title="Select 'No' Folder")
    if not no_folder:
        sys.exit()

    save_progress_setting("source_folder", source_folder)
    save_progress_setting("yes_folder", yes_folder)
    save_progress_setting("no_folder", no_folder)


# Validate normal-mode folders if not using cache
if not use_local_cache:
    if not all(
        [
            source_folder,
            yes_folder,
            no_folder,
            os.path.exists(source_folder) if source_folder else False,
            os.path.exists(yes_folder) if yes_folder else False,
            os.path.exists(no_folder) if no_folder else False,
        ]
    ):
        ask_for_folders()

# ==========================
# Global Variables
# ==========================
images_list = []
index = 0
img_tk = None
next_img_tk = None
history_stack = []

ALL_UNPROCESSED_IMAGES = []
BATCH_START_INDEX = 0
SCANNING_FINISHED = False

# Thread-safe-ish next image pipeline:
_next_pil = None
_next_pil_lock = threading.Lock()
_preload_in_progress = False
_next_error_path = None
_next_error_msg = None

# ==========================
# Tkinter UI Setup
# ==========================
root.deiconify()
root.title("Image Reviewer")
root.geometry("480x810")
root.resizable(False, False)

image_label = tk.Label(root)
image_label.pack(padx=10, pady=10)

label = tk.Label(root, text="Scanning folders...")
label.pack(pady=5)

control_bar_frame = tk.Frame(root)
control_bar_frame.pack(side="bottom", fill="x", pady=10)

button_frame = tk.Frame(control_bar_frame)
button_frame.pack(pady=5)

controls_text = f"Yes: {yes_key} / {yes_mouse} | No: {no_key} / {no_mouse} | Back: {back_key}"
controls_label = tk.Label(control_bar_frame, text=controls_text, font=("Helvetica", 9))
controls_label.pack(pady=5)

sync_bar = tk.Frame(control_bar_frame)
sync_bar.pack(pady=5)

# Progress bar for Sync Down / Sync Up
progress_frame = tk.Frame(control_bar_frame)
progress_frame.pack(fill="x", padx=10, pady=5)

progress_bar = ttk.Progressbar(progress_frame, mode="determinate")
progress_bar.pack(fill="x")
progress_bar.pack_forget()  # hidden by default

progress_text = tk.Label(progress_frame, text="")
progress_text.pack()
progress_text.pack_forget()  # hidden by default

# ==========================
# UI busy helper
# ==========================
def _set_ui_busy(is_busy: bool, msg: str | None = None):
    state = "disabled" if is_busy else "normal"
    yes_button.config(state=state)
    no_button.config(state=state)
    back_button.config(state=state)
    settings_btn.config(state=state)

    sync_down_btn.config(state=("normal" if (not is_busy and use_local_cache) else "disabled"))
    sync_up_btn.config(state=("normal" if (not is_busy and use_local_cache) else "disabled"))
    sync_up_cleanup_btn.config(state=("normal" if (not is_busy and use_local_cache) else "disabled"))

    if msg is not None:
        label.config(text=msg)


# ==========================
# Move / Back
# ==========================
def move_image(destination_folder, status="yes"):
    global index
    if index > 0 and index <= len(images_list):
        img_path = images_list[index - 1]

        if os.path.exists(img_path):
            if use_local_cache:
                # Preserve relpaths for BOTH yes/no in cache mode
                rel_path = os.path.relpath(img_path, source_folder)
                dest_path = os.path.join(destination_folder, rel_path)
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            else:
                if status == "no":
                    dest_path = os.path.join(destination_folder, os.path.basename(img_path))
                else:
                    rel_path = os.path.relpath(img_path, source_folder)
                    dest_path = os.path.join(destination_folder, rel_path)
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

            if os.path.exists(dest_path):
                try:
                    os.remove(img_path)
                    print(f"Destination exists for '{os.path.basename(img_path)}'. DELETED source file.")
                except Exception as e:
                    print(f"Error deleting source file {img_path}: {e}")
            else:
                try:
                    os.rename(img_path, dest_path)
                except PermissionError as e:
                    print(f"Permission Error: Could not move file {img_path}. Is it still open? {e}")
                except Exception as e:
                    print(f"Error moving file {img_path}: {e}")

        mark_processed(img_path, status)

    next_image()


def go_back():
    global index, img_tk, next_img_tk
    if not history_stack:
        return

    last_image_path = history_stack.pop()

    rel_path = os.path.relpath(last_image_path, source_folder)
    yes_moved_path = os.path.join(yes_folder, rel_path)

    if use_local_cache:
        # In cache mode, NO also preserves relpaths
        no_moved_path = os.path.join(no_folder, rel_path)
    else:
        no_moved_path = os.path.join(no_folder, os.path.basename(last_image_path))

    moved_path = None
    if os.path.exists(yes_moved_path):
        moved_path = yes_moved_path
    elif os.path.exists(no_moved_path):
        moved_path = no_moved_path

    if moved_path:
        os.makedirs(os.path.dirname(last_image_path), exist_ok=True)
        try:
            os.rename(moved_path, last_image_path)
        except Exception as e:
            print(f"Error moving file back {moved_path}: {e}")
        finally:
            unmark_processed(last_image_path)

    index -= 2
    preload_next()  # refresh pipeline
    next_image()


# ==========================
# Preload / display (Drive-lag mitigation)
# ==========================
def _prepare_pil_for_display(img_path: str) -> Image.Image:
    with Image.open(img_path) as pil_img:
        pil_img.load()
        # Keep aspect ratio; fit into DISPLAY_W x DISPLAY_H
        pil_img.thumbnail((DISPLAY_W, DISPLAY_H), RESAMPLE)
        if pil_img.mode not in ("RGB", "RGBA"):
            pil_img = pil_img.convert("RGB")
        return pil_img.copy()


def preload_next():
    """
    Background thread: load+decode+resize into PIL Image ONLY.
    Main thread will convert to ImageTk.PhotoImage (Tk objects are not thread-safe).
    """
    global _next_pil, _preload_in_progress, _next_error_path, _next_error_msg

    _preload_in_progress = True
    try:
        if index < len(images_list):
            img_path = images_list[index]
            try:
                pil_ready = _prepare_pil_for_display(img_path)
                with _next_pil_lock:
                    _next_pil = pil_ready
                _next_error_path = None
                _next_error_msg = None
            except Exception as e:
                _next_error_path = img_path
                _next_error_msg = str(e)
                print(f"Error loading {img_path}: {e}")
                with _next_pil_lock:
                    _next_pil = None
        else:
            with _next_pil_lock:
                _next_pil = None
            _next_error_path = None
            _next_error_msg = None
    finally:
        _preload_in_progress = False


def _consume_preloaded_to_tk():
    global next_img_tk, _next_pil
    with _next_pil_lock:
        pil_img = _next_pil
        _next_pil = None

    if pil_img is None:
        next_img_tk = None
        return False

    next_img_tk = ImageTk.PhotoImage(pil_img)
    return True


def next_image():
    global img_tk, next_img_tk, index

    if not images_list or index >= len(images_list):
        load_next_batch()
        if not images_list:
            label.config(text="No unprocessed images found or all processed!")
            image_label.config(image="")
            img_tk = None
            return
        return

    got_image = _consume_preloaded_to_tk()
    if not got_image:
        # If preload failed for this specific file, skip it so we don't loop forever.
        if (not _preload_in_progress) and (_next_error_path == images_list[index]):
            bad_path = images_list[index]
            print(f"[SKIP BAD IMAGE] {bad_path} ({_next_error_msg})")

            # Mark as processed so it won't be picked again this run
            mark_processed(bad_path, "bad")

            # If we're in cache mode and the bad file is in the local inbox, delete it
            # so a future Sync Down can re-copy it cleanly.
            try:
                if (
                    use_local_cache
                    and os.path.exists(bad_path)
                    and os.path.commonpath([bad_path, source_folder]) == source_folder
                ):
                    os.remove(bad_path)
            except Exception as e:
                print(f"Error deleting bad cached file {bad_path}: {e}")

            index += 1
            threading.Thread(target=preload_next, daemon=True).start()
            root.after(1, next_image)
            return

        if not _preload_in_progress:
            threading.Thread(target=preload_next, daemon=True).start()
        root.after(15, next_image)
        return

    # Now safe to record history + display + advance index
    if index > 0 and index - 1 < len(images_list):
        history_stack.append(images_list[index - 1])

    img_tk = next_img_tk
    image_label.config(image=img_tk)

    remaining_in_batch = len(images_list) - index
    total_remaining = (len(ALL_UNPROCESSED_IMAGES) - BATCH_START_INDEX) + remaining_in_batch
    scanning_text = " (Still scanning...)" if not SCANNING_FINISHED else ""

    label.config(
        text=f"Batch: {index + 1}/{len(images_list)} | Total Remaining (this run): {total_remaining}{scanning_text}"
    )

    index += 1
    threading.Thread(target=preload_next, daemon=True).start()


# ==========================
# Load Images (capped scan)
# ==========================
def load_all_unprocessed_paths():
    global ALL_UNPROCESSED_IMAGES, SCANNING_FINISHED
    ALL_UNPROCESSED_IMAGES = []
    SCANNING_FINISHED = False

    temp_list = []
    first_batch_ready = False

    for root_dir, _, files in os.walk(source_folder):
        for f in files:
            if _is_image_file(f):
                full_path = os.path.join(root_dir, f)
                if not is_processed(full_path):
                    temp_list.append(full_path)

                    if len(temp_list) >= MAX_SESSION_IMAGES:
                        random.shuffle(temp_list)
                        ALL_UNPROCESSED_IMAGES.extend(temp_list[:MAX_SESSION_IMAGES])
                        SCANNING_FINISHED = True
                        root.after(0, finalize_load_images)
                        return

                    if not first_batch_ready and len(temp_list) >= IMAGE_BATCH_SIZE:
                        random.shuffle(temp_list)
                        ALL_UNPROCESSED_IMAGES.extend(temp_list)
                        temp_list = []
                        first_batch_ready = True
                        root.after(0, finalize_load_images)

    if temp_list:
        random.shuffle(temp_list)
        ALL_UNPROCESSED_IMAGES.extend(temp_list)

    if len(ALL_UNPROCESSED_IMAGES) > MAX_SESSION_IMAGES:
        ALL_UNPROCESSED_IMAGES = ALL_UNPROCESSED_IMAGES[:MAX_SESSION_IMAGES]

    SCANNING_FINISHED = True
    print(f"Found {len(ALL_UNPROCESSED_IMAGES)} total unprocessed images (capped).")

    if not first_batch_ready:
        root.after(0, finalize_load_images)


def load_next_batch():
    """Loads the next batch of images from the global list. RUNS ON MAIN THREAD."""
    global images_list, index, BATCH_START_INDEX

    start = BATCH_START_INDEX
    end = BATCH_START_INDEX + IMAGE_BATCH_SIZE

    current_batch = ALL_UNPROCESSED_IMAGES[start:end]

    if not current_batch:
        images_list = []
        return

    images_list = current_batch
    BATCH_START_INDEX = end
    index = 0

    print(f"Loaded batch: {start + 1} to {min(end, len(ALL_UNPROCESSED_IMAGES))}")

    # Prime preload for index 0, then let next_image wait until it's ready
    threading.Thread(target=preload_next, daemon=True).start()
    root.after(1, next_image)


def finalize_load_images():
    global images_list
    if not images_list and ALL_UNPROCESSED_IMAGES:
        load_next_batch()
    if not images_list and SCANNING_FINISHED:
        label.config(text="No unprocessed images found in the source folder!")


def start_load_images_threaded():
    label.config(text=f"Scanning folders... (loading up to {MAX_SESSION_IMAGES} images this run)")
    threading.Thread(target=load_all_unprocessed_paths, daemon=True).start()


# ==========================
# Scan reset helper
# ==========================
def reset_scan_and_restart():
    global images_list, index, img_tk, next_img_tk, history_stack
    global ALL_UNPROCESSED_IMAGES, BATCH_START_INDEX, SCANNING_FINISHED
    global _next_pil

    images_list = []
    index = 0
    img_tk = None
    next_img_tk = None
    history_stack = []

    ALL_UNPROCESSED_IMAGES = []
    BATCH_START_INDEX = 0
    SCANNING_FINISHED = False

    with _next_pil_lock:
        _next_pil = None

    image_label.config(image="")
    start_load_images_threaded()


# ==========================
# Buttons
# ==========================
yes_button = tk.Button(button_frame, text="Yes", width=10, command=lambda: move_image(yes_folder, "yes"))
yes_button.pack(side="left", padx=5)

no_button = tk.Button(button_frame, text="No", width=10, command=lambda: move_image(no_folder, "no"))
no_button.pack(side="left", padx=5)

back_button = tk.Button(button_frame, text="Go Back", width=10, command=go_back)
back_button.pack(side="left", padx=5)

settings_btn = tk.Button(button_frame, text="Settings", width=10, command=lambda: open_settings())
settings_btn.pack(side="left", padx=5)

# Sync buttons
def on_sync_down():
    if not use_local_cache:
        return
    if not (drive_source_folder and local_cache_root):
        label.config(text="Cache mode needs Drive Source + Local Cache Root (Settings).")
        return

    def ui_progress(copied: int, total: int):
        # Always update Tk widgets on main thread
        def apply():
            progress_bar.config(maximum=total)
            progress_bar["value"] = copied
            progress_text.config(text=f"Sync Down: {copied}/{total}")

        root.after(0, apply)

    def worker():
        try:
            def start_ui():
                _set_ui_busy(True, "Sync Down: copying from Drive to local cache...")
                progress_bar["value"] = 0
                progress_bar.config(maximum=MAX_SESSION_IMAGES)
                progress_bar.pack(fill="x")
                progress_text.config(text=f"Sync Down: 0/{MAX_SESSION_IMAGES}")
                progress_text.pack()

            root.after(0, start_ui)

            copied = sync_down_to_local(MAX_SESSION_IMAGES, progress_cb=ui_progress)

            def apply_and_restart():
                global source_folder, yes_folder, no_folder
                source_folder, yes_folder, no_folder = _compute_cache_paths(local_cache_root)
                os.makedirs(source_folder, exist_ok=True)
                os.makedirs(yes_folder, exist_ok=True)
                os.makedirs(no_folder, exist_ok=True)

                progress_bar.pack_forget()
                progress_text.pack_forget()
                _set_ui_busy(False, f"Sync Down done. Copied {copied} images. Scanning local cache...")
                reset_scan_and_restart()

            root.after(0, apply_and_restart)

        except Exception as e:
            def fail_ui():
                progress_bar.pack_forget()
                progress_text.pack_forget()
                _set_ui_busy(False, f"Sync Down failed: {e}")

            root.after(0, fail_ui)

    threading.Thread(target=worker, daemon=True).start()


def on_sync_up():
    if not use_local_cache:
        return
    if not (drive_source_folder and drive_yes_folder and drive_no_folder and local_cache_root):
        label.config(text="Cache mode needs Drive Source/Yes/No + Local Cache Root (Settings).")
        return

    def worker():
        try:
            root.after(0, lambda: _set_ui_busy(True, "Sync Up: uploading Yes/No to Drive + deleting originals..."))
            sync_up_to_drive_and_delete_originals()
            root.after(0, lambda: _set_ui_busy(False, "Sync Up done. (Uploaded + deleted originals)"))
        except Exception as e:
            root.after(0, lambda: _set_ui_busy(False, f"Sync Up failed: {e}"))

    threading.Thread(target=worker, daemon=True).start()


def on_sync_up_cleanup():
    if not use_local_cache:
        return
    if not (drive_source_folder and drive_yes_folder and drive_no_folder and local_cache_root):
        label.config(text="Cache mode needs Drive Source/Yes/No + Local Cache Root (Settings).")
        return

    def worker():
        try:
            root.after(
                0,
                lambda: _set_ui_busy(
                    True,
                    "Sync Up + Cleanup: uploading + deleting originals + deleting local...",
                ),
            )
            sync_up_to_drive_delete_originals_and_cleanup_local()
            root.after(
                0,
                lambda: _set_ui_busy(
                    False,
                    "Sync Up + Cleanup done. (Uploaded + deleted originals + cleaned local)",
                ),
            )
        except Exception as e:
            root.after(0, lambda: _set_ui_busy(False, f"Sync Up + Cleanup failed: {e}"))

    threading.Thread(target=worker, daemon=True).start()


sync_down_btn = tk.Button(sync_bar, text="Sync Down", width=10, command=on_sync_down)
sync_down_btn.pack(side="left", padx=5)

sync_up_btn = tk.Button(sync_bar, text="Sync Up", width=10, command=on_sync_up)
sync_up_btn.pack(side="left", padx=5)

sync_up_cleanup_btn = tk.Button(sync_bar, text="Sync Up + Cleanup", width=16, command=on_sync_up_cleanup)
sync_up_cleanup_btn.pack(side="left", padx=5)

if not use_local_cache:
    sync_down_btn.config(state="disabled")
    sync_up_btn.config(state="disabled")
    sync_up_cleanup_btn.config(state="disabled")


# ==========================
# Key and Mouse Bindings
# ==========================
def key_press(event):
    key = event.keysym
    if key == yes_key or key == "Left":
        move_image(yes_folder, "yes")
    elif key == no_key or key == "Right":
        move_image(no_folder, "no")
    elif key == back_key:
        go_back()


root.bind("<Key>", key_press)


def bind_mouse_actions():
    image_label.unbind("<Button-1>")
    image_label.unbind("<Button-2>")
    image_label.unbind("<Button-3>")

    if yes_mouse:
        image_label.bind(f"<{yes_mouse}>", lambda event: move_image(yes_folder, "yes"))

    if no_mouse and no_mouse != yes_mouse:
        image_label.bind(f"<{no_mouse}>", lambda event: move_image(no_folder, "no"))


# ==========================
# Settings Window
# ==========================
def open_settings():
    global yes_key, no_key, back_key, yes_mouse, no_mouse
    global source_folder, yes_folder, no_folder
    global use_local_cache, local_cache_root, drive_source_folder, drive_yes_folder, drive_no_folder

    conn_settings = sqlite3.connect(DB_FILE)
    cursor_settings = conn_settings.cursor()

    def save_setting_local(key, value):
        cursor_settings.execute(
            """
            INSERT INTO settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, str(value)),
        )
        conn_settings.commit()

    settings_win = tk.Toplevel(root)
    settings_win.title("Settings")
    settings_win.transient(root)
    settings_win.grab_set()

    def on_settings_close():
        conn_settings.close()
        settings_win.destroy()

    settings_win.protocol("WM_DELETE_WINDOW", on_settings_close)

    def update_controls_label():
        controls = f"Yes: {yes_key} / {yes_mouse} | No: {no_key} / {no_mouse} | Back: {back_key}"
        controls_label.config(text=controls)
        bind_mouse_actions()
        sync_down_btn.config(state="normal" if use_local_cache else "disabled")
        sync_up_btn.config(state="normal" if use_local_cache else "disabled")
        sync_up_cleanup_btn.config(state="normal" if use_local_cache else "disabled")

    # --- KEY BINDINGS ---
    tk.Label(settings_win, text="Keyboard Bindings", font=("Helvetica", 12, "bold")).grid(
        row=0, column=0, columnspan=3, pady=10
    )

    def capture_key(label_widget, key_var_name):
        def inner(event):
            val = event.keysym
            globals()[key_var_name] = val
            label_widget.config(text=f"{key_var_name.replace('_', ' ').title()}: {val}")
            save_setting_local(key_var_name, val)
            update_controls_label()
            settings_win.unbind("<Key>")

        label_widget.config(text="Press a key...")
        settings_win.bind("<Key>", inner)

    yes_label_k = tk.Label(settings_win, text=f"Yes Key: {yes_key}", width=20, anchor="w")
    yes_label_k.grid(row=1, column=0, padx=5, pady=5, sticky="w")
    tk.Button(settings_win, text="Set Yes Key", command=lambda: capture_key(yes_label_k, "yes_key")).grid(
        row=1, column=2, padx=5, sticky="w"
    )

    no_label_k = tk.Label(settings_win, text=f"No Key: {no_key}", width=20, anchor="w")
    no_label_k.grid(row=2, column=0, padx=5, pady=5, sticky="w")
    tk.Button(settings_win, text="Set No Key", command=lambda: capture_key(no_label_k, "no_key")).grid(
        row=2, column=2, padx=5, sticky="w"
    )

    back_label_k = tk.Label(settings_win, text=f"Back Key: {back_key}", width=20, anchor="w")
    back_label_k.grid(row=3, column=0, padx=5, pady=5, sticky="w")
    tk.Button(settings_win, text="Set Back Key", command=lambda: capture_key(back_label_k, "back_key")).grid(
        row=3, column=2, padx=5, sticky="w"
    )

    tk.Frame(settings_win, height=2, bd=1, relief="sunken").grid(row=4, columnspan=3, sticky="ew", padx=5, pady=10)

    # --- MOUSE BINDINGS ---
    tk.Label(settings_win, text="Mouse Bindings", font=("Helvetica", 12, "bold")).grid(
        row=5, column=0, columnspan=3, pady=10
    )

    def capture_mouse(label_widget, mouse_var_name):
        def inner(event):
            val = f"Button-{event.num}"
            globals()[mouse_var_name] = val
            label_widget.config(text=f"{mouse_var_name.replace('_', ' ').title()}: {val}")
            save_setting_local(mouse_var_name, val)
            update_controls_label()

            settings_win.unbind("<Button-1>")
            settings_win.unbind("<Button-2>")
            settings_win.unbind("<Button-3>")

        settings_win.bind("<Button-1>", inner)
        settings_win.bind("<Button-2>", inner)
        settings_win.bind("<Button-3>", inner)

        label_widget.config(text="Click a mouse button...")

    yes_label_m = tk.Label(settings_win, text=f"Yes Mouse: {yes_mouse}", width=20, anchor="w")
    yes_label_m.grid(row=6, column=0, padx=5, pady=5, sticky="w")
    tk.Button(settings_win, text="Set Yes Mouse", command=lambda: capture_mouse(yes_label_m, "yes_mouse")).grid(
        row=6, column=2, padx=5, sticky="w"
    )

    no_label_m = tk.Label(settings_win, text=f"No Mouse: {no_mouse}", width=20, anchor="w")
    no_label_m.grid(row=7, column=0, padx=5, pady=5, sticky="w")
    tk.Button(settings_win, text="Set No Mouse", command=lambda: capture_mouse(no_label_m, "no_mouse")).grid(
        row=7, column=2, padx=5, sticky="w"
    )

    tk.Frame(settings_win, height=2, bd=1, relief="sunken").grid(row=8, columnspan=3, sticky="ew", padx=5, pady=10)

    # --- NORMAL MODE FOLDERS ---
    tk.Label(settings_win, text="Folder Paths", font=("Helvetica", 12, "bold")).grid(
        row=9, column=0, columnspan=3, pady=10
    )

    def change_folder(folder_type, label_widget):
        global source_folder, yes_folder, no_folder
        new_folder = filedialog.askdirectory(title=f"Select {folder_type} Folder")
        if not new_folder:
            return

        if folder_type == "Source":
            save_setting_local("source_folder", new_folder)
            if not use_local_cache:
                source_folder = new_folder
                label_widget.config(text=new_folder)
                reset_scan_and_restart()
            else:
                label_widget.config(text="(cache mode active)")
        elif folder_type == "Yes":
            save_setting_local("yes_folder", new_folder)
            if not use_local_cache:
                yes_folder = new_folder
                label_widget.config(text=new_folder)
            else:
                label_widget.config(text="(cache mode active)")
        elif folder_type == "No":
            save_setting_local("no_folder", new_folder)
            if not use_local_cache:
                no_folder = new_folder
                label_widget.config(text=new_folder)
            else:
                label_widget.config(text="(cache mode active)")

    tk.Label(settings_win, text="Source Folder:").grid(row=10, column=0, sticky="e")
    source_label = tk.Label(
        settings_win,
        text=(source_folder if not use_local_cache else "(cache mode active)"),
        width=40,
        anchor="w",
        wraplength=250,
    )
    source_label.grid(row=10, column=1, sticky="w")
    tk.Button(settings_win, text="Change", command=lambda: change_folder("Source", source_label)).grid(
        row=10, column=2, padx=5, sticky="w"
    )

    tk.Label(settings_win, text="'Yes' Folder:").grid(row=11, column=0, sticky="e")
    yes_label_f = tk.Label(
        settings_win,
        text=(yes_folder if not use_local_cache else "(cache mode active)"),
        width=40,
        anchor="w",
        wraplength=250,
    )
    yes_label_f.grid(row=11, column=1, sticky="w")
    tk.Button(settings_win, text="Change", command=lambda: change_folder("Yes", yes_label_f)).grid(
        row=11, column=2, padx=5, sticky="w"
    )

    tk.Label(settings_win, text="'No' Folder:").grid(row=12, column=0, sticky="e")
    no_label_f = tk.Label(
        settings_win,
        text=(no_folder if not use_local_cache else "(cache mode active)"),
        width=40,
        anchor="w",
        wraplength=250,
    )
    no_label_f.grid(row=12, column=1, sticky="w")
    tk.Button(settings_win, text="Change", command=lambda: change_folder("No", no_label_f)).grid(
        row=12, column=2, padx=5, sticky="w"
    )

    tk.Frame(settings_win, height=2, bd=1, relief="sunken").grid(
        row=13, columnspan=3, sticky="ew", padx=5, pady=10
    )

    # --- CACHE MODE SETTINGS ---
    tk.Label(settings_win, text="Local Cache / Drive Sync", font=("Helvetica", 12, "bold")).grid(
        row=14, column=0, columnspan=3, pady=10
    )

    cache_var = tk.IntVar(value=1 if use_local_cache else 0)

    def choose_local_cache_root():
        global local_cache_root
        new_root = filedialog.askdirectory(title="Select Local Cache Root (fast local folder)")
        if new_root:
            local_cache_root = new_root
            save_setting_local("local_cache_root", local_cache_root)
            cache_root_label.config(text=local_cache_root)

    def choose_drive_folder(which: str):
        global drive_source_folder, drive_yes_folder, drive_no_folder
        new_folder = filedialog.askdirectory(title=f"Select Drive {which} Folder (Google Drive)")
        if not new_folder:
            return
        if which == "Source":
            drive_source_folder = new_folder
            save_setting_local("drive_source_folder", drive_source_folder)
            drive_source_label.config(text=drive_source_folder)
        elif which == "Yes":
            drive_yes_folder = new_folder
            save_setting_local("drive_yes_folder", drive_yes_folder)
            drive_yes_label.config(text=drive_yes_folder)
        elif which == "No":
            drive_no_folder = new_folder
            save_setting_local("drive_no_folder", drive_no_folder)
            drive_no_label.config(text=drive_no_folder)

    def toggle_cache_mode():
        global use_local_cache, source_folder, yes_folder, no_folder
        desired = cache_var.get() == 1

        if desired and not local_cache_root:
            choose_local_cache_root()
            if not local_cache_root:
                cache_var.set(0)
                return

        use_local_cache = desired
        save_setting_local("use_local_cache", "1" if use_local_cache else "0")

        if use_local_cache:
            source_folder, yes_folder, no_folder = _compute_cache_paths(local_cache_root)
            os.makedirs(source_folder, exist_ok=True)
            os.makedirs(yes_folder, exist_ok=True)
            os.makedirs(no_folder, exist_ok=True)
        else:
            source_folder = load_setting("source_folder")
            yes_folder = load_setting("yes_folder")
            no_folder = load_setting("no_folder")

        update_controls_label()
        reset_scan_and_restart()

    tk.Checkbutton(settings_win, text="Use Local Cache Mode", variable=cache_var, command=toggle_cache_mode).grid(
        row=15, column=0, columnspan=3, sticky="w", padx=5
    )

    tk.Label(settings_win, text="Local Cache Root:").grid(row=16, column=0, sticky="e")
    cache_root_label = tk.Label(settings_win, text=local_cache_root, width=40, anchor="w", wraplength=250)
    cache_root_label.grid(row=16, column=1, sticky="w")
    tk.Button(settings_win, text="Change", command=choose_local_cache_root).grid(row=16, column=2, padx=5, sticky="w")

    tk.Label(settings_win, text="Drive Source:").grid(row=17, column=0, sticky="e")
    drive_source_label = tk.Label(settings_win, text=drive_source_folder, width=40, anchor="w", wraplength=250)
    drive_source_label.grid(row=17, column=1, sticky="w")
    tk.Button(settings_win, text="Change", command=lambda: choose_drive_folder("Source")).grid(
        row=17, column=2, padx=5, sticky="w"
    )

    tk.Label(settings_win, text="Drive Yes:").grid(row=18, column=0, sticky="e")
    drive_yes_label = tk.Label(settings_win, text=drive_yes_folder, width=40, anchor="w", wraplength=250)
    drive_yes_label.grid(row=18, column=1, sticky="w")
    tk.Button(settings_win, text="Change", command=lambda: choose_drive_folder("Yes")).grid(
        row=18, column=2, padx=5, sticky="w"
    )

    tk.Label(settings_win, text="Drive No:").grid(row=19, column=0, sticky="e")
    drive_no_label = tk.Label(settings_win, text=drive_no_folder, width=40, anchor="w", wraplength=250)
    drive_no_label.grid(row=19, column=1, sticky="w")
    tk.Button(settings_win, text="Change", command=lambda: choose_drive_folder("No")).grid(
        row=19, column=2, padx=5, sticky="w"
    )


# ==========================
# Start App
# ==========================
bind_mouse_actions()
reset_scan_and_restart()


def _auto_sync_down_on_start():
    """
    If cache mode is enabled and configured, automatically Sync Down once on startup
    when the local inbox is empty.
    """
    if not use_local_cache:
        return
    if not (drive_source_folder and local_cache_root):
        return

    inbox, _, _ = _compute_cache_paths(local_cache_root)

    # Only auto-sync if inbox is empty (avoid re-copying every launch)
    if not os.path.exists(inbox) or not any(_iter_images(inbox)):
        on_sync_down()


root.after(250, _auto_sync_down_on_start)

root.mainloop()

conn_main.close()