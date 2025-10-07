import sys
import os
import random
import numpy as np
from PySide6.QtWidgets import (
    QApplication, QWidget, QPushButton, QVBoxLayout, QLabel,
    QTextEdit, QLineEdit, QHBoxLayout, QProgressBar
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPixmap
from PIL import Image
from tensorflow.keras.models import Sequential, load_model
from tensorflow.keras.layers import Input, Conv2D, MaxPooling2D, Flatten, Dense
from tensorflow.keras.optimizers import Adam
import sqlite3

# ------------------------------
# Paths
# ------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # SQLite in same folder as script
DB_PATH = os.path.join(BASE_DIR, "skipped_images.sqlite")
DATASET_PATH = "G:/My Drive/Card Database"  # Change as needed
MODELS_DIR = "G:/My Drive/models/CardData"

# ------------------------------
# SQLite helpers
# ------------------------------
def connect_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS card_ai (
            id INTEGER PRIMARY KEY CHECK (id = 1),
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
    if row:
        return {"genome": row[0], "total_steps": row[1]}
    return {"genome": 1, "total_steps": 0}

def save_card_ai(conn, genome, total_steps):
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE card_ai SET genome=?, total_steps=? WHERE id=1
    """, (genome, total_steps))
    conn.commit()

# ------------------------------
# Training thread
# ------------------------------
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
        values = load_card_ai(self.conn)
        self.genome = values["genome"]
        self.total_steps = values["total_steps"]

    def run(self):
        try:
            os.makedirs(MODELS_DIR, exist_ok=True)
            # Gather images
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
                self.progress.emit("No images found in dataset.")
                return

            total_steps_in_run = self.max_steps_per_epoch * self.epochs
            current_step = 0

            for epoch in range(self.epochs):
                combined = list(zip(image_paths, labels))
                random.shuffle(combined)
                steps_in_epoch = min(self.max_steps_per_epoch, len(image_paths))

                for step in range(steps_in_epoch):
                    image_path, class_idx = combined[step]
                    img = Image.open(image_path).convert("RGB").resize(self.target_size, Image.BICUBIC)
                    x = np.expand_dims(np.array(img) / 255.0, axis=0)
                    y = np.zeros((1, len(self.class_labels)))
                    y[0, class_idx] = 1

                    loss, acc = self.model.train_on_batch(x, y)

                    self.progress.emit(
                        f"Genome {self.genome}, Epoch {epoch + 1}/{self.epochs}, "
                        f"Step {step + 1}/{steps_in_epoch}, Image: {os.path.basename(image_path)}, "
                        f"Loss={loss:.4f}, Accuracy={acc:.4f}"
                    )

                    self.image_update.emit(QPixmap(image_path))
                    self.accuracy_update.emit(acc)
                    self.loss_update.emit(loss)
                    self.genome_update.emit(self.genome)

                    current_step += 1
                    self.total_steps += 1
                    self.total_steps_update.emit(self.total_steps)
                    self.progress_bar_update.emit(int(current_step / total_steps_in_run * 100))

                    # Save to DB after each step
                    save_card_ai(self.conn, self.genome, self.total_steps)

                # Save model after each epoch
                model_filename = f'card_predictor_model_genome_{self.genome}_epoch_{epoch+1}.keras'
                self.model.save(os.path.join(MODELS_DIR, model_filename))

                self.genome += 1  # Increment genome after epoch
                save_card_ai(self.conn, self.genome, self.total_steps)

            self.progress.emit("Training complete.")
        except Exception as e:
            self.progress.emit(f"Error during training: {str(e)}")
        finally:
            self.conn.close()

# ------------------------------
# GUI Application
# ------------------------------
class CardPredictorApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TCG Card Predictor")
        self.resize(1000, 700)

        self.conn = connect_db()
        values = load_card_ai(self.conn)
        self.genome = values["genome"]
        self.total_steps = values["total_steps"]

        main_layout = QHBoxLayout()
        # Left layout: image display
        left_layout = QVBoxLayout()
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setScaledContents(True)
        self.image_label.setFixedSize(500, 700)
        left_layout.addWidget(self.image_label)
        main_layout.addLayout(left_layout)

        # Right layout: logs and info
        right_layout = QVBoxLayout()
        self.text_output = QTextEdit()
        self.text_output.setReadOnly(True)
        right_layout.addWidget(self.text_output)

        self.epochs_input = QLineEdit()
        self.epochs_input.setPlaceholderText("Enter number of epochs")
        right_layout.addWidget(self.epochs_input)

        self.accuracy_label = QLabel(f"Accuracy: N/A")
        right_layout.addWidget(self.accuracy_label)
        self.loss_label = QLabel(f"Loss: N/A")
        right_layout.addWidget(self.loss_label)
        self.genome_label = QLabel(f"Genome: {self.genome}")
        right_layout.addWidget(self.genome_label)
        self.total_steps_label = QLabel(f"Total Steps: {self.total_steps}")
        right_layout.addWidget(self.total_steps_label)

        self.progress_bar = QProgressBar()
        right_layout.addWidget(self.progress_bar)

        buttons_layout = QHBoxLayout()
        self.train_button = QPushButton("Train Model")
        self.train_button.clicked.connect(self.train_model)
        buttons_layout.addWidget(self.train_button)
        right_layout.addLayout(buttons_layout)

        main_layout.addLayout(right_layout)
        self.setLayout(main_layout)

        self.dataset_path = DATASET_PATH
        self.target_size = (200, 200)
        self.class_labels = self.get_class_labels()
        self.model = self.load_or_create_model()

    def get_class_labels(self):
        return sorted([d for d in os.listdir(self.dataset_path) if os.path.isdir(os.path.join(self.dataset_path, d))])

    def load_or_create_model(self):
        model_file = os.path.join(MODELS_DIR, 'card_predictor_model.keras')
        if os.path.exists(model_file):
            return load_model(model_file)
        else:
            return self.build_model()

    def build_model(self):
        model = Sequential([
            Input(shape=(200, 200, 3)),
            Conv2D(32, (3,3), activation='relu'),
            MaxPooling2D((2,2)),
            Flatten(),
            Dense(128, activation='relu'),
            Dense(len(self.class_labels), activation='softmax')
        ])
        model.compile(optimizer=Adam(1e-5), loss='categorical_crossentropy', metrics=['accuracy'])
        return model

    def train_model(self):
        epochs_text = self.epochs_input.text()
        try:
            epochs = int(epochs_text)
            if epochs <= 0: epochs = 1
        except:
            epochs = 1
            self.append_text("Invalid epochs input, defaulting to 1.")

        self.training_thread = TrainingThread(
            self.model,
            self.dataset_path,
            self.target_size,
            epochs,
            self.class_labels,
            max_steps_per_epoch=500
        )
        self.training_thread.progress.connect(self.append_text)
        self.training_thread.image_update.connect(self.update_image)
        self.training_thread.accuracy_update.connect(self.update_accuracy)
        self.training_thread.loss_update.connect(self.update_loss)
        self.training_thread.genome_update.connect(self.update_genome)
        self.training_thread.total_steps_update.connect(self.update_total_steps)
        self.training_thread.progress_bar_update.connect(self.update_progress_bar)
        self.training_thread.start()

    def append_text(self, message):
        self.text_output.append(message)

    def update_image(self, pixmap):
        self.image_label.setPixmap(pixmap)

    def update_accuracy(self, acc):
        self.accuracy_label.setText(f"Accuracy: {acc*100:.2f}%")

    def update_loss(self, loss):
        self.loss_label.setText(f"Loss: {loss:.4f}")

    def update_genome(self, genome):
        self.genome_label.setText(f"Genome: {genome}")

    def update_total_steps(self, total_steps):
        self.total_steps_label.setText(f"Total Steps: {total_steps}")

    def update_progress_bar(self, value):
        self.progress_bar.setValue(value)

# ------------------------------
# Main
# ------------------------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = CardPredictorApp()
    window.show()
    sys.exit(app.exec())