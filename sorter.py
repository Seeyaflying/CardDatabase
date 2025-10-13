import os
import sys
import tkinter as tk
from tkinter import filedialog
from PIL import Image, ImageTk
import random
import sqlite3
import threading
from datetime import datetime

# Define the batch size for preloading
IMAGE_BATCH_SIZE = 250

# ==========================
# Database Setup
# ==========================
if getattr(sys, 'frozen', False):
    exe_folder = os.path.dirname(sys.executable)
    main_folder = os.path.dirname(exe_folder)
else:
    main_folder = os.path.dirname(os.path.abspath(__file__))

DB_FILE = os.path.join(main_folder, "skipped_images.sqlite")
# Main connection for status/progress (used by background thread)
conn_main = sqlite3.connect(DB_FILE, check_same_thread=False)
cursor_main = conn_main.cursor()

cursor_main.execute("""
                    CREATE TABLE IF NOT EXISTS settings
                    (
                        key
                        TEXT
                        PRIMARY
                        KEY,
                        value
                        TEXT
                    )
                    """)

cursor_main.execute("""
                    CREATE TABLE IF NOT EXISTS progress
                    (
                        img_path
                        TEXT
                        PRIMARY
                        KEY,
                        processed_at
                        TEXT,
                        status
                        TEXT
                    )
                    """)
conn_main.commit()


# ==========================
# Helper Functions
# ==========================
# This save_setting function is for the main progress updates (not settings window)
def save_progress_setting(key, value):
    cursor_main.execute("""
                        INSERT INTO settings (key, value)
                        VALUES (?, ?) ON CONFLICT(key) DO
                        UPDATE SET value =excluded.value
                        """, (key, value))
    conn_main.commit()


def load_setting(key, default=None):
    cursor_main.execute("SELECT value FROM settings WHERE key=?", (key,))
    result = cursor_main.fetchone()
    return result[0] if result else default


