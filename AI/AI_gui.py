import sys
import os
import re
import random
import numpy as np
import time
from pathlib import Path

# UI Imports
from PySide6.QtWidgets import (
    QApplication, QWidget, QPushButton, QVBoxLayout, QLabel,
    QTextEdit, QLineEdit, QHBoxLayout, QProgressBar
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPixmap

# AI & Image Processing
from PIL import Image
from tensorflow.keras.models import Sequential, load_model
from tensorflow.keras.layers import Input, Conv2D, MaxPooling2D, Flatten, Dense
from tensorflow.keras.optimizers import Adam

# Point Python at the utilities folder where config.py lives
UTILS = Path(__file__).resolve().parent.parent / "utilities"
sys.path.insert(0, str(UTILS))

import config
from pymongo import MongoClient

# ==============================================================
# 1. DATABASE (Mongo carddb.card_ai) & PATHS
# ==============================================================
_client = None

def get_client():
    global _client
    if _client is None:
        _client = MongoClient(config.MONGO_URI, serverSelectionTimeoutMS=5000)
    return _client

def card_ai_coll():
    return get_client()[config.DB_NAME]["card_ai"]

# --- Card database folders to scan for images -----------------
DATASET_ROOTS = [
    Path(r"T:\Full Card Database\Card Database"),
    Path(r"T:\Full Card Database\New Cards"),
]

# --- Model save locations --------------------------------------
MODELS_DIR = config.G_DRIVE / "models" / "CardData"
MODELS_DIR_LOCAL = Path(r"T:\Full Card Database\models\CardData")
MODELS_DIR.mkdir(parents=True, exist_ok=True)
MODELS_DIR_LOCAL.mkdir(parents=True, exist_ok=True)

# Shared model file — same one the headless script uses
MODEL_FILE = MODELS_DIR / "card_ai_model.keras"
MODEL_FILE_LOCAL = MODELS_DIR_LOCAL / "card_ai_model.keras"


# ==============================================================
# 2. DATABASE HELPERS (read/write card_ai, keyed by id: 1)
# ==============================================================
def load_card_ai():
    """Read genome/steps from the existing card_ai doc (keyed by id: 1)."""
    doc = card_ai_coll().find_one({"id": 1})
    if doc is None:
        card_ai_coll().insert_one({"id": 1, "genome": 1, "total_steps": 0, "full_iteration": 0})
        return {"genome": 1, "total_steps": 0}
    return {
        "genome": doc.get("genome", 1),
        "total_steps": doc.get("total_steps", 0),
    }

def save_card_ai(genome, total_steps):
    card_ai_coll().update_one(
        {"id": 1},
        {"$set": {"genome": genome, "total_steps": total_steps}},
        upsert=True,
    )


# ==============================================================
# 3. TRAINING THREAD
# ==============================================================
class TrainingThread(QThread):
    progress = Signal(str)
    image_update = Signal(QPixmap)
    accuracy_update = Signal(float)
    loss_update = Signal(float)
    genome_update = Signal(int)
    total_steps_update = Signal(int)
    progress_bar_update = Signal(int)

    def __init__(self, model, data_roots, target_size, epochs, class_labels, max_steps_per_epoch):
        super().__init__()
        self.model = model
        self.data_roots = data_roots
        self.target_size = target_size
        self.epochs = epochs
        self.class_labels = class_labels
        self.max_steps_per_epoch = max_steps_per_epoch
        stats = load_card_ai()
        self.genome = stats["genome"]
        self.total_steps = stats["total_steps"]

    def run(self):
        try:
            image_paths, labels = [], []
            for root in self.data_roots:
                if not os.path.exists(root):
                    continue
                for subdir, _, files in os.walk(root):
                    class_name = os.path.basename(subdir)
                    if class_name in self.class_labels:
                        idx = self.class_labels.index(class_name)
                        for file in files:
                            if file.lower().endswith(('.png', '.jpg', '.jpeg')):
                                image_paths.append(os.path.join(subdir, file))
                                labels.append(idx)

            if not image_paths:
                self.progress.emit(f"Error: No images found in {self.data_roots}")
                return

            self.progress.emit(f"Found {len(image_paths)} images across {len(self.class_labels)} classes.")

            total_run_steps = self.max_steps_per_epoch * self.epochs
            current_run_step = 0

            for epoch in range(self.epochs):
                combined = list(zip(image_paths, labels))
                random.shuffle(combined)
                steps_in_epoch = min(self.max_steps_per_epoch, len(image_paths))

                for step in range(steps_in_epoch):
                    img_p, class_idx = combined[step]

                    try:
                        img = Image.open(img_p).convert("RGB").resize(self.target_size, Image.Resampling.BICUBIC)
                    except Exception as e:
                        self.progress.emit(f"SKIP bad image: {os.path.basename(img_p)} ({e})")
                        continue

                    x = np.expand_dims(np.array(img) / 255.0, axis=0)
                    y = np.zeros((1, len(self.class_labels)))
                    y[0, class_idx] = 1

                    loss, acc = self.model.train_on_batch(x, y)

                    self.progress.emit(
                        f"G:{self.genome} E:{epoch + 1} S:{step + 1} | {os.path.basename(img_p)} | Acc:{acc:.2f}")
                    self.image_update.emit(QPixmap(img_p))
                    self.accuracy_update.emit(acc)
                    self.loss_update.emit(loss)

                    current_run_step += 1
                    self.total_steps += 1
                    self.total_steps_update.emit(self.total_steps)
                    self.progress_bar_update.emit(int(current_run_step / total_run_steps * 100))

                    save_card_ai(self.genome, self.total_steps)

                # Save to the shared model file (Drive + local copy)
                self.model.save(str(MODEL_FILE))
                self.model.save(str(MODEL_FILE_LOCAL))

                self.genome += 1
                self.genome_update.emit(self.genome)
                save_card_ai(self.genome, self.total_steps)

                self.progress.emit(
                    f"--- Genome {self.genome - 1} complete. Model saved to {MODEL_FILE.name} "
                    f"(+ local copy). Ready to run again. ---")

            self.progress.emit("--- Training Session Complete ---")
        except Exception as e:
            self.progress.emit(f"CRITICAL ERROR: {str(e)}")


# ==============================================================
# 4. MAIN GUI WINDOW
# ==============================================================
class CardPredictorApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TCG Card Predictor AI")
        self.resize(1100, 750)

        stats = load_card_ai()
        self.genome = stats["genome"]
        self.total_steps = stats["total_steps"]

        main_layout = QHBoxLayout()

        left_layout = QVBoxLayout()
        self.image_label = QLabel("Waiting for Training...")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setScaledContents(True)
        self.image_label.setFixedSize(500, 700)
        self.image_label.setStyleSheet("border: 2px solid #444; background: #000;")
        left_layout.addWidget(self.image_label)
        main_layout.addLayout(left_layout)

        right_layout = QVBoxLayout()
        self.text_output = QTextEdit()
        self.text_output.setReadOnly(True)
        self.text_output.setStyleSheet("background: #1e1e1e; color: #00ff00; font-family: monospace;")
        right_layout.addWidget(self.text_output)

        self.epochs_input = QLineEdit()
        self.epochs_input.setPlaceholderText("Number of Epochs (e.g. 5)")
        right_layout.addWidget(self.epochs_input)

        self.accuracy_label = QLabel("Accuracy: 0.00%")
        self.loss_label = QLabel("Loss: 0.0000")
        self.genome_label = QLabel(f"Current Genome: {self.genome}")
        self.total_steps_label = QLabel(f"Global Steps: {self.total_steps}")
        for lbl in [self.accuracy_label, self.loss_label, self.genome_label, self.total_steps_label]:
            lbl.setStyleSheet("font-weight: bold; font-size: 14px;")
            right_layout.addWidget(lbl)

        self.progress_bar = QProgressBar()
        right_layout.addWidget(self.progress_bar)

        self.train_button = QPushButton("START TRAINING")
        self.train_button.setFixedHeight(50)
        self.train_button.setStyleSheet("background: #27ae60; color: white; font-weight: bold;")
        self.train_button.clicked.connect(self.train_model)
        right_layout.addWidget(self.train_button)

        main_layout.addLayout(right_layout)
        self.setLayout(main_layout)

        self.target_size = (200, 200)
        self.class_labels = self.collect_class_labels()
        if self.class_labels:
            self.append_text(f"Loaded {len(self.class_labels)} card categories.")
        else:
            self.append_text(f"CRITICAL: No card folders found in {DATASET_ROOTS}")

        self.model = self.load_or_create_model()

    def collect_class_labels(self):
        """Gather unique game-folder names across all dataset roots."""
        labels = set()
        for root in DATASET_ROOTS:
            if not os.path.exists(root):
                continue
            for subdir, _, _ in os.walk(root):
                labels.add(os.path.basename(subdir))
        return sorted(labels)

    def load_or_create_model(self):
        """Load the shared model, or rebuild it if the class count changed."""
        num_classes = len(self.class_labels) if self.class_labels else 1

        if MODEL_FILE.exists():
            try:
                loaded = load_model(str(MODEL_FILE))
                # Check if the output layer matches the current class count
                existing = loaded.output_shape[-1]
                if existing == num_classes:
                    self.append_text(f"Loading shared model ({existing} classes): {MODEL_FILE.name}")
                    return loaded
                else:
                    self.append_text(
                        f"Class count changed: model has {existing} classes, data now has {num_classes}. "
                        f"Rebuilding model to match.")
            except Exception as e:
                self.append_text(f"Could not load existing model ({e}). Building new one.")

        self.append_text("Building new neural network...")
        model = Sequential([
            Input(shape=(200, 200, 3)),
            Conv2D(32, (3, 3), activation='relu'),
            MaxPooling2D((2, 2)),
            Flatten(),
            Dense(128, activation='relu'),
            Dense(num_classes, activation='softmax')
        ])
        model.compile(optimizer=Adam(1e-5), loss='categorical_crossentropy', metrics=['accuracy'])
        return model

    def train_model(self):
        if not self.class_labels:
            self.append_text("Aborted: No data folders found.")
            return

        try:
            val = int(self.epochs_input.text())
            epochs = val if val > 0 else 1
        except:
            epochs = 1

        self.train_button.setEnabled(False)
        self.training_thread = TrainingThread(self.model, DATASET_ROOTS, self.target_size, epochs, self.class_labels, 500)

        self.training_thread.progress.connect(self.append_text)
        self.training_thread.image_update.connect(self.update_image)
        self.training_thread.accuracy_update.connect(self.update_accuracy)
        self.training_thread.loss_update.connect(self.update_loss)
        self.training_thread.genome_update.connect(self.update_genome)
        self.training_thread.total_steps_update.connect(self.update_total_steps)
        self.training_thread.progress_bar_update.connect(self.update_progress_bar)
        self.training_thread.finished.connect(lambda: self.train_button.setEnabled(True))

        self.training_thread.start()

    def append_text(self, msg):
        self.text_output.append(msg)

    def update_image(self, pix):
        self.image_label.setPixmap(pix)

    def update_accuracy(self, acc):
        self.accuracy_label.setText(f"Accuracy: {acc * 100:.2f}%")

    def update_loss(self, loss):
        self.loss_label.setText(f"Loss: {loss:.4f}")

    def update_genome(self, gen):
        self.genome_label.setText(f"Current Genome: {gen}")

    def update_total_steps(self, steps):
        self.total_steps_label.setText(f"Global Steps: {steps}")

    def update_progress_bar(self, val):
        self.progress_bar.setValue(val)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = CardPredictorApp()
    window.show()
    sys.exit(app.exec())






