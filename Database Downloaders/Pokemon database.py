import os
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin


def get_links(base_url):
    """
    Fetches all links from a base URL.

    :param base_url: URL to scrape for links.
    :return: A list of full URLs.
    """
    response = requests.get(base_url)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    links = [urljoin(base_url, a['href']) for a in soup.find_all('a', href=True)]
    return links


def download_images_from_url(url, output_folder, urls_data):
    """
    Downloads all images from a given URL and records the URLs in a dictionary.

    :param url: The webpage URL to scrape images from.
    :param output_folder: Directory to save downloaded images.
    :param urls_data: Dictionary to store URLs of images.
    """
    response = requests.get(url)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    images = soup.find_all('img')

    for img in images:
        img_url = img.get('src')
        if img_url:
            full_img_url = urljoin(url, img_url)
            try:
                response = requests.get(full_img_url, stream=True)
                if response.status_code == 200:
                    img_name = os.path.basename(full_img_url.split('?')[0])
                    img_path = os.path.join(output_folder, img_name)
                    with open(img_path, 'wb') as img_file:
                        for chunk in response.iter_content(1024):
                            img_file.write(chunk)
                    print(f"Downloaded: {img_name} from {url}")
                    urls_data[url].append(full_img_url)
                else:
                    print(f"Failed to download {full_img_url}. HTTP {response.status_code}")
            except Exception as e:
                print(f"Error downloading {full_img_url}: {e}")


def scrape_and_download_images(base_url, output_folder, output_json):
    """
    Scrapes links from the base URL, downloads images, and saves the URLs in a JSON file.

    :param base_url: The main website URL to start scraping from.
    :param output_folder: Directory to save downloaded images.
    :param output_json: Path to save the URLs JSON file.
    """
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    urls_data = {}
    links = get_links(base_url)
    print(f"Found {len(links)} links on the base page.")

    for link in links:
        print(f"Processing: {link}")
        subfolder = os.path.join(output_folder, link.split('/')[-2])  # Create subfolder for each link
        if not os.path.exists(subfolder):
            os.makedirs(subfolder)
        urls_data[link] = []
        download_images_from_url(link, subfolder, urls_data)

    # Save URLs to JSON
    with open(output_json, 'w', encoding='utf-8') as json_file:
        json.dump(urls_data, json_file, indent=4)
    print(f"Image URLs saved to {output_json}")


if __name__ == "__main__":
    # Base URL to start scraping
    base_url = "https://pkmncards.com/sets/"
    output_directory = "pkmn_images"  # Directory to save all images
    output_json_file = "pokemon_urls.json"  # JSON file to save URLs

    scrape_and_download_images(base_url, output_directory, output_json_file)