def mark_processed(img_path, status="yes"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor_main.execute("""
    INSERT OR REPLACE INTO progress (img_path, processed_at, status) VALUES (?, ?, ?)
    """, (img_path, timestamp, status))
    conn_main.commit()


def is_processed(img_path):
    cursor_main.execute("SELECT 1 FROM progress WHERE img_path=?", (img_path,))
    return cursor_main.fetchone() is not None


# ==========================
# Initialize Folders and Keys
# ==========================
root = tk.Tk()
root.withdraw()


def ask_for_folders():
    global source_folder, yes_folder, no_folder
    source_folder = filedialog.askdirectory(title="Select Source Folder")
    if not source_folder: sys.exit()
    yes_folder = filedialog.askdirectory(title="Select 'Yes' Folder")
    if not yes_folder: sys.exit()
    no_folder = filedialog.askdirectory(title="Select 'No' Folder")
    if not no_folder: sys.exit()
    save_progress_setting("source_folder", source_folder)
    save_progress_setting("yes_folder", yes_folder)
    save_progress_setting("no_folder", no_folder)


source_folder = load_setting("source_folder")
yes_folder = load_setting("yes_folder")
no_folder = load_setting("no_folder")

if not all([source_folder, yes_folder, no_folder,
            os.path.exists(source_folder), os.path.exists(yes_folder), os.path.exists(no_folder)]):
    ask_for_folders()

# Default keyboard keys
yes_key = load_setting("yes_key", "y")  # Default: 'y'
no_key = load_setting("no_key", "n")  # Default: 'n'
back_key = load_setting("back_key", "b")  # Default: 'b'

# Default Mouse Bindings
yes_mouse = load_setting("yes_mouse", "Button-1")  # Default: Left Click
no_mouse = load_setting("no_mouse", "Button-3")  # Default: Right Click

# ==========================
# Global Variables
# ==========================
images_list = []
index = 0
img_tk = None
next_img_tk = None
history_stack = []

# Global Variables for batching
ALL_UNPROCESSED_IMAGES = []
BATCH_START_INDEX = 0

# ==========================
# Tkinter UI Setup
# ==========================
root.deiconify()
root.title("Image Reviewer")
root.geometry("480x780")
root.resizable(False, False)

# --- UI Element Definitions ---

# Main image label (placed at the top)
image_label = tk.Label(root)
image_label.pack(padx=10, pady=10)

# Label for current image/loading status (placed below the image)
label = tk.Label(root, text="Scanning all folders...")
label.pack(pady=5)

# Control/Button Frame (placed at the bottom)
control_bar_frame = tk.Frame(root)
control_bar_frame.pack(side="bottom", fill="x", pady=10)

# Button Frame (for Yes/No/Back/Settings)
button_frame = tk.Frame(control_bar_frame)
button_frame.pack(pady=5)

# Controls Label (placed next to buttons)
controls_text = f"Yes: {yes_key} / {yes_mouse} | No: {no_key} / {no_mouse} | Back: {back_key}"
controls_label = tk.Label(control_bar_frame, text=controls_text, font=("Helvetica", 9))
controls_label.pack(pady=5)


# ==========================
# Move Functions
# ==========================
def move_image(destination_folder, status="yes"):
    global index
    if index > 0 and index <= len(images_list):
        img_path = images_list[index - 1]

        if os.path.exists(img_path):
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


# ==========================
# Preload Next Image
# ==========================
def preload_next():
    global next_img_tk
    if index < len(images_list):
        img_path = images_list[index]
        try:
            with Image.open(img_path) as pil_img:
                pil_img.load()
                pil_img = pil_img.resize((460, 680), Image.LANCZOS)
                next_img_tk = ImageTk.PhotoImage(pil_img)

        except Exception as e:
            print(f"Error loading {img_path}: {e}")
            next_img_tk = None
    else:
        next_img_tk = None


# ==========================
# Display Next Image
# ==========================
def next_image():
    global img_tk, next_img_tk, index

    if not images_list or index >= len(images_list):
        load_next_batch()
        if not images_list:
            label.config(text="No unprocessed images found or all processed!")
            image_label.config(image="")
            img_tk = None
            return

    if index > 0 and index - 1 < len(images_list):
        history_stack.append(images_list[index - 1])

    img_tk = next_img_tk
    if img_tk:
        image_label.config(image=img_tk)

    remaining_in_batch = len(images_list) - index
    total_remaining = len(ALL_UNPROCESSED_IMAGES) - BATCH_START_INDEX + remaining_in_batch

    if index < len(images_list):
        label.config(
            text=f"Batch: {index + 1}/{len(images_list)} | Total Remaining: {total_remaining}")

    index += 1
    threading.Thread(target=preload_next, daemon=True).start()


# ==========================
# Go Back (Undo Last Move)
# ==========================
def go_back():
    global index, img_tk, next_img_tk
    if history_stack:
        last_image_path = history_stack.pop()

        rel_path = os.path.relpath(last_image_path, source_folder)
        yes_moved_path = os.path.join(yes_folder, rel_path)
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
                cursor_main.execute("DELETE FROM progress WHERE img_path=?", (last_image_path,))
                conn_main.commit()

        index -= 2
        preload_next()
        next_image()


# ==========================
# Load Images (Batching Logic)
# ==========================
def load_all_unprocessed_paths():
    """Finds all unprocessed images and shuffles them once. RUNS IN BACKGROUND THREAD."""
    global ALL_UNPROCESSED_IMAGES
    ALL_UNPROCESSED_IMAGES = []

    for root_dir, _, files in os.walk(source_folder):
        for f in files:
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif")):
                full_path = os.path.join(root_dir, f)
                if not is_processed(full_path):
                    ALL_UNPROCESSED_IMAGES.append(full_path)

    random.shuffle(ALL_UNPROCESSED_IMAGES)
    print(f"Found {len(ALL_UNPROCESSED_IMAGES)} total unprocessed images.")


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

    preload_next()
    next_image()


def finalize_load_images():
    """Called safely from the thread to update the UI and start the app. RUNS ON MAIN THREAD."""
    global images_list

    # 2. Load the first batch
    load_next_batch()

    if not images_list:
        label.config(text="No unprocessed images found in the source folder!")


def load_images():
    """Performs the long I/O task and schedules the UI update. Runs in background thread."""
    load_all_unprocessed_paths()
    root.after(0, finalize_load_images)


def start_load_images_threaded():
    """Starts the initial image scan in a background thread to prevent freezing."""
    label.config(text="Scanning all folders and preparing batches... Please wait.")
    threading.Thread(target=load_images, daemon=True).start()


# ==========================
# Buttons (Yes/No/Back/Settings)
# ==========================
yes_button = tk.Button(button_frame, text="Yes", width=10, command=lambda: move_image(yes_folder, "yes"))
yes_button.pack(side="left", padx=5)

no_button = tk.Button(button_frame, text="No", width=10, command=lambda: move_image(no_folder, "no"))
no_button.pack(side="left", padx=5)

back_button = tk.Button(button_frame, text="Go Back", width=10, command=go_back)
back_button.pack(side="left", padx=5)

settings_btn = tk.Button(button_frame, text="Settings", width=10, command=lambda: open_settings())
settings_btn.pack(side="left", padx=5)


# ==========================
# Key and Mouse Bindings
# ==========================
def key_press(event):
    key = event.keysym
    if key == yes_key or key == 'Left':
        move_image(yes_folder, "yes")
    elif key == no_key or key == 'Right':
        move_image(no_folder, "no")
    elif key == back_key:
        go_back()


root.bind("<Key>", key_press)


# Dynamic Mouse Bindings Function
def bind_mouse_actions():
    global yes_mouse, no_mouse
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

    # === FIX: Use a dedicated, local connection/cursor for settings to avoid RecursiveUse error ===
    conn_settings = sqlite3.connect(DB_FILE)
    cursor_settings = conn_settings.cursor()

    def save_setting_local(key, value):
        cursor_settings.execute("""
                                INSERT INTO settings (key, value)
                                VALUES (?, ?) ON CONFLICT(key) DO
                                UPDATE SET value =excluded.value
                                """, (key, value))
        conn_settings.commit()

    # ==============================================================================================

    settings_win = tk.Toplevel(root)
    settings_win.title("Settings")
    settings_win.transient(root)
    settings_win.grab_set()

    # Bind an exit handler to close the local connection when the window closes
    def on_settings_close():
        conn_settings.close()
        settings_win.destroy()

    settings_win.protocol("WM_DELETE_WINDOW", on_settings_close)

    def update_controls_label():
        controls_text = f"Yes: {yes_key} / {yes_mouse} | No: {no_key} / {no_mouse} | Back: {back_key}"
        controls_label.config(text=controls_text)
        bind_mouse_actions()

    # --- KEY BINDINGS ---
    tk.Label(settings_win, text="Keyboard Bindings", font=("Helvetica", 12, "bold")).grid(row=0, column=0, columnspan=3,
                                                                                          pady=10)

    def capture_key(label_widget, key_var_name):
        def inner(event):
            val = event.keysym
            globals()[key_var_name] = val
            label_widget.config(text=f"{key_var_name.replace('_', ' ').title()}: {val}")
            # === FIX: Use the local save function ===
            save_setting_local(key_var_name, val)
            update_controls_label()
            settings_win.unbind("<Key>")

        label_widget.config(text="Press a key...")
        settings_win.bind("<Key>", inner)

    yes_label_k = tk.Label(settings_win, text=f"Yes Key: {yes_key}", width=20, anchor="w")
    yes_label_k.grid(row=1, column=0, padx=5, pady=5, sticky="w")
    tk.Button(settings_win, text="Set Yes Key",
              command=lambda: capture_key(yes_label_k, "yes_key")).grid(row=1, column=2, padx=5, sticky="w")

    no_label_k = tk.Label(settings_win, text=f"No Key: {no_key}", width=20, anchor="w")
    no_label_k.grid(row=2, column=0, padx=5, pady=5, sticky="w")
    tk.Button(settings_win, text="Set No Key",
              command=lambda: capture_key(no_label_k, "no_key")).grid(row=2, column=2, padx=5, sticky="w")

    back_label_k = tk.Label(settings_win, text=f"Back Key: {back_key}", width=20, anchor="w")
    back_label_k.grid(row=3, column=0, padx=5, pady=5, sticky="w")
    tk.Button(settings_win, text="Set Back Key",
              command=lambda: capture_key(back_label_k, "back_key")).grid(row=3, column=2, padx=5, sticky="w")

    tk.Frame(settings_win, height=2, bd=1, relief="sunken").grid(row=4, columnspan=3, sticky="ew", padx=5, pady=10)

    # --- MOUSE BINDINGS ---
    tk.Label(settings_win, text="Mouse Bindings", font=("Helvetica", 12, "bold")).grid(row=5, column=0, columnspan=3,
                                                                                       pady=10)

    def capture_mouse(label_widget, mouse_var_name):
        def inner(event):
            val = f"Button-{event.num}"
            globals()[mouse_var_name] = val
            label_widget.config(text=f"{mouse_var_name.replace('_', ' ').title()}: {val}")
            # === FIX: Use the local save function ===
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
    tk.Button(settings_win, text="Set Yes Mouse",
              command=lambda: capture_mouse(yes_label_m, "yes_mouse")).grid(row=6, column=2, padx=5, sticky="w")

    no_label_m = tk.Label(settings_win, text=f"No Mouse: {no_mouse}", width=20, anchor="w")
    no_label_m.grid(row=7, column=0, padx=5, pady=5, sticky="w")
    tk.Button(settings_win, text="Set No Mouse",
              command=lambda: capture_mouse(no_label_m, "no_mouse")).grid(row=7, column=2, padx=5, sticky="w")

    tk.Frame(settings_win, height=2, bd=1, relief="sunken").grid(row=8, columnspan=3, sticky="ew", padx=5, pady=10)

    # --- FOLDER PATHS ---
    tk.Label(settings_win, text="Folder Paths", font=("Helvetica", 12, "bold")).grid(row=9, column=0, columnspan=3,
                                                                                     pady=10)

    def change_folder(folder_type, label_widget):
        global source_folder, yes_folder, no_folder
        new_folder = filedialog.askdirectory(title=f"Select {folder_type} Folder")
        if new_folder:
            if folder_type == "Source":
                source_folder = new_folder
                save_setting_local("source_folder", source_folder)
            elif folder_type == "Yes":
                yes_folder = new_folder
                save_setting_local("yes_folder", yes_folder)
            elif folder_type == "No":
                no_folder = new_folder
                save_setting_local("no_folder", no_folder)
            label_widget.config(text=new_folder)

            if folder_type == "Source":
                start_load_images_threaded()

    tk.Label(settings_win, text="Source Folder:").grid(row=10, column=0, sticky="e")
    source_label = tk.Label(settings_win, text=source_folder, width=40, anchor="w", wraplength=250)
    source_label.grid(row=10, column=1, columnspan=1, sticky="w")
    tk.Button(settings_win, text="Change", command=lambda: change_folder("Source", source_label)).grid(row=10, column=2,
                                                                                                       padx=5,
                                                                                                       sticky="w")

    tk.Label(settings_win, text="'Yes' Folder:").grid(row=11, column=0, sticky="e")
    yes_label_f = tk.Label(settings_win, text=yes_folder, width=40, anchor="w", wraplength=250)
    yes_label_f.grid(row=11, column=1, columnspan=1, sticky="w")
    tk.Button(settings_win, text="Change", command=lambda: change_folder("Yes", yes_label_f)).grid(row=11, column=2,
                                                                                                   padx=5, sticky="w")

    tk.Label(settings_win, text="'No' Folder:").grid(row=12, column=0, sticky="e")
    no_label_f = tk.Label(settings_win, text=no_folder, width=40, anchor="w", wraplength=250)
    no_label_f.grid(row=12, column=1, columnspan=1, sticky="w")
    tk.Button(settings_win, text="Change", command=lambda: change_folder("No", no_label_f)).grid(row=12, column=2,
                                                                                                 padx=5, sticky="w")


# ==========================
# Start App
# ==========================
bind_mouse_actions()
start_load_images_threaded()
root.mainloop()

# Close the main connection when the app closes
conn_main.close()