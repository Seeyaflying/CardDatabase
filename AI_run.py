import sys
import os
import random
import numpy as np
from PySide6.QtWidgets import QApplication, QWidget, QPushButton, QVBoxLayout, QLabel, QTextEdit, QLineEdit, QHBoxLayout, QProgressBar
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPixmap
from PIL import Image
from tensorflow.keras.models import Sequential, load_model
from tensorflow.keras.layers import Input, Conv2D, MaxPooling2D, Flatten, Dense
from tensorflow.keras.optimizers import Adam
import json

# Paths for saving data
VALUES_FILE_PATH = "G:/My Drive/models/CardData/values.json"
MODELS_DIR = "G:/My Drive/models/CardData"

# JSON Helpers
def load_values_from_json(file_path, default_values):
    """Load values from a JSON file."""
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r') as file:
                return json.load(file)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error loading JSON from {file_path}: {e}")
    return default_values

def save_values_to_json(file_path, values):
    """Save values to a JSON file."""
    try:
        with open(file_path, 'w') as file:
            json.dump(values, file, indent=4)
    except IOError as e:
        print(f"Error saving JSON to {file_path}: {e}")

# Training Thread
class TrainingThread(QThread):
    progress = Signal(str)
    image_update = Signal(QPixmap)
    accuracy_update = Signal(float)
    loss_update = Signal(float)
    progress_bar_update = Signal(int)
    genome_update = Signal(int)
    full_iteration_update = Signal(int)

    def __init__(self, model, data_path, target_size, epochs, class_labels, max_steps_per_epoch, json_file):
        super().__init__()
        self.model = model
        self.data_path = data_path
        self.target_size = target_size
        self.epochs = epochs
        self.class_labels = class_labels
        self.max_steps_per_epoch = max_steps_per_epoch
        self.json_file = json_file
        default_values = {"genome": 1, "full_iteration": 0}
        values = load_values_from_json(json_file, default_values)
        self.genome = values["genome"]
        self.full_iteration = values["full_iteration"]

    def run(self):
        try:
            if not os.path.exists(MODELS_DIR):
                os.makedirs(MODELS_DIR)

            image_paths = []
            labels = []
            for subdir, _, files in os.walk(self.data_path):
                class_name = os.path.basename(subdir)
                if class_name in self.class_labels:
                    class_index = self.class_labels.index(class_name)
                    for file in files:
                        if file.lower().endswith(('.png', '.jpg', '.jpeg')):  # Only image files
                            image_paths.append(os.path.join(subdir, file))
                            labels.append(class_index)

            if not image_paths:
                self.progress.emit("No images found in the dataset.")
                return

            total_steps = self.max_steps_per_epoch * self.epochs
            current_step = 0

            for epoch in range(self.epochs):
                combined = list(zip(image_paths, labels))
                random.shuffle(combined)

                steps_in_epoch = min(self.max_steps_per_epoch, len(image_paths))

                for step in range(steps_in_epoch):
                    image_path, class_index = combined[step]
                    img = Image.open(image_path).convert("RGB").resize(self.target_size, Image.BICUBIC)
                    img_array = np.array(img) / 255.0
                    img_array = np.expand_dims(img_array, axis=0)

                    label = np.zeros((1, len(self.class_labels)))
                    label[0, class_index] = 1

                    loss, accuracy = self.model.train_on_batch(img_array, label)

                    self.image_update.emit(QPixmap(image_path))
                    self.progress.emit(f"Epoch {epoch + 1}/{self.epochs}, Step {current_step + 1}/{total_steps}: Loss={loss:.4f}, Accuracy={accuracy:.4f}")
                    self.accuracy_update.emit(accuracy)
                    self.loss_update.emit(loss)
                    self.genome_update.emit(self.genome)
                    self.full_iteration_update.emit(self.full_iteration)

                    current_step += 1

                    progress_percent = int((current_step / total_steps) * 100)
                    self.progress_bar_update.emit(progress_percent)

                    self.full_iteration += 1
                    save_values_to_json(self.json_file, {"genome": self.genome, "full_iteration": self.full_iteration})

                model_filename = f'card_predictor_model_genome_{self.genome}_epoch_{epoch + 1}_full_iteration_{self.full_iteration}.keras'
                model_path = os.path.join(MODELS_DIR, model_filename)
                self.model.save(model_path)
                self.progress.emit(f"Model saved at: {model_path}")

                self.genome += 1
                save_values_to_json(self.json_file, {"genome": self.genome, "full_iteration": self.full_iteration})
                self.progress.emit(f"Epoch {epoch + 1} completed. Genome updated to: {self.genome}, Full Iteration updated to: {self.full_iteration}")

            self.progress.emit("Training complete.")
        except Exception as e:
            self.progress.emit(f"Error during training: {str(e)}")

