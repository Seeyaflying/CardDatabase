import os
import io
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from tqdm import tqdm  # Import tqdm for progress bar

# Path to your service account key file (the JSON key you downloaded)
SERVICE_ACCOUNT_FILE = 'credentials.json'

# Define the required scope for accessing Google Drive files
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

# Define the root folder ID here. This is the ID of the folder in Google Drive you want to start from.
root_folder_id = '1ZsA3gR3Eny7C-1XQ7uk7LTJ4P0mgqc7M'  # Replace with the actual folder ID

# Define the local folder path where you want to save the files (hardcoded)
local_root_path = r'images'  # Change to your desired folder path

# Authenticate using the service account
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES)

# Build the Google Drive API client
service = build('drive', 'v3', credentials=credentials)


# Function to list files in a specific folder on Google Drive with pagination
def list_drive_files(folder_id=None):
    """
    Lists all files and folders in a given folder on Google Drive, handling pagination.

    Args:
    folder_id (str): The ID of the folder to list files from. If None, lists all files in Drive.

    Returns:
    list: A list of files in the folder.
    """
    query = f"'{folder_id}' in parents" if folder_id else ''
    files = []
    page_token = None

    try:
        while True:
            # Request files from Google Drive
            results = service.files().list(q=query, pageToken=page_token).execute()
            files.extend(results.get('files', []))
            page_token = results.get('nextPageToken')

            # Break if there are no more pages
            if not page_token:
                break
        return files
    except Exception as e:
        print(f"An error occurred while listing files in folder ID {folder_id}: {e}")
        return []


# Function to create a local folder structure based on Google Drive folders
def create_local_folder_structure(folder_id, local_root_path):
    """
    Creates a local folder on your machine to match the folder in Google Drive.

    Args:
    folder_id (str): The ID of the folder to create a local folder for.
    local_root_path (str): The root path on your local machine where you want to save the files.

    Returns:
    str: The local path where the folder has been created.
    """
    # Get folder info from Google Drive
    folder = service.files().get(fileId=folder_id).execute()
    folder_name = folder['name']

    # Create the folder locally if it doesn't exist
    local_folder_path = os.path.join(local_root_path, folder_name)
    if not os.path.exists(local_folder_path):
        os.makedirs(local_folder_path)  # This will create the folder if it doesn't exist

    print(f"Created local folder: {local_folder_path}")
    return local_folder_path


# Function to download a file from Google Drive to a local folder
def download_files(file_id, file_name, local_folder_path):
    """
    Downloads a file from Google Drive to a specified local folder.

    Args:
    file_id (str): The ID of the file to download.
    file_name (str): The name of the file to download.
    local_folder_path (str): The local folder path to save the file.
    """
    file_path = os.path.join(local_folder_path, file_name)

    # Check if file already exists
    if os.path.exists(file_path):
        print(f"File {file_name} already exists, skipping download.")
        return

    # Request the file's data from Google Drive
    request = service.files().get_media(fileId=file_id)

    # Use tqdm for a progress bar while downloading
    with io.FileIO(file_path, 'wb') as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        # Set up a progress bar
        while not done:
            status, done = downloader.next_chunk()
            print(f"Download {int(status.progress() * 100)}% complete for {file_name}.")

    print(f"Downloaded {file_name} to {local_folder_path}")


# Recursive function to download all files and folders from Google Drive
def download_all_files(folder_id=None, local_root_path=None):
    """
    Recursively downloads all files and folders from a specified folder on Google Drive.

    Args:
    folder_id (str): The ID of the folder to start downloading files from.
    local_root_path (str): The local root folder path where files should be saved.
    """
    # List all files in the folder (either root or a subfolder)
    files = list_drive_files(folder_id)

    # Loop through each file/folder
    for file in files:
        # If it's a folder, create a local folder and call the function recursively
        if file['mimeType'] == 'application/vnd.google-apps.folder':
            print(f"Found folder: {file['name']}")
            local_folder_path = create_local_folder_structure(file['id'], local_root_path)
            download_all_files(file['id'], local_folder_path)  # Recursively process subfolders
        else:
            # If it's a file, download it
            print(f"Found file: {file['name']}")
            download_files(file['id'], file['name'], local_root_path)  # Download to the root folder


# Main execution
if __name__ == '__main__':
    # Ensure that the local root folder exists, create it if not
    if not os.path.exists(local_root_path):
        os.makedirs(local_root_path)
        print(f"Created local root folder: {local_root_path}")

    # Starting the download process from the root folder
    print(f"Starting to download from folder ID: {root_folder_id}")
    download_all_files(root_folder_id, local_root_path)
    print("Download completed.")

