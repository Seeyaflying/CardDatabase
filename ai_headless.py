import os
import json
import numpy as np
from tensorflow.keras.models import Sequential, load_model
from tensorflow.keras.layers import Input, Conv2D, MaxPooling2D, Flatten, Dense
from tensorflow.keras.optimizers import Adam
from PIL import Image
import random

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

# Training function
def train_model(model, data_path, target_size, epochs, class_labels, max_steps_per_epoch, json_file, genome, total_steps, full_iteration):
    try:
        if not os.path.exists(MODELS_DIR):
            os.makedirs(MODELS_DIR)

        image_paths = []
        labels = []
        for subdir, _, files in os.walk(data_path):
            class_name = os.path.basename(subdir)
            if class_name in class_labels:
                class_index = class_labels.index(class_name)
                for file in files:
                    if file.lower().endswith(('.png', '.jpg', '.jpeg')):  # Only image files
                        image_paths.append(os.path.join(subdir, file))
                        labels.append(class_index)

        if not image_paths:
            print("No images found in the dataset.")
            return total_steps, full_iteration

        total_steps_in_epochs = max_steps_per_epoch * epochs
        steps_in_epoch = min(max_steps_per_epoch, len(image_paths))

        for epoch in range(epochs):
            combined = list(zip(image_paths, labels))
            random.shuffle(combined)

            for step, (image_path, class_index) in enumerate(combined):
                if step >= steps_in_epoch:
                    break

                img = Image.open(image_path).convert("RGB").resize(target_size, Image.BICUBIC)
                img_array = np.array(img) / 255.0
                img_array = np.expand_dims(img_array, axis=0)

                label = np.zeros((1, len(class_labels)))
                label[0, class_index] = 1

                loss, accuracy = model.train_on_batch(img_array, label)

                predicted_class = np.argmax(model.predict(img_array))
                print(f"Genome {genome}, Epoch {epoch+1}/{epochs}, Step {step+1}/{steps_in_epoch}: Image={image_path}, Loss={loss:.4f}, Accuracy={accuracy:.4f}, Predicted Class={class_labels[predicted_class]}")

                total_steps += 1
                full_iteration += 1
                progress_percent = int((total_steps / (total_steps_in_epochs * num_genomes)) * 100)
                print(f"Progress: {progress_percent}%")

                save_values_to_json(json_file, {"genome": genome, "total_steps": total_steps, "full_iteration": full_iteration})

        model_filename = f'card_predictor_model_genome_{genome}.keras'
        model_path = os.path.join(MODELS_DIR, model_filename)
        model.save(model_path)
        print(f"Genome {genome} completed. Model saved at: {model_path}")

        print(f"Genome {genome} training complete.")
        return total_steps, full_iteration
    except Exception as e:
        print(f"Error during training: {str(e)}")
        return total_steps, full_iteration

# Application
def main():
    dataset_path = 'G:/My Drive/Card Database'
    target_size = (200, 200)
    class_labels = []
    for subdir in os.listdir(dataset_path):
        if os.path.isdir(os.path.join(dataset_path, subdir)):
            class_labels.append(subdir)
    class_labels = sorted(class_labels)

    model_file = os.path.join(MODELS_DIR, 'card_predictor_model.keras')
    if os.path.exists(model_file):
        model = load_model(model_file)
    else:
        model = Sequential([
            Input(shape=(200, 200, 3)),
            Conv2D(32, (3, 3), activation='relu'),
            MaxPooling2D((2, 2)),
            Flatten(),
            Dense(128, activation='relu'),
            Dense(len(class_labels), activation='softmax')
        ])
        model.compile(optimizer=Adam(learning_rate=0.00001),
                      loss='categorical_crossentropy',
                      metrics=['accuracy'])

    default_values = {"genome": 1, "total_steps": 0, "full_iteration": 0}
    values = load_values_from_json(VALUES_FILE_PATH, default_values)
    genome = values.get("genome", default_values["genome"])
    total_steps = values.get("total_steps", default_values["total_steps"])
    full_iteration = values.get("full_iteration", default_values["full_iteration"])

    global num_genomes
    num_genomes = int(input("Enter the number of genomes to train: "))

    epochs = 1
    max_steps_per_epoch = 2500

    for i in range(num_genomes):
        print(f"Training genome {i+1}...")
        total_steps, full_iteration = train_model(model, dataset_path, target_size, epochs, class_labels, max_steps_per_epoch, VALUES_FILE_PATH, genome, total_steps, full_iteration)
        genome += 1
        save_values_to_json(VALUES_FILE_PATH, {"genome": genome, "total_steps": total_steps, "full_iteration": 0})
        full_iteration = 0

if __name__ == "__main__":
    main()