import sys
import os
import random
import numpy as np
from pathlib import Path
from PIL import Image

# AI Frameworks
import tensorflow as tf
from tensorflow.keras.models import Sequential, load_model
from tensorflow.keras.layers import Input, Conv2D, MaxPooling2D, Flatten, Dense
from tensorflow.keras.optimizers import Adam

# Point at the shared utilities config.py
UTILS = Path(__file__).resolve().parent.parent / "utilities"
sys.path.insert(0, str(UTILS))

import config
from pymongo import MongoClient

# ==============================================================
# 1. PLATFORM DETECTION & DYNAMIC PATHS
# ==============================================================
IS_WINDOWS = os.name == 'nt'

if IS_WINDOWS:
    DATASET_PATH = r"T:\Full Card Database\Card Database"
    MODELS_DIR = config.G_DRIVE / "models" / "CardData"
else:
    DATASET_PATH = os.path.expanduser("~/Desktop/GDrive/Card Database")
    MODELS_DIR = Path(os.path.expanduser("~/Desktop/GDrive/models/CardData"))

# Canonical model file shared with the GUI
MODEL_FILE = MODELS_DIR / "card_ai_model.keras"
os.makedirs(MODELS_DIR, exist_ok=True)


# ==============================================================
# 2. DATABASE HELPERS (Mongo carddb.card_ai, keyed by id: 1)
# ==============================================================
_client = None

def get_client():
    global _client
    if _client is None:
        _client = MongoClient(config.MONGO_URI, serverSelectionTimeoutMS=5000)
    return _client

def card_ai_coll():
    return get_client()[config.DB_NAME]["card_ai"]

def load_card_ai():
    """Read genome/steps from the shared card_ai doc (keyed by id: 1)."""
    doc = card_ai_coll().find_one({"id": 1})
    if doc is None:
        card_ai_coll().insert_one({"id": 1, "genome": 1, "total_steps": 0, "full_iteration": 0})
        return {"genome": 1, "total_steps": 0, "full_iteration": 0}
    return {
        "genome": doc.get("genome", 1),
        "total_steps": doc.get("total_steps", 0),
        "full_iteration": doc.get("full_iteration", 0),
    }

def save_card_ai(genome, total_steps, full_iteration):
    card_ai_coll().update_one(
        {"id": 1},
        {"$set": {"genome": genome, "total_steps": total_steps, "full_iteration": full_iteration}},
        upsert=True,
    )


# ==============================================================
# 3. CNN HELPERS
# ==============================================================
def init_model(target_size, class_labels):
    num_classes = len(class_labels)

    if MODEL_FILE.exists():
        try:
            loaded = load_model(str(MODEL_FILE))
            existing = loaded.output_shape[-1]
            if existing == num_classes:
                print(f"Loading existing model ({existing} classes) from {MODEL_FILE}")
                return loaded
            else:
                print(f"Class count changed: model has {existing} classes, data now has {num_classes}. "
                      f"Rebuilding model to match.")
        except Exception as e:
            print(f"Could not load existing model ({e}). Building new one.")

    model = Sequential([
        Input(shape=(target_size[0], target_size[1], 3)),
        Conv2D(32, (3, 3), activation='relu'),
        MaxPooling2D((2, 2)),
        Flatten(),
        Dense(128, activation='relu'),
        Dense(num_classes, activation='softmax')
    ])
    model.compile(optimizer=Adam(1e-5), loss='categorical_crossentropy', metrics=['accuracy'])
    print(f"Initialized new CNN model for {num_classes} classes.")
    return model


def train_model(model, data_path, target_size, epochs, class_labels, max_steps, genome, total_steps,
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
                img = Image.open(img_path).convert("RGB").resize(target_size, Image.Resampling.BICUBIC)
                x = np.expand_dims(np.array(img) / 255.0, axis=0)
                y = np.zeros((1, len(class_labels)))
                y[0, class_idx] = 1

                loss, acc = model.train_on_batch(x, y)
                total_steps += 1
                full_iteration += 1

                save_card_ai(genome, total_steps, full_iteration)

                print(f"[Step {total_steps}] G:{genome} | E:{epoch + 1}/{epochs} | "
                      f"S:{step_in_epoch}/{steps_per_epoch} | TCG: {tcg_name} | "
                      f"Acc: {acc:.4f} | Loss: {loss:.4f}")
            except Exception as e:
                print(f"Skipping {os.path.basename(img_path)} due to error: {e}")
                continue

    # Save the shared model file
    model.save(str(MODEL_FILE))
    print(f"Saved shared model at {MODEL_FILE}\n")

    return total_steps, full_iteration


# ==============================================================
# 4. MAIN ENTRY POINT
# ==============================================================
def main():
    target_size = (200, 200)
    values = load_card_ai()
    genome = values["genome"]
    total_steps = values["total_steps"]
    full_iteration = values["full_iteration"]

    if not os.path.exists(DATASET_PATH):
        print(f"Dataset folder not found: {DATASET_PATH}")
        print("Make sure your rclone mount is active!")
        return

    class_labels = [d for d in sorted(os.listdir(DATASET_PATH))
                    if os.path.isdir(os.path.join(DATASET_PATH, d)) and not d.startswith('.')]

    if not class_labels:
        print(f"No subfolders found in dataset path: {DATASET_PATH}")
        return

    model = init_model(target_size, class_labels)

    epochs = 1
    max_steps_per_epoch = 500

    while True:
        try:
            num_genomes = int(input("Number of genomes to train (or 0 to exit): "))
        except ValueError:
            print("Invalid input. Defaulting to 1 genome.")
            num_genomes = 1

        if num_genomes <= 0:
            print("Exiting.")
            break

        for _ in range(num_genomes):
            print(f"\n=== Training Genome {genome} ===")
            total_steps, full_iteration = train_model(
                model, DATASET_PATH, target_size, epochs,
                class_labels, max_steps_per_epoch,
                genome, total_steps, full_iteration
            )
            genome += 1
            save_card_ai(genome, total_steps, full_iteration)
            print(f"--- Genome {genome - 1} complete. Model saved to {MODEL_FILE.name}. "
                  f"Ready to run again. ---")

        again = input("\nRun another genome? (y/n): ").strip().lower()
        if again not in ("y", "yes"):
            print("Exiting.")
            break

    print("\nTraining completed.")


if __name__ == "__main__":
    main()

