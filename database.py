import os
import shutil
from PIL import Image, ImageTk
import tkinter as tk
from tkinter import filedialog, messagebox
import threading
import time
from pymongo import MongoClient
from queue import Queue
import random

class TCGOrganizer:
    def __init__(self):
        try:
            print("Initializing TCG Organizer...")
            # Initialize the GUI window
            self.root = tk.Tk()
            self.root.title("TCG Organizer")
            self.root.geometry("800x600")

            # Initialize variables to store the input and output folders
            self.input_folder = "G:/My Drive/Card Database"
            self.output_folder = "G:/My Drive/Database"

            # Initialize variables to store the current image index and list of images
            self.image_index = 0
            self.images = []

            # Initialize a dictionary to store the TCG sets
            self.tcg_sets = {}

            # Initialize a queue to store the images to be processed
            self.queue = Queue()

            # Initialize a MongoDB client to store the card data
            self.client = MongoClient('mongodb+srv://seeyaflying:Riversong1969@cluster0.7fugd.mongodb.net/')
            self.db = self.client['tcg_database']
            self.collection = self.db['cards']

            # Initialize a variable to store the number of cards processed
            self.cards_processed = 0

            # Create GUI components
            # Label to display the current image
            self.image_label = tk.Label(self.root)
            self.image_label.pack(pady=20)

            # Label and entry field for the TCG set
            self.set_label = tk.Label(self.root, text="TCG Set:", font=("Arial", 14))
            self.set_label.pack(pady=5)
            self.set_entry = tk.Entry(self.root, width=50, font=("Arial", 14))
            self.set_entry.pack(pady=5)

            # Label and entry field for the set name
            self.set_name_label = tk.Label(self.root, text="Set Name:", font=("Arial", 14))
            self.set_name_label.pack(pady=5)
            self.set_name_entry = tk.Entry(self.root, width=50, font=("Arial", 14))
            self.set_name_entry.pack(pady=5)

            # Label and entry field for the card name
            self.card_label = tk.Label(self.root, text="Card Name:", font=("Arial", 14))
            self.card_label.pack(pady=5)
            self.card_entry = tk.Entry(self.root, width=50, font=("Arial", 14))
            self.card_entry.pack(pady=5)

            # Button to confirm the current image
            self.confirm_button = tk.Button(self.root, text="Confirm", command=self.confirm_image, width=20, height=2)
            self.confirm_button.pack(pady=10)

            # Button to skip the current image
            self.skip_button = tk.Button(self.root, text="Skip", command=self.skip_image, width=20, height=2)
            self.skip_button.pack(pady=10)

            # Button to add a new image
            self.add_button = tk.Button(self.root, text="Add New Image", command=self.add_new_image, width=20, height=2)
            self.add_button.pack(pady=10)

            # Label to display the number of cards processed
            self.cards_processed_label = tk.Label(self.root, text=f"Cards Processed: {self.cards_processed}",
                                                  font=("Arial", 14))
            self.cards_processed_label.pack(pady=5)

            # Initialize the current TCG set
            self.current_tcg_set = None

            # Initialize the monitor thread
            self.monitor_thread = None

            # Load the progress from the database
            self.load_progress()

            # Populate the TCG sets dictionary
            self.populate_tcg_sets()

            # Display a random image
            self.display_random_image()

            # Start the monitor thread
            self.start_monitor_thread()

            print("TCG Organizer initialized successfully.")
        except Exception as e:
            print(f"An error occurred during initialization: {e}")

    # Method to populate the TCG sets dictionary
    def populate_tcg_sets(self):
        try:
            print("Populating TCG sets dictionary...")
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
            print("TCG sets dictionary populated successfully.")
        except Exception as e:
            print(f"An error occurred while populating the TCG sets dictionary: {e}")

    # Method to display a random image
    def display_random_image(self):
        try:
            print("Displaying a random image...")
            # Check if there are any TCG sets
            if self.tcg_sets:
                # Select a random TCG set
                random_folder = random.choice(list(self.tcg_sets.keys()))
                # Select a random image from the TCG set
                random_image = random.choice(self.tcg_sets[random_folder])
                # Get the full path of the image
                image_path = os.path.join(self.input_folder, random_folder, random_image)
                # Open the image
                image = Image.open(image_path)
                # Resize the image to fit the label
                image.thumbnail((400, 400))
                # Convert the image to a PhotoImage
                photo = ImageTk.PhotoImage(image)
                # Display the image on the label
                self.image_label.config(image=photo)
                self.image_label.image = photo
                # Clear the entry fields
                self.set_entry.delete(0, tk.END)
                self.set_name_entry.delete(0, tk.END)
                self.card_entry.delete(0, tk.END)
                # Insert the TCG set into the entry field
                self.set_entry.insert(tk.END, random_folder)
                # Add the image to the queue
                self.queue.put(image_path)
                print(f"Random image displayed: {random_image}")
            else:
                print("No TCG sets found.")
        except Exception as e:
            print(f"An error occurred while displaying a random image: {e}")

    # Method to confirm the current image
    def confirm_image(self):
        try:
            print("Confirming the current image...")
            # Get the set name and card name from the entry fields
            set_name = self.set_name_entry.get()
            card_name = self.card_entry.get()
            # Check if the set name and card name are empty
            if not set_name and not card_name:
                # Ask the user to confirm if the set name and card name are empty
                confirm = messagebox.askyesno("Confirm", "Are you sure you want to confirm the TCG set without specifying the set name and card name?")
                if confirm:
                    # Get the image path from the queue
                    image_path = self.queue.get()
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
                    print("Image confirmed and saved to database.")
                else:
                    # Do nothing if the user does not confirm
                    print("Image confirmation cancelled.")
            else:
                # Get the image path from the queue
                image_path = self.queue.get()
                # Insert the image data into the MongoDB database
                self.collection.insert_one({
                    'image_filename': os.path.basename(image_path),
                    'tcg_set': self.set_entry.get(),
                  'set_name': set_name,
                    'card_name': card_name,
                  'modified_time': time.time()
                })
                # Create the output folder if it does not exist
                output_folder = os.path.join(self.output_folder, self.set_entry.get(), set_name)
                os.makedirs(output_folder, exist_ok=True)
                # Copy the image to the output folder
                shutil.copy2(image_path, os.path.join(output_folder, os.path.basename(image_path)))
                # Increment the number of cards processed
                self.cards_processed += 1
                # Update the label to display the number of cards processed
                self.cards_processed_label.config(text=f"Cards Processed: {self.cards_processed}")
                # Save the progress to the database
                self.save_progress()
                print("Image confirmed and saved to database with set name and card name.")
        except Exception as e:
            print(f"An error occurred while confirming the image: {e}")

    # Method to skip the current image
    def skip_image(self):
        try:
            print("Skipping the current image...")
            # Get the image path from the queue
            image_path = self.queue.get()
            # Display the next image
            self.display_random_image()
            print("Image skipped.")
        except Exception as e:
            print(f"An error occurred while skipping the image: {e}")

    # Method to add a new image
    def add_new_image(self):
        try:
            print("Adding a new image...")
            # Open a file dialog to select the new image
            new_image_path = filedialog.askopenfilename(filetypes=[("Image Files", ".jpg.png.gif.webp")])
            if new_image_path:
                # Open the new image
                image = Image.open(new_image_path)
                # Resize the image to fit the label
                image.thumbnail((400, 400))
                # Convert the image to a PhotoImage
                photo = ImageTk.PhotoImage(image)
                # Display the image on the label
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

    # Method to start the monitor thread
    def start_monitor_thread(self):
        try:
            print("Starting monitor thread...")
            # Create a new thread to run the monitor function
            self.monitor_thread = threading.Thread(target=self.monitor)
            # Start the thread
            self.monitor_thread.start()
            print("Monitor thread started successfully.")
        except Exception as e:
            print(f"An error occurred while starting the monitor thread: {e}")

    # Method to monitor the queue and process images
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

    # Method to process an image
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

    # Method to load the progress from the database
    def load_progress(self):
        try:
            print("Loading progress from database...")
            # Get the number of cards processed from the database
            self.cards_processed = self.collection.count_documents({})
            print(f"Progress loaded from database: {self.cards_processed} cards processed")
        except Exception as e:
            print(f"An error occurred while loading the progress from the database: {e}")

    # Method to save the progress to the database
    def save_progress(self):
        try:
            print("Saving progress to database...")
            # Insert the progress into the database
            self.collection.insert_one({
                'cards_processed': self.cards_processed,
              'modified_time': time.time()
            })
            print("Progress saved to database successfully")
        except Exception as e:
            print(f"An error occurred while saving the progress to the database: {e}")

    # Method to run the GUI
    def run(self):
        try:
            print("Running GUI...")
            # Start the GUI event loop
            self.root.mainloop()
            print("GUI started successfully")
        except Exception as e:
            print(f"An error occurred while running the GUI: {e}")

if __name__ == "__main__":
    # Create an instance of the TCGOrganizer class
    tcg_organizer = TCGOrganizer()
    # Run the GUI
    tcg_organizer.run()