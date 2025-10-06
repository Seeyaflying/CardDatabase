import os
import sqlite3
import random
import numpy as np
from PIL import Image
from tensorflow.keras.models import Sequential, load_model
from tensorflow.keras.layers import Input, Conv2D, MaxPooling2D, Flatten, Dense
from tensorflow.keras.optimizers import Adam

# ------------------------------
# Paths
# ------------------------------
BASE_DIR = r"G:\My Drive\models\CardData"
DB_PATH = os.path.join(BASE_DIR, "skipped_images.sqlite")
DATASET_PATH = os.path.join(BASE_DIR, "Card Database")
MODELS_DIR = os.path.join(BASE_DIR, "models")

# ------------------------------
# DB helpers
# ------------------------------
def connect_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    return conn

def load_card_ai(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT genome, total_steps, full_iteration FROM card_ai WHERE id = 1")
    row = cursor.fetchone()
    return {"genome": row[0], "total_steps": row[1], "full_iteration": row[2]} if row else {"genome":1,"total_steps":0,"full_iteration":0}

def save_card_ai(conn, genome, total_steps, full_iteration):
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO card_ai (id, genome, total_steps, full_iteration)
        VALUES (1, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            genome=excluded.genome,
            total_steps=excluded.total_steps,
            full_iteration=excluded.full_iteration
    """, (genome, total_steps, full_iteration))
    conn.commit()

# ------------------------------
# CNN helpers
# ------------------------------
def init_model(target_size, class_labels):
    os.makedirs(MODELS_DIR, exist_ok=True)
    model_file = os.path.join(MODELS_DIR,'card_predictor_model.keras')
    if os.path.exists(model_file):
        return load_model(model_file)
    model = Sequential([
        Input(shape=(target_size[0],target_size[1],3)),
        Conv2D(32,(3,3),activation='relu'),
        MaxPooling2D((2,2)),
        Flatten(),
        Dense(128,activation='relu'),
        Dense(len(class_labels),activation='softmax')
    ])
    model.compile(optimizer=Adam(1e-5), loss='categorical_crossentropy', metrics=['accuracy'])
    return model

def train_model(model, data_path, target_size, epochs, class_labels, max_steps, conn, genome, total_steps, full_iteration):
    image_paths, labels = [], []
    for subdir, _, files in os.walk(data_path):
        class_name = os.path.basename(subdir)
        if class_name in class_labels:
            idx = class_labels.index(class_name)
            for file in files:
                if file.lower().endswith(('.png','.jpg','.jpeg')):
                    image_paths.append(os.path.join(subdir,file))
                    labels.append(idx)
    if not image_paths: print("No images found."); return total_steps, full_iteration
    steps_per_epoch = min(max_steps,len(image_paths))
    for epoch in range(epochs):
        combined = list(zip(image_paths,labels))
        random.shuffle(combined)
        for step,(img_path,class_idx) in enumerate(combined[:steps_per_epoch]):
            img = Image.open(img_path).convert("RGB").resize(target_size,Image.BICUBIC)
            x = np.expand_dims(np.array(img)/255.0,axis=0)
            y = np.zeros((1,len(class_labels)))
            y[0,class_idx]=1
            loss, acc = model.train_on_batch(x,y)
            total_steps+=1
            full_iteration+=1
            save_card_ai(conn, genome, total_steps, full_iteration)
            print(f"Genome {genome} Epoch {epoch+1}/{epochs} Step {step+1}/{steps_per_epoch} Loss={loss:.4f} Acc={acc:.4f}")
    model.save(os.path.join(MODELS_DIR,f'card_predictor_model_genome_{genome}.keras'))
    print(f"Genome {genome} completed.")
    return total_steps, full_iteration

# ------------------------------
# Main
# ------------------------------
def main():
    target_size = (200,200)
    conn = connect_db()
    values = load_card_ai(conn)
    genome = values["genome"]
    total_steps = values["total_steps"]
    full_iteration = values["full_iteration"]

    class_labels = [d for d in sorted(os.listdir(DATASET_PATH)) if os.path.isdir(os.path.join(DATASET_PATH,d))]
    model = init_model(target_size,class_labels)

    num_genomes = int(input("Number of genomes to train: "))
    epochs = 1
    max_steps_per_epoch = 500

    for _ in range(num_genomes):
        print(f"\nTraining genome {genome}...")
        total_steps, full_iteration = train_model(model, DATASET_PATH, target_size, epochs, class_labels, max_steps_per_epoch, conn, genome, total_steps, full_iteration)
        genome += 1
        full_iteration = 0
        save_card_ai(conn, genome, total_steps, full_iteration)

    conn.close()

if __name__=="__main__":
    main()

