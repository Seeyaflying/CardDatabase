import sys
import os
import random
import numpy as np
import sqlite3
import time
from PIL import Image

# AI Frameworks
import tensorflow as tf
from tensorflow.keras.models import Sequential, load_model
from tensorflow.keras.layers import Input, Conv2D, MaxPooling2D, Flatten, Dense
from tensorflow.keras.optimizers import Adam

# ==============================================================
# 1. PLATFORM DETECTION & DYNAMIC PATHS
# ==============================================================
IS_WINDOWS = os.name == 'nt'

# SQLite database stays in the script folder
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "skipped_images.sqlite")

if IS_WINDOWS:
    # Windows Native Google Drive Paths (G: Drive)
    DATASET_PATH = r"G:\My Drive\Card Database"
    MODELS_DIR = r"G:\My Drive\models\CardData\models"
else:
    # Ubuntu Paths (Assumes rclone mount at ~/Desktop/GDrive)
    DATASET_PATH = os.path.expanduser("~/Desktop/GDrive/Card Database")
    MODELS_DIR = os.path.expanduser("~/Desktop/GDrive/models/CardData/models")

# Ensure the models directory exists locally or on drive
os.makedirs(MODELS_DIR, exist_ok=True)


# ==============================================================
# 2. DATABASE HELPERS
# ==============================================================
def connect_db():
    conn = sqlite3.connect(DB_PATH)
    # Ensure the table exists if starting from scratch on Ubuntu
    cursor = conn.cursor()
    cursor.execute("""
                   CREATE TABLE IF NOT EXISTS card_ai
                   (
                       id
                       INTEGER
                       PRIMARY
                       KEY
                       CHECK
                   (
                       id =
                       1
                   ),
                       genome INTEGER NOT NULL,
                       total_steps INTEGER NOT NULL,
                       full_iteration INTEGER NOT NULL
                       )
                   """)
    conn.commit()
    return conn


def load_card_ai(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT genome, total_steps, full_iteration FROM card_ai WHERE id = 1")
    row = cursor.fetchone()
    if row:
        return {"genome": row[0], "total_steps": row[1], "full_iteration": row[2]}
    return {"genome": 1, "total_steps": 0, "full_iteration": 0}


def save_card_ai(conn, genome, total_steps, full_iteration):
    cursor = conn.cursor()
    cursor.execute("""
                   INSERT INTO card_ai (id, genome, total_steps, full_iteration)
                   VALUES (1, ?, ?, ?) ON CONFLICT(id) DO
                   UPDATE SET
                       genome=excluded.genome,
                       total_steps=excluded.total_steps,
                       full_iteration=excluded.full_iteration
                   """, (genome, total_steps, full_iteration))
    conn.commit()


# ==============================================================
# 3. CNN HELPERS
# ==============================================================
def init_model(target_size, class_labels):
    model_file = os.path.join(MODELS_DIR, 'card_predictor_model.keras')
    if os.path.exists(model_file):
        print(f"Loading existing model from {model_file}")
        # Note: compile=False is safer when moving models across platforms
        return load_model(model_file)

    model = Sequential([
        Input(shape=(target_size[0], target_size[1], 3)),
        Conv2D(32, (3, 3), activation='relu'),
        MaxPooling2D((2, 2)),
        Flatten(),
        Dense(128, activation='relu'),
        Dense(len(class_labels), activation='softmax')
    ])
    model.compile(optimizer=Adam(1e-5), loss='categorical_crossentropy', metrics=['accuracy'])
    print(f"Initialized new CNN model for {len(class_labels)} classes.")
    return model


def train_model(model, data_path, target_size, epochs, class_labels, max_steps, conn, genome, total_steps,
                full_iteration):
    image_paths, labels, tcg_names = [], [], []

    print(f"Scanning for images in: {data_path}...")
    for subdir, _, files in os.walk(data_path):
        class_name = os.path.basename(subdir)
        if class_name in class_labels:
            idx = class_labels.index(class_name)
            for file in files:
                if file.lower().endswith(('.png', '.jpg', '.jpeg')):
                    image_paths.append(os.path.join(subdir, file))
                    labels.append(idx)
                    tcg_names.append(class_name)

    if not image_paths:
        print("No images found in dataset folder!")
        return total_steps, full_iteration

    steps_per_epoch = min(max_steps, len(image_paths))

    for epoch in range(epochs):
        combined = list(zip(image_paths, labels, tcg_names))
        random.shuffle(combined)

        for step_in_epoch, (img_path, class_idx, tcg_name) in enumerate(combined[:steps_per_epoch], start=1):
            try:
                # Use Resampling.BICUBIC for Pillow 10+ (standard on Python 3.12)
                img = Image.open(img_path).convert("RGB").resize(target_size, Image.Resampling.BICUBIC)
                x = np.expand_dims(np.array(img) / 255.0, axis=0)
                y = np.zeros((1, len(class_labels)))
                y[0, class_idx] = 1

                loss, acc = model.train_on_batch(x, y)
                total_steps += 1
                full_iteration += 1

                # Save progress to SQLite
                save_card_ai(conn, genome, total_steps, full_iteration)

                print(f"[Step {total_steps}] G:{genome} | E:{epoch + 1}/{epochs} | "
                      f"S:{step_in_epoch}/{steps_per_epoch} | TCG: {tcg_name} | "
                      f"Acc: {acc:.4f} | Loss: {loss:.4f}")
            except Exception as e:
                print(f"Skipping {os.path.basename(img_path)} due to error: {e}")
                continue

    # Save model progress
    latest_file = os.path.join(MODELS_DIR, 'card_predictor_model.keras')
    genome_file = os.path.join(MODELS_DIR, f'card_predictor_model_genome_{genome}.keras')

    model.save(latest_file)
    model.save(genome_file)
    print(f"Saved model for genome {genome} at {genome_file}\n")

    return total_steps, full_iteration


# ==============================================================
# 4. MAIN ENTRY POINT
# ==============================================================
def main():
    target_size = (200, 200)
    conn = connect_db()
    values = load_card_ai(conn)
    genome = values["genome"]
    total_steps = values["total_steps"]
    full_iteration = values["full_iteration"]

    if not os.path.exists(DATASET_PATH):
        print(f"Dataset folder not found: {DATASET_PATH}")
        print("Make sure your rclone mount is active!")
        return

    # Filter out hidden folders like .tmp or .idea
    class_labels = [d for d in sorted(os.listdir(DATASET_PATH))
                    if os.path.isdir(os.path.join(DATASET_PATH, d)) and not d.startswith('.')]

    if not class_labels:
        print(f"No subfolders found in dataset path: {DATASET_PATH}")
        return

    model = init_model(target_size, class_labels)

    try:
        num_genomes = int(input("Number of genomes to train: "))
    except ValueError:
        print("Invalid input. Defaulting to 1 genome.")
        num_genomes = 1

    epochs = 1
    max_steps_per_epoch = 500

    for _ in range(num_genomes):
        print(f"\n=== Training Genome {genome} ===")
        total_steps, full_iteration = train_model(
            model, DATASET_PATH, target_size, epochs,
            class_labels, max_steps_per_epoch,
            conn, genome, total_steps, full_iteration
        )
        genome += 1
        full_iteration = 0  # Reset local iteration for next genome
        save_card_ai(conn, genome, total_steps, full_iteration)

    conn.close()
    print("\nTraining completed.")


if __name__ == "__main__":
    main()