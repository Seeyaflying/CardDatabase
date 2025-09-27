import os
import random
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.image import Image
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.core.window import Window
from kivy.uix.popup import Popup
import shutil
import platform

# -----------------------
# Folder setup
# -----------------------
if platform.system() == "Linux" and "ANDROID_ARGUMENT" in os.environ:
    # Running on Android
    from android.storage import primary_external_storage_path
    BASE_PATH = os.path.join(primary_external_storage_path(), "MEGA", "ImageReviewer")
else:
    # Running on PC for testing
    BASE_PATH = os.path.join(os.getcwd(), "ImageReviewer")

YES_PATH = os.path.join(BASE_PATH, "Yes")
NO_PATH = os.path.join(BASE_PATH, "No")

os.makedirs(BASE_PATH, exist_ok=True)
os.makedirs(YES_PATH, exist_ok=True)
os.makedirs(NO_PATH, exist_ok=True)

# -----------------------
# App class
# -----------------------
class ImageReviewer(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self.image_files = []
        self.current_image = None
        self.history = []

        self.image_widget = Image(allow_stretch=True, keep_ratio=True)
        self.add_widget(self.image_widget)

        # Buttons
        button_layout = BoxLayout(size_hint_y=0.2)
        self.btn_yes = Button(text="Yes", background_color=(0, 1, 0, 1))
        self.btn_no = Button(text="No", background_color=(1, 0, 0, 1))
        self.btn_back = Button(text="Back", background_color=(0.5, 0.5, 0.5, 1))
        self.btn_refresh = Button(text="Refresh", background_color=(0, 0.5, 1, 1))

        self.btn_yes.bind(on_press=lambda x: self.move_image(YES_PATH))
        self.btn_no.bind(on_press=lambda x: self.move_image(NO_PATH))
        self.btn_back.bind(on_press=lambda x: self.undo_last())
        self.btn_refresh.bind(on_press=lambda x: self.load_images())

        button_layout.add_widget(self.btn_yes)
        button_layout.add_widget(self.btn_no)
        button_layout.add_widget(self.btn_back)
        button_layout.add_widget(self.btn_refresh)

        self.add_widget(button_layout)

        # Load first batch
        self.load_images()

    def load_images(self):
        """Load all unreviewed images from base folder."""
        self.image_files = [
            os.path.join(BASE_PATH, f)
            for f in os.listdir(BASE_PATH)
            if f.lower().endswith((".png", ".jpg", ".jpeg")) and
               f not in os.listdir(YES_PATH) and
               f not in os.listdir(NO_PATH)
        ]
        if not self.image_files:
            self.show_popup("No Images", "No unreviewed images found.")
        else:
            self.show_next_image()

    def show_next_image(self):
        if self.image_files:
            self.current_image = random.choice(self.image_files)
            self.image_widget.source = self.current_image
            self.image_widget.reload()
        else:
            self.current_image = None
            self.image_widget.source = ""

    def move_image(self, target_folder):
        if self.current_image:
            filename = os.path.basename(self.current_image)
            new_path = os.path.join(target_folder, filename)
            shutil.move(self.current_image, new_path)
            self.history.append((new_path, self.current_image))
            self.image_files.remove(self.current_image)
            self.show_next_image()

    def undo_last(self):
        if self.history:
            last_path, original_path = self.history.pop()
            shutil.move(last_path, original_path)
            self.image_files.append(original_path)
            self.show_next_image()

    def show_popup(self, title, message):
        layout = BoxLayout(orientation="vertical")
        layout.add_widget(Label(text=message))
        popup = Popup(title=title, content=layout, size_hint=(0.6, 0.4))
        popup.open()

# -----------------------
# Run the app
# -----------------------
class ImageReviewerApp(App):
    def build(self):
        Window.clearcolor = (1, 1, 1, 1)
        return ImageReviewer()

if __name__ == "__main__":
    ImageReviewerApp().run()
