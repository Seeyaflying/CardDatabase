import os
from PIL import Image, UnidentifiedImageError
from tqdm import tqdm

def resize_images_to_jpg(input_folder, output_folder, new_size=(800, 800)):
    """
    Resize all image files in the input folder to JPG format and save them to the output folder,
    maintaining the original folder structure.

    Args:
        input_folder (str): Path to the folder containing input images.
        output_folder (str): Path to the root folder to save resized JPG images.
        new_size (tuple): Target size for resizing (width, height).
    """
    # Get a list of all image files in the input folder (recursively)
    image_files = []
    for root, _, files in os.walk(input_folder):
        for file in files:
            if file.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif')):
                image_files.append(os.path.join(root, file))

    skipped_files = []  # To store files that are skipped
    to_process_files = []  # Files that need processing

    # Pre-process the files ahead of time
    for input_path in image_files:
        # Calculate the relative path from the input folder
        relative_path = os.path.relpath(os.path.dirname(input_path), input_folder)

        # Create the corresponding output directory
        output_dir = os.path.join(output_folder, relative_path)
        os.makedirs(output_dir, exist_ok=True)

        # Determine the output file path
        output_file_name = os.path.splitext(os.path.basename(input_path))[0] + ".jpg"
        output_path = os.path.join(output_dir, output_file_name)

        # Add to the process list if file doesn't exist, else add to skipped list
        if os.path.exists(output_path):
            skipped_files.append(input_path)
        else:
            to_process_files.append(input_path)

    # Update the progress bar dynamically to reflect the total number of images
    with tqdm(total=len(image_files), desc="Processing images", unit="file", leave=True, position=0, ncols=100) as pbar:
        for input_path in image_files:
            if input_path in skipped_files:
                # If the file was skipped, update progress bar but do not process
                pbar.update(1)
                continue

            try:
                # Open the image
                with Image.open(input_path) as img:
                    # Resize the image using LANCZOS resampling
                    img_resized = img.resize(new_size, Image.Resampling.LANCZOS)

                    # Convert to RGB if not already in RGB mode
                    if img.mode != 'RGB':
                        img_resized = img_resized.convert('RGB')

                    # Determine the relative path for saving
                    relative_path = os.path.relpath(os.path.dirname(input_path), input_folder)
                    output_dir = os.path.join(output_folder, relative_path)
                    os.makedirs(output_dir, exist_ok=True)
                    output_file_name = os.path.splitext(os.path.basename(input_path))[0] + ".jpg"
                    output_path = os.path.join(output_dir, output_file_name)

                    # Save as JPG
                    img_resized.save(output_path, format="JPEG")

            except UnidentifiedImageError:
                pass  # Skipping invalid image files silently
            except Exception as e:
                tqdm.write(f"Error processing {input_path}: {e}")
            finally:
                pbar.update(1)

    # If there were skipped files, you can print them at the end or handle them as needed
    if skipped_files:
        tqdm.write(f"Skipped {len(skipped_files)} files as they already exist.")

if __name__ == "__main__":
    input_folder = "originals"  # Replace with your input folder path
    output_folder = "data"  # Replace with your output folder path

    # Prompt the user for custom size input
    width = int(input("Enter the desired width (default 800): ") or 800)
    height = int(input("Enter the desired height (default 800): ") or 800)

    resize_images_to_jpg(input_folder, output_folder, new_size=(width, height))
