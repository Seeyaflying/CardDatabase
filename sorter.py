import os
import sys
import tkinter as tk
from tkinter import filedialog
from PIL import Image, ImageTk
import random
import sqlite3
import threading
from datetime import datetime

# ==========================
# Database Setup
# ==========================
# Always use folder above dist as main folder
if getattr(sys, 'frozen', False):
    exe_folder = os.path.dirname(sys.executable)
    main_folder = os.path.dirname(exe_folder)  # parent folder
else:
    main_folder = os.path.dirname(os.path.abspath(__file__))

DB_FILE = os.path.join(main_folder, "skipped_images.sqlite")
conn_main = sqlite3.connect(DB_FILE)
cursor_main = conn_main.cursor()

# Create tables if not exist
cursor_main.execute("""
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
)
""")

cursor_main.execute("""
CREATE TABLE IF NOT EXISTS progress (
    img_path TEXT PRIMARY KEY,
    processed_at TEXT,
    status TEXT
)
""")
conn_main.commit()

# ==========================
# Helper Functions
# ==========================
def save_setting(key, value):
    cursor_main.execute("""
    INSERT INTO settings (key, value) VALUES (?, ?)
    ON CONFLICT(key) DO UPDATE SET value=excluded.value
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
    yes_folder = filedialog.askdirectory(title="Select 'Yes' Folder")
    no_folder = filedialog.askdirectory(title="Select 'No' Folder")
    save_setting("source_folder", source_folder)
    save_setting("yes_folder", yes_folder)
    save_setting("no_folder", no_folder)

source_folder = load_setting("source_folder")
yes_folder = load_setting("yes_folder")
no_folder = load_setting("no_folder")

if not (source_folder and os.path.exists(source_folder)):
    ask_for_folders()

# Default keys
yes_key = load_setting("yes_key", "y")
no_key = load_setting("no_key", "n")
skip_key = load_setting("skip_key", "s")
back_key = load_setting("back_key", "b")

# ==========================
# Global Variables
# ==========================
images_list = []
index = 0
img_tk = None
next_img_tk = None
history_stack = []

# ==========================
# Tkinter UI Setup
# ==========================
root.deiconify()
root.title("Image Reviewer")

image_label = tk.Label(root)
image_label.pack()

label = tk.Label(root, text="Loading images...")
label.pack()

button_frame = tk.Frame(root)
button_frame.pack(pady=10)

# ==========================
# Move Images
# ==========================
def move_image(destination_folder, status="yes"):
    global index
    if index > 0:
        img_path = images_list[index - 1]
        if os.path.exists(img_path):
            rel_path = os.path.relpath(img_path, source_folder)
            dest_path = os.path.join(destination_folder, rel_path)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            os.rename(img_path, dest_path)
        mark_processed(img_path, status)
    next_image()

def move_yes():
    move_image(yes_folder, "yes")

def move_no():
    global index
    if index > 0:
        img_path = images_list[index - 1]
        if os.path.exists(img_path):
            # Ensure the skipped folder exists
            os.makedirs(no_folder, exist_ok=True)
            base_name = os.path.basename(img_path)
            dest_path = os.path.join(no_folder, base_name)

            # Add numeric suffix if file already exists
            base, ext = os.path.splitext(dest_path)
            counter = 1
            while os.path.exists(dest_path):
                dest_path = f"{base}_{counter}{ext}"
                counter += 1

            os.rename(img_path, dest_path)

        mark_processed(img_path, "no")
    next_image()



def move_skip():
    mark_processed(images_list[index-1], "skipped")
    next_image()

# ==========================
# Preload Next Image
# ==========================
def preload_next():
    global next_img_tk
    if index < len(images_list):
        img_path = images_list[index]
        try:
            pil_img = Image.open(img_path)
            pil_img.thumbnail((800, 600), Image.LANCZOS)
            next_img_tk = ImageTk.PhotoImage(pil_img)
        except:
            next_img_tk = None
    else:
        next_img_tk = None

# ==========================
# Display Next Image
# ==========================
def next_image():
    global img_tk, next_img_tk, index
    if not images_list or index >= len(images_list):
        label.config(text="No unprocessed images found or all processed!")
        image_label.config(image="")
        img_tk = None
        return

    if index > 0:
        history_stack.append(images_list[index - 1])

    img_tk = next_img_tk
    if img_tk:
        image_label.config(image=img_tk)
    remaining = len(images_list) - index
    if index < len(images_list):
        label.config(text=f"{index+1}/{len(images_list)}: {os.path.basename(images_list[index])} | Remaining: {remaining}")
    index += 1

    threading.Thread(target=preload_next, daemon=True).start()

# ==========================
# Go Back (Undo Last Move)
# ==========================
def go_back():
    global index, img_tk, next_img_tk
    if history_stack:
        last_image = history_stack.pop()
        # Undo last move in DB
        cursor_main.execute("DELETE FROM progress WHERE img_path=?", (last_image,))
        conn_main.commit()

        # Move back to source folder if it was moved
        for folder in [yes_folder, no_folder]:
            rel_path = os.path.relpath(last_image, source_folder)
            moved_path = os.path.join(folder, rel_path)
            if os.path.exists(moved_path):
                os.makedirs(os.path.dirname(last_image), exist_ok=True)
                os.rename(moved_path, last_image)
                break

        index -= 1
        try:
            pil_img = Image.open(last_image)
            pil_img.thumbnail((800, 600), Image.LANCZOS)
            img_tk = ImageTk.PhotoImage(pil_img)
            image_label.config(image=img_tk)
            label.config(text=f"{index}/{len(images_list)}: {os.path.basename(last_image)} | Remaining: {len(images_list) - index}")
        except:
            img_tk = None

# ==========================
# Load Images
# ==========================
def load_images():
    """
    Load all images from the source folder that haven't been processed yet.
    Shuffles them randomly. This runs once when the app starts.
    """
    global images_list, index
    all_images = []
    for root_dir, _, files in os.walk(source_folder):
        for f in files:
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif")):
                full_path = os.path.join(root_dir, f)
                if not is_processed(full_path):
                    all_images.append(full_path)

    random.shuffle(all_images)
    images_list = all_images
    index = 0

    preload_next()
    next_image()

# ==========================
# Buttons for Yes/No/Skip/Back
# ==========================
yes_button = tk.Button(button_frame, text="Yes", width=10, command=move_yes)
yes_button.pack(side="left", padx=5)

no_button = tk.Button(button_frame, text="No", width=10, command=move_no)
no_button.pack(side="left", padx=5)

skip_button = tk.Button(button_frame, text="Skip", width=10, command=move_skip)
skip_button.pack(side="left", padx=5)

back_button = tk.Button(button_frame, text="Go Back", width=10, command=go_back)
back_button.pack(side="left", padx=5)

# ==========================
# Key Bindings
# ==========================
def key_press(event):
    if event.char == yes_key:
        move_yes()
    elif event.char == no_key:
        move_no()
    elif event.char == skip_key:
        move_skip()
    elif event.char == back_key:
        go_back()

root.bind("<Key>", key_press)

# ==========================
# Settings Window
# ==========================
def open_settings():
    settings_win = tk.Toplevel(root)
    settings_win.title("Settings")

    # Key labels
    yes_label = tk.Label(settings_win, text=f"Yes Key: {yes_key}", width=20)
    yes_label.grid(row=0, column=0, padx=5, pady=5)
    no_label = tk.Label(settings_win, text=f"No Key: {no_key}", width=20)
    no_label.grid(row=1, column=0, padx=5, pady=5)
    skip_label = tk.Label(settings_win, text=f"Skip Key: {skip_key}", width=20)
    skip_label.grid(row=2, column=0, padx=5, pady=5)
    back_label = tk.Label(settings_win, text=f"Back Key: {back_key}", width=20)
    back_label.grid(row=3, column=0, padx=5, pady=5)

    def capture_key(label_widget, key_name):
        def inner(event):
            val = event.char
            globals()[key_name] = val
            label_widget.config(text=f"{key_name.replace('_', ' ').title()}: {val}")
            save_setting(key_name, val)
            settings_win.unbind("<Key>")
        return inner

    tk.Button(settings_win, text="Set Yes Key", command=lambda: settings_win.bind("<Key>", capture_key(yes_label, "yes_key"))).grid(row=0, column=1)
    tk.Button(settings_win, text="Set No Key", command=lambda: settings_win.bind("<Key>", capture_key(no_label, "no_key"))).grid(row=1, column=1)
    tk.Button(settings_win, text="Set Skip Key", command=lambda: settings_win.bind("<Key>", capture_key(skip_label, "skip_key"))).grid(row=2, column=1)
    tk.Button(settings_win, text="Set Back Key", command=lambda: settings_win.bind("<Key>", capture_key(back_label, "back_key"))).grid(row=3, column=1)

    # Folder settings
    def change_folder(folder_type):
        global source_folder, yes_folder, no_folder
        new_folder = filedialog.askdirectory(title=f"Select {folder_type} Folder")
        if new_folder:
            if folder_type == "Source":
                source_folder = new_folder
                save_setting("source_folder", source_folder)
                source_label.config(text=source_folder)
            elif folder_type == "'Yes'":
                yes_folder = new_folder
                save_setting("yes_folder", yes_folder)
                yes_label_f.config(text=yes_folder)
            elif folder_type == "'No'":
                no_folder = new_folder
                save_setting("no_folder", no_folder)
                no_label_f.config(text=no_folder)

    tk.Label(settings_win, text="Source Folder:").grid(row=4, column=0, sticky="e")
    source_label = tk.Label(settings_win, text=source_folder, width=40, anchor="w")
    source_label.grid(row=4, column=1)
    tk.Button(settings_win, text="Change", command=lambda: change_folder("Source")).grid(row=4, column=2)

    tk.Label(settings_win, text="'Yes' Folder:").grid(row=5, column=0, sticky="e")
    yes_label_f = tk.Label(settings_win, text=yes_folder, width=40, anchor="w")
    yes_label_f.grid(row=5, column=1)
    tk.Button(settings_win, text="Change", command=lambda: change_folder("'Yes'")).grid(row=5, column=2)

    tk.Label(settings_win, text="'No' Folder:").grid(row=6, column=0, sticky="e")
    no_label_f = tk.Label(settings_win, text=no_folder, width=40, anchor="w")
    no_label_f.grid(row=6, column=1)
    tk.Button(settings_win, text="Change", command=lambda: change_folder("'No'")).grid(row=6, column=2)

settings_btn = tk.Button(root, text="Settings", command=open_settings)
settings_btn.pack()

# ==========================
# Load Images & Start App
# ==========================
load_images()
root.mainloop()