# Application
class CardPredictorApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('TCG Card Predictor')
        self.resize(1000, 700)

        main_layout = QHBoxLayout()

        # Left layout for image display
        left_layout = QVBoxLayout()
        self.image_label = QLabel(self)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setScaledContents(True)
        self.image_label.setFixedSize(500, 700)
        left_layout.addWidget(self.image_label, alignment=Qt.AlignCenter)

        # Right layout
        right_layout = QVBoxLayout()
        self.text_output = QTextEdit(self)
        self.text_output.setReadOnly(True)
        right_layout.addWidget(self.text_output)

        self.epochs_input = QLineEdit(self)
        self.epochs_input.setPlaceholderText("Enter number of epochs")
        right_layout.addWidget(self.epochs_input)

        self.accuracy_label = QLabel("Accuracy: N/A", self)
        right_layout.addWidget(self.accuracy_label)

        self.loss_label = QLabel("Loss: N/A", self)
        right_layout.addWidget(self.loss_label)

        self.genome_label = QLabel("Genome: N/A", self)
        right_layout.addWidget(self.genome_label)

        self.full_iteration_label = QLabel("Full Iteration: N/A", self)
        right_layout.addWidget(self.full_iteration_label)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setValue(0)
        right_layout.addWidget(self.progress_bar)

        buttons_layout = QHBoxLayout()
        self.train_button = QPushButton('Train Model', self)
        self.predict_button = QPushButton('Start Prediction', self)
        self.train_button.clicked.connect(self.train_model)
        self.predict_button.clicked.connect(self.start_prediction)
        buttons_layout.addWidget(self.train_button)
        buttons_layout.addWidget(self.predict_button)
        right_layout.addLayout(buttons_layout)

        main_layout.addLayout(left_layout)
        main_layout.addLayout(right_layout)
        self.setLayout(main_layout)

        self.dataset_path = 'G:/My Drive/Card Database'  # Modify this path as needed
        self.target_size = (200, 200)
        self.class_labels = self.get_class_labels()
        self.model = self.load_or_create_model()

        default_values = {"genome": 1, "full_iteration": 0}
        values = load_values_from_json(VALUES_FILE_PATH, default_values)
        self.genome = values["genome"]
        self.full_iteration = values["full_iteration"]
        self.update_genome(self.genome)
        self.update_full_iteration(self.full_iteration)

    def get_class_labels(self):
        labels = []
        for subdir in os.listdir(self.dataset_path):
            if os.path.isdir(os.path.join(self.dataset_path, subdir)):
                labels.append(subdir)
        return sorted(labels)

    def load_or_create_model(self):
        model_file = os.path.join(MODELS_DIR, 'card_predictor_model.keras')
        if os.path.exists(model_file):
            return load_model(model_file)
        else:
            return self.build_model()

    def build_model(self):
        model = Sequential([
            Input(shape=(200, 200, 3)),
            Conv2D(32, (3, 3), activation='relu'),
            MaxPooling2D((2, 2)),
            Flatten(),
            Dense(128, activation='relu'),
            Dense(len(self.class_labels), activation='softmax')
        ])
        model.compile(optimizer=Adam(learning_rate=0.00001),
                      loss='categorical_crossentropy',
                      metrics=['accuracy'])
        return model

    def update_progress(self, message):
        self.text_output.append(message)

    def update_image(self, pixmap):
        self.image_label.setPixmap(pixmap)

    def update_accuracy(self, accuracy):
        self.accuracy_label.setText(f"Accuracy: {accuracy * 100:.2f}%")

    def update_loss(self, loss):
        self.loss_label.setText(f"Loss: {loss:.4f}")

    def update_genome(self, genome):
        self.genome_label.setText(f"Genome: {genome}")

    def update_full_iteration(self, full_iteration):
        self.full_iteration_label.setText(f"Full Iteration: {full_iteration}")

    def update_progress_bar(self, value):
        self.progress_bar.setValue(value)

    def train_model(self):
        # Get the number of epochs from the input field
        epochs_input = self.epochs_input.text()

        # If the input is empty or not a valid integer, set the default value to 1
        if not epochs_input or not epochs_input.isdigit():
            epochs = 1
            self.update_progress("Invalid or empty input for epochs. Using default value of 1 epoch.")
        else:
            epochs = int(epochs_input)
            if epochs <= 0:
                epochs = 1
                self.update_progress("Epochs must be a positive integer. Using default value of 1 epoch.")

        # Proceed with training
        self.training_thread = TrainingThread(
            self.model,
            self.dataset_path,
            self.target_size,
            epochs,
            self.class_labels,
            max_steps_per_epoch=500,
            json_file=VALUES_FILE_PATH
        )

        self.training_thread.progress.connect(self.update_progress)
        self.training_thread.image_update.connect(self.update_image)
        self.training_thread.accuracy_update.connect(self.update_accuracy)
        self.training_thread.loss_update.connect(self.update_loss)
        self.training_thread.genome_update.connect(self.update_genome)
        self.training_thread.full_iteration_update.connect(self.update_full_iteration)
        self.training_thread.progress_bar_update.connect(self.update_progress_bar)
        self.training_thread.start()

    def start_prediction(self):
        self.update_progress("Prediction started!")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = CardPredictorApp()
    window.show()
    sys.exit(app.exec())
