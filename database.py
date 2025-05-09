import os
import shutil
import time
import threading
import random
from queue import Queue
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk
from pymongo import MongoClient

class TCGOrganizer:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("TCG Organizer")
        # Initialize the input and output folders
        self.input_folder = "G:/My Drive/Card Database"
        self.output_folder = "G:/My Drive/Database"
        self.tcg_sets = {}
        self.cards_processed = 0
        self.collection = None
        self.queue = Queue()
        self.progress_bar = None
        self.progress_label = None
        self.image_label = None
        self.set_entry = None
        self.set_name_entry = None
        self.card_entry = None
        self.cards_processed_label = None
        self.create_widgets()
        self.connect_to_database()
        self.load_progress()
        self.populate_tcg_sets()

    def create_widgets(self):
        try:
            # Create the input folder label and entry
            self.input_folder_label = tk.Label(self.root, text="Input Folder:")
            self.input_folder_label.pack()
            self.input_folder_entry = tk.Entry(self.root, width=50)
            self.input_folder_entry.insert(0, self.input_folder)
            self.input_folder_entry.pack()
            # Create the output folder label and entry
            self.output_folder_label = tk.Label(self.root, text="Output Folder:")
            self.output_folder_label.pack()
            self.output_folder_entry = tk.Entry(self.root, width=50)
            self.output_folder_entry.insert(0, self.output_folder)
            self.output_folder_entry.pack()
            # Create the progress bar and label
            self.progress_bar = ttk.Progressbar(self.root, orient=tk.HORIZONTAL, length=200, mode='determinate')
            self.progress_bar.pack()
            self.progress_label = tk.Label(self.root, text="")
            self.progress_label.pack()
            # Create the image label
            self.image_label = tk.Label(self.root)
            self.image_label.pack()
            # Create the set entry
            self.set_label = tk.Label(self.root, text="TCG Set:")
            self.set_label.pack()
            self.set_entry = tk.Entry(self.root)
            self.set_entry.pack()
            # Create the set name entry
            self.set_name_label = tk.Label(self.root, text="Set Name:")
            self.set_name_label.pack()
            self.set_name_entry = tk.Entry(self.root)
            self.set_name_entry.pack()
            # Create the card entry
            self.card_label = tk.Label(self.root, text="Card Name:")
            self.card_label.pack()
            self.card_entry = tk.Entry(self.root)
            self.card_entry.pack()
            # Create the confirm button
            self.confirm_button = tk.Button(self.root, text="Confirm", command=self.confirm_image)
            self.confirm_button.pack()
            # Create the skip button
            self.skip_button = tk.Button(self.root, text="Skip", command=self.skip_image)
            self.skip_button.pack()
            # Create the add new image button
            self.add_new_image_button = tk.Button(self.root, text="Add New Image", command=self.add_new_image)
            self.add_new_image_button.pack()
            # Create the cards processed label
            self.cards_processed_label = tk.Label(self.root, text="Cards Processed: 0")
            self.cards_processed_label.pack()
        except Exception as e:
            print(f"An error occurred while creating the widgets: {e}")

    def connect_to_database(self):
        try:
            # Connect to the MongoDB database
            self.client = MongoClient('mongodb+srv://seeyaflying:Riversong1969@cluster0.7fugd.mongodb.net/')
            self.db = self.client['tcg_database']
            self.collection = self.db['cards']
            print("Connected to database successfully")
        except Exception as e:
            print(f"An error occurred while connecting to the database: {e}")

    def load_progress(self):
        try:
            print("Loading progress from database...")
            # Find all documents in the collection
            documents = self.collection.find()
            # Loop through each document
            for document in documents:
                # Increment the number of cards processed
                self.cards_processed += 1
            # Update the label to display the number of cards processed
            self.cards_processed_label.config(text=f"Cards Processed: {self.cards_processed}")
            print("Progress loaded from database successfully")
        except Exception as e:
            print(f"An error occurred while loading progress from the database: {e}")

    def populate_tcg_sets(self):
        try:
            self.tcg_sets_thread = threading.Thread(target=self._populate_tcg_sets)
            self.tcg_sets_thread.start()
        except Exception as e:
            print(f"An error occurred while starting the TCG sets population thread: {e}")

    def _populate_tcg_sets(self):
        try:
            # Get the total number of folders in the input folder
            total_folders = len(os.listdir(self.input_folder))
            # Initialize the progress counter
            progress_counter = 0
            # Loop through each folder in the input folder
            for folder in os.listdir(self.input_folder):
                # Get the full path of the folder
                folder_path = os.path.join(self.input_folder, folder)
                # Check if the folder is a directory
                if os.path.isdir(folder_path):
                    # Loop through each file in the folder
                    for file in os.listdir(folder_path):
                        # Check if the file is an image
                        if file.endswith(('.jpg', '.png', '.gif', '.webp')):
                            # Check if the image is not already in the TCG sets dictionary
                            if folder in self.tcg_sets and file not in self.tcg_sets[folder]:
                                # Add the image to the TCG sets dictionary
                                self.tcg_sets[folder].append(file)
                            elif folder not in self.tcg_sets:
                                # Add the folder and image to the TCG sets dictionary
                                self.tcg_sets[folder] = [file]
                # Update the progress counter
                progress_counter += 1
                # Update the progress bar and label using a callback function
                self.root.after(0, self.update_progress_bar, progress_counter, total_folders)
            print("TCG sets dictionary populated successfully.")
            # Remove the progress bar and label using a callback function
            self.root.after(0, self.remove_progress_bar)
            # Display the first image
            self.display_random_image()
        except Exception as e:
            print(f"An error occurred while populating the TCG sets dictionary: {e}")

    def update_progress_bar(self, progress_counter, total_folders):
        try:
            # Update the progress bar
            self.progress_bar['value'] = (progress_counter / total_folders) * 100
            # Update the progress label
            self.progress_label['text'] = f"Populating TCG sets dictionary... ({progress_counter}/{total_folders})"
        except Exception as e:
            print(f"An error occurred while updating the progress bar: {e}")

    def remove_progress_bar(self):
        try:
            # Remove the progress bar and label
            self.progress_bar.pack_forget()
            self.progress_label.pack_forget()
        except Exception as e:
            print(f"An error occurred while removing the progress bar: {e}")

    def display_random_image(self):
        try:
            # Get a random folder from the TCG sets dictionary
            random_folder = random.choice(list(self.tcg_sets.keys()))
            # Get a random image from the random folder
            random_image = random.choice(self.tcg_sets[random_folder])
            # Get the full path of the random image
            random_image_path = os.path.join(self.input_folder, random_folder, random_image)
            # Open the random image
            image = Image.open(random_image_path)
            # Resize the image to fit the label
            image.thumbnail((400, 400))
            # Convert the image to a PhotoImage
            photo = ImageTk.PhotoImage(image)
            # Display the image on the label
            self.image_label.config(image=photo)
            self.image_label.image = photo
            # Add the image to the queue
            self.queue.put(random_image_path)
        except Exception as e:
            print(f"An error occurred while displaying the random image: {e}")

    def confirm_image(self):
        try:
            print("Confirming the current image...")
            # Get the set name and card name from the entry fields
            set_name = self.set_name_entry.get()
            card_name = self.card_entry.get()
            # Check if the set name and card name are empty
            if not set_name and not card_name:
                # Ask the user to confirm if the set name and card name are empty
                confirm = messagebox.askyesno("Confirm", "Set name and card name are empty. Are you sure you want to confirm?")
                if confirm:
                    # Add the image to the database with empty set name and card name
                    self.collection.insert_one({
                        'image_filename': os.path.basename(self.queue.get()),
                        'tcg_set': self.set_entry.get(),
                      'set_name': '',
                        'card_name': '',
                      'modified_time': time.time()
                    })
                    # Remove the image from the queue
                    self.queue.task_done()
                    # Display the next random image
                    self.display_random_image()
                else:
                    # Do not add the image to the database
                    print("Image not confirmed.")
            else:
                # Add the image to the database with the set name and card name
                self.collection.insert_one({
                    'image_filename': os.path.basename(self.queue.get()),
                    'tcg_set': self.set_entry.get(),
                  'set_name': set_name,
                    'card_name': card_name,
                 'modified_time': time.time()
                })
                # Remove the image from the queue
                self.queue.task_done()
                # Display the next random image
                self.display_random_image()
            print("Image confirmed successfully.")
        except Exception as e:
            print(f"An error occurred while confirming the current image: {e}")

    def skip_image(self):
        try:
            print("Skipping the current image...")
            # Remove the image from the queue
            self.queue.task_done()
            # Display the next random image
            self.display_random_image()
            print("Image skipped successfully.")
        except Exception as e:
            print(f"An error occurred while skipping the current image: {e}")

    def add_new_image(self):
        try:
            # Open a file dialog to select the new image
            new_image_path = filedialog.askopenfilename(filetypes=[("Image Files", ".jpg.png.gif.webp")])
            # Check if the new image is selected
            if new_image_path:
                # Display the new image on the label
                image = Image.open(new_image_path)
                image.thumbnail((400, 400))
                photo = ImageTk.PhotoImage(image)
                self.image_label.config(image=photo)
                self.image_label.image = photo
                # Clear the entry fields
                self.set_entry.delete(0, tk.END)
                self.set_name_entry.delete(0, tk.END)
                self.card_entry.delete(0, tk.END)
                # Add the image to the queue
                self.queue.put(new_image_path)
                print("New image added.")
        except Exception as e:
            print(f"An error occurred while adding a new image: {e}")

    def start_monitor_thread(self):
        try:
            print("Starting monitor thread...")
            # Create a new thread to run the monitor function
            self.monitor_thread = threading.Thread(target=self.monitor)
            # Start the thread
            self.monitor_thread.start()
            print("Monitor thread started successfully")
        except Exception as e:
            print(f"An error occurred while starting the monitor thread: {e}")

    def monitor(self):
        try:
            print("Monitoring queue and processing images...")
            # Loop indefinitely
            while True:
                # Check if there are any images in the queue
                if not self.queue.empty():
                    # Get the next image from the queue
                    image_path = self.queue.get()
                    # Process the image
                    self.process_image(image_path)
                    # Remove the image from the queue
                    self.queue.task_done()
                # Wait for 1 second before checking the queue again
                time.sleep(1)
        except Exception as e:
            print(f"An error occurred while monitoring the queue and processing images: {e}")

    def process_image(self, image_path):
        try:
            print(f"Processing image: {image_path}...")
            # Insert the image data into the MongoDB database
            self.collection.insert_one({
                'image_filename': os.path.basename(image_path),
                'tcg_set': self.set_entry.get(),
               'set_name': '',
                'card_name': '',
               'modified_time': time.time()
            })
            # Create the output folder if it does not exist
            output_folder = os.path.join(self.output_folder, self.set_entry.get())
            os.makedirs(output_folder, exist_ok=True)
            # Copy the image to the output folder
            shutil.copy2(image_path, os.path.join(output_folder, os.path.basename(image_path)))
            # Increment the number of cards processed
            self.cards_processed += 1
            # Update the label to display the number of cards processed
            self.cards_processed_label.config(text=f"Cards Processed: {self.cards_processed}")
            # Save the progress to the database
            self.save_progress()
            print(f"Image processed and saved to database: {image_path}")
        except Exception as e:
            print(f"An error occurred while processing the image: {e}")

    def save_progress(self):
        try:
            print("Saving progress to database...")
            # Update the document with the current number of cards processed
            self.collection.update_one({'tcg_set': self.set_entry.get()}, {'$set': {'cards_processed': self.cards_processed}}, upsert=True)
            print("Progress saved to database successfully")
        except Exception as e:
            print(f"An error occurred while saving progress: {e}")

    def run(self):
        try:
            # Start the GUI event loop
            self.root.mainloop()
            print("GUI event loop started successfully")
        except Exception as e:
            print(f"An error occurred while running the GUI event loop: {e}")

if __name__ == "__main__":
    app = TCGOrganizer()
    app.run()