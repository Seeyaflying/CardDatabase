import sys
import os
import random
import numpy as np
import sqlite3
import time

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

# ==============================================================
# 1. PLATFORM DETECTION & DYNAMIC PATHS
# ==============================================================
IS_WINDOWS = os.name == 'nt'

# The SQLite DB stays in the same folder as this script
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "skipped_images.sqlite")

if IS_WINDOWS:
    # Windows Native Google Drive Paths
    DATASET_PATH = r"G:\My Drive\Card Database"
    MODELS_DIR = r"G:\My Drive\models\CardData"
else:
    # Ubuntu/Linux Paths (Assumes rclone mount at ~/Desktop/GDrive)
    DATASET_PATH = os.path.expanduser("~/Desktop/GDrive/Card Database")
    MODELS_DIR = os.path.expanduser("~/Desktop/GDrive/models/CardData")

# Ensure the models directory exists locally/on drive
os.makedirs(MODELS_DIR, exist_ok=True)


# ==============================================================
# 2. DATABASE HELPERS
# ==============================================================
def connect_db():
    """Connects to SQLite with multi-thread support for the GUI."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
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
                       total_steps INTEGER NOT NULL
                       )
                   """)
    cursor.execute("SELECT COUNT(*) FROM card_ai WHERE id=1")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO card_ai (id, genome, total_steps) VALUES (1, 1, 0)")
        conn.commit()
    return conn


def load_card_ai(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT genome, total_steps FROM card_ai WHERE id=1")
    row = cursor.fetchone()
    return {"genome": row[0], "total_steps": row[1]} if row else {"genome": 1, "total_steps": 0}


def save_card_ai(conn, genome, total_steps):
    cursor = conn.cursor()
    cursor.execute("UPDATE card_ai SET genome=?, total_steps=? WHERE id=1", (genome, total_steps))
    conn.commit()


# ==============================================================
# 3. TRAINING THREAD (Backend Logic)
# ==============================================================
class TrainingThread(QThread):
    progress = Signal(str)
    image_update = Signal(QPixmap)
    accuracy_update = Signal(float)
    loss_update = Signal(float)
    genome_update = Signal(int)
    total_steps_update = Signal(int)
    progress_bar_update = Signal(int)

    def __init__(self, model, data_path, target_size, epochs, class_labels, max_steps_per_epoch):
        super().__init__()
        self.model = model
        self.data_path = data_path
        self.target_size = target_size
        self.epochs = epochs
        self.class_labels = class_labels
        self.max_steps_per_epoch = max_steps_per_epoch
        self.conn = connect_db()
        stats = load_card_ai(self.conn)
        self.genome = stats["genome"]
        self.total_steps = stats["total_steps"]

    def run(self):
        try:
            image_paths, labels = [], []
            for subdir, _, files in os.walk(self.data_path):
                class_name = os.path.basename(subdir)
                if class_name in self.class_labels:
                    idx = self.class_labels.index(class_name)
                    for file in files:
                        if file.lower().endswith(('.png', '.jpg', '.jpeg')):
                            image_paths.append(os.path.join(subdir, file))
                            labels.append(idx)

            if not image_paths:
                self.progress.emit(f"Error: No images found in {self.data_path}")
                return

            total_run_steps = self.max_steps_per_epoch * self.epochs
            current_run_step = 0

            for epoch in range(self.epochs):
                combined = list(zip(image_paths, labels))
                random.shuffle(combined)
                steps_in_epoch = min(self.max_steps_per_epoch, len(image_paths))

                for step in range(steps_in_epoch):
                    img_p, class_idx = combined[step]

                    # Pillow 10+ uses Resampling.BICUBIC
                    img = Image.open(img_p).convert("RGB").resize(self.target_size, Image.Resampling.BICUBIC)
                    x = np.expand_dims(np.array(img) / 255.0, axis=0)
                    y = np.zeros((1, len(self.class_labels)))
                    y[0, class_idx] = 1

                    loss, acc = self.model.train_on_batch(x, y)

                    # UI Updates
                    self.progress.emit(
                        f"G:{self.genome} E:{epoch + 1} S:{step + 1} | {os.path.basename(img_p)} | Acc:{acc:.2f}")
                    self.image_update.emit(QPixmap(img_p))
                    self.accuracy_update.emit(acc)
                    self.loss_update.emit(loss)

                    current_run_step += 1
                    self.total_steps += 1
                    self.total_steps_update.emit(self.total_steps)
                    self.progress_bar_update.emit(int(current_run_step / total_run_steps * 100))

                    save_card_ai(self.conn, self.genome, self.total_steps)

                # Save model per epoch
                m_path = os.path.join(MODELS_DIR, f'card_ai_gen_{self.genome}_ep_{epoch + 1}.keras')
                self.model.save(m_path)

                self.genome += 1
                self.genome_update.emit(self.genome)
                save_card_ai(self.conn, self.genome, self.total_steps)

            self.progress.emit("--- Training Session Complete ---")
        except Exception as e:
            self.progress.emit(f"CRITICAL ERROR: {str(e)}")
        finally:
            self.conn.close()


# ==============================================================
# 4. MAIN GUI WINDOW
# ==============================================================
class CardPredictorApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TCG Card Predictor AI")
        self.resize(1100, 750)

        # DB Init
        self.conn = connect_db()
        stats = load_card_ai(self.conn)
        self.genome = stats["genome"]
        self.total_steps = stats["total_steps"]

        # UI Layout
        main_layout = QHBoxLayout()

        # Left Side (Image Preview)
        left_layout = QVBoxLayout()
        self.image_label = QLabel("Waiting for Training...")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setScaledContents(True)
        self.image_label.setFixedSize(500, 700)
        self.image_label.setStyleSheet("border: 2px solid #444; background: #000;")
        left_layout.addWidget(self.image_label)
        main_layout.addLayout(left_layout)

        # Right Side (Logs & Stats)
        right_layout = QVBoxLayout()
        self.text_output = QTextEdit()
        self.text_output.setReadOnly(True)
        self.text_output.setStyleSheet("background: #1e1e1e; color: #00ff00; font-family: monospace;")
        right_layout.addWidget(self.text_output)

        # Inputs
        self.epochs_input = QLineEdit()
        self.epochs_input.setPlaceholderText("Number of Epochs (e.g. 5)")
        right_layout.addWidget(self.epochs_input)

        # Labels
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

        # Load Data Info
        self.target_size = (200, 200)
        if os.path.exists(DATASET_PATH):
            self.class_labels = sorted(
                [d for d in os.listdir(DATASET_PATH) if os.path.isdir(os.path.join(DATASET_PATH, d))])
            self.append_text(f"Loaded {len(self.class_labels)} card categories.")
        else:
            self.class_labels = []
            self.append_text(f"CRITICAL: Dataset not found at {DATASET_PATH}")

        self.model = self.load_or_create_model()

    def load_or_create_model(self):
        m_file = os.path.join(MODELS_DIR, 'card_predictor_latest.keras')
        if os.path.exists(m_file):
            self.append_text("Loading existing model...")
            return load_model(m_file)
        return self.build_model()

    def build_model(self):
        self.append_text("Building new neural network...")
        num_classes = len(self.class_labels) if self.class_labels else 1
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
        self.training_thread = TrainingThread(self.model, DATASET_PATH, self.target_size, epochs, self.class_labels,
                                              500)

        # Connect Signals
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