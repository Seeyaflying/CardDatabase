import os
import re
import requests
import sqlite3
import logging
import platform
import zipfile
import io
import tarfile
import sys
from datetime import date
from concurrent.futures import ThreadPoolExecutor
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from tqdm import tqdm

# Imports for Colored Console Output
try:
    from colorama import Fore, Style, init

    # Initialize colorama for cross-platform compatibility
    init(autoreset=True)
except ImportError:
    # Define placeholder variables if colorama isn't available
    class ColorPlaceholder:
        def __getattr__(self, name):
            return ''


    Fore = Style = ColorPlaceholder()
    print("Warning: 'colorama' library not found. Terminal output will not be colored.")

# Selenium Imports
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, NoSuchElementException

# --- CONFIGURATION: Paths ---
GECKODRIVER_DIR = "utils"
GECKODRIVER_FILENAME = "geckodriver.exe" if platform.system() == "Windows" else "geckodriver"
GECKODRIVER_PATH = os.path.join(GECKODRIVER_DIR, GECKODRIVER_FILENAME)

# --- USER CONFIGURATION (ACTION REQUIRED) ---
BASE_SAVE_DIR = "G:/My Drive/New Cards"
CHECK_FOLDER = "G:/My Drive/Card Database"
GITHUB_TOKEN = "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"  # MUST BE UPDATED

# --- CONFIGURATION: Settings & DB ---
MAX_DOWNLOAD_WORKERS = 40
PAGE_LOAD_TIMEOUT = 12
DB_FILE = "skipped_images.sqlite"
TABLE_NAME = "skipped_images"
LANGUAGE_TYPE = "japanese"
LOG_DIR = "log"
# Single audit file to capture all logging data
SINGLE_LOG_FILE = os.path.join(LOG_DIR, f"{date.today().strftime('%Y-%m-%d')}_downloader_audit.log")

# --- CONFIGURATION: SITE DATA (YOU MUST KEEP total_pages UPDATED) ---
SITES = {
    "Battle Spirits": {"id": 79, "total_pages": 145},
    "Buddy Fight": {"id": 71, "total_pages": 233},
    "Build Divide": {"id": 61, "total_pages": 176},
    "Cardfight Vanguard": {"id": 44, "total_pages": 554},
    "Chaos": {"id": 50, "total_pages": 433},
    "Detective Conan": {"id": 84, "total_pages": 26},
    "DB Heroes": {"id": 73, "total_pages": 202},
    "DB Super Divers": {"id": 93, "total_pages": 13},
    "DBZ Super Fusion World": {"id": 82, "total_pages": 29},
    "Digimon": {"id": 37, "total_pages": 118},
    "Duel Masters": {"id": 36, "total_pages": 464},
    "Fate-Grand Order Arcade": {"id": 39, "total_pages": 42},
    "Final Fantasy": {"id": 56, "total_pages": 233},
    "Fire Emblem Cipher": {"id": 33, "total_pages": 74},
    "Godzilla Card Game": {"id": 99, "total_pages": 5},
    "Gundam": {"id": 94, "total_pages": 10},
    "Hololive": {"id": 88, "total_pages": 29},
    "Kamen Rider Battle Ganba Legends": {"id": 86, "total_pages": 28},
    "Kamen Rider Battle Ganbarizing": {"id": 85, "total_pages": 99},
    "Kantai Collection Kancolle Arcade": {"id": 60, "total_pages": 1},
    "Love Live": {"id": 95, "total_pages": 23},
    "Lycee Over Ture": {"id": 48, "total_pages": 185},
    "One Piece": {"id": 67, "total_pages": 88},
    "Osica": {"id": 68, "total_pages": 68},
    "Pokemon": {"id": 35, "total_pages": 629},
    "Precious Memories": {"id": 41, "total_pages": 416},
    "Prism Connect": {"id": 59, "total_pages": 89},
    "Rebirth for you": {"id": 38, "total_pages": 402},
    "Shadowverse Evolve": {"id": 62, "total_pages": 110},
    "Takashi Murakami Jellyfish Eyes": {"id": 91, "total_pages": 3},
    "The Quintessential Quintuplets": {"id": 87, "total_pages": 20},
    "Trails Series": {"id": 92, "total_pages": 8},
    "Ultraman": {"id": 90, "total_pages": 14},
    "Union Arena": {"id": 74, "total_pages": 166},
    "Vividz": {"id": 70, "total_pages": 12},
    "Weiss Schwarz": {"id": 31, "total_pages": 1324},
    "Weiss Schwarz Blau": {"id": 72, "total_pages": 97},
    "Weiss Schwarz Rose": {"id": 96, "total_pages": 22},
    "Wixoss": {"id": 43, "total_pages": 344},
    "Xross Stars": {"id": 98, "total_pages": 5},
    "Yugioh": {"id": 34, "total_pages": 797},
    "Yugioh Rush Duel": {"id": 49, "total_pages": 116},
    "Z-X Zillions over enemy X": {"id": 42, "total_pages": 441},
}

# --- COMMON PAGINATION SELECTORS TO TEST (Improved) ---
COMMON_PAGINATION_SELECTORS = [
    # Primary selector targeting the last page link item
    "li.go_last a",

    # Secondary generic options (kept for fallback)
    "div.list_page_nav a",
    "div.list_page_nav ul li a",
    "ul.pagination li:last-child a",
    "a[href*='p=']",
]


# --- Setup Functions ---

def setup_directories(log_dir, base_save_dir, check_folder):
    """Creates necessary directories."""
    os.makedirs(log_dir, exist_ok=True)
    os.makedirs(GECKODRIVER_DIR, exist_ok=True)
    os.makedirs(base_save_dir, exist_ok=True)
    os.makedirs(check_folder, exist_ok=True)


def setup_logger(log_dir):
    """Sets up the primary logger to output to the console (colored) AND a single file."""
    logger = logging.getLogger("japanese_downloader")
    logger.setLevel(logging.INFO)

    # Custom Formatter for colored console output
    class ColoredFormatter(logging.Formatter):
        FORMAT = '%(asctime)s - %(levelname)s - %(message)s'

        LOG_COLORS = {
            logging.WARNING: Fore.YELLOW + Style.BRIGHT,
            logging.ERROR: Fore.RED,
            logging.CRITICAL: Fore.RED + Style.BRIGHT,
            logging.INFO: Fore.GREEN,
            logging.DEBUG: Fore.CYAN,
        }

        def format(self, record):
            # Apply color only to the console stream
            if isinstance(self._fmt, str) and not ('FileHandler' in str(self)):
                color = self.LOG_COLORS.get(record.levelno, '')
                original_message = super().format(record)
                if record.levelno >= logging.WARNING:
                    return f"{color}{original_message}{Style.RESET_ALL}"
                return original_message

            return super().format(record)

    # Standard formatter for the file (no color ANSI codes)
    file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')
    colored_formatter = ColoredFormatter()

    if not logger.handlers:
        # 1. Stream Handler (Console/Terminal Output with colors)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(colored_formatter)
        logger.addHandler(console_handler)

        # 2. File Handler (Single Log File Output)
        file_handler = logging.FileHandler(SINGLE_LOG_FILE, encoding="utf-8")
        # FILE: Set to INFO to capture only key progress, warnings, and errors
        # Note: We rely on print() for download/skip status now
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

    return logger


# --- GECKODRIVER DOWNLOAD/INSTALLATION ---

def get_latest_geckodriver_info(logger):
    """Fetches the latest Geckodriver version and download URL using a GitHub token."""
    api_url = "https://api.github.com/repos/mozilla/geckodriver/releases/latest"
    logger.debug(f"Attempting to connect to GitHub API at: {api_url}")
    session = requests.Session()
    retry = Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retry))
    headers = {}
    if GITHUB_TOKEN and GITHUB_TOKEN != "YOUR_PERSONAL_ACCESS_TOKEN_HERE":
        headers['Authorization'] = f'token {GITHUB_TOKEN}'
    try:
        response = session.get(api_url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        latest_version = data.get('tag_name', 'v0.0.0').lstrip('v')
        logger.debug(f"Latest Geckodriver version found: {latest_version}")

        system = platform.system()
        python_arch = platform.architecture()[0]
        is_64_bit = ("64" in python_arch)

        if system == "Windows":
            target = "win64.zip" if is_64_bit else "win32.zip"
        elif system == "Linux":
            target = "linux64.tar.gz"
        elif system == "Darwin":
            target = "macos.tar.gz"
        else:
            raise ValueError(f"Unsupported OS: {system}")

        logger.debug(f"Target OS/Arch match: {target}")

        download_url = None
        for asset in data.get('assets', []):
            if target in asset['name']:
                download_url = asset['browser_download_url']
                break
        if not download_url: raise ValueError(
            f"Could not find matching asset '{target}' for Geckodriver v{latest_version}.")
        return latest_version, download_url
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch latest geckodriver info from GitHub API: {e}")
        return None, None
    except ValueError as e:
        logger.error(f"Asset matching error: {e}")
        return None, None


def install_geckodriver(logger):
    """Checks and installs/updates Geckodriver."""
    latest_version, download_url = get_latest_geckodriver_info(logger)
    if not latest_version or not download_url:
        logger.critical("Could not get latest Geckodriver info. Cannot proceed.")
        return False
    VERSION_FILE = os.path.join(GECKODRIVER_DIR, "geckodriver_version.txt")
    installed_version = "0.0.0"
    if os.path.exists(VERSION_FILE):
        try:
            with open(VERSION_FILE, 'r') as f:
                installed_version = f.read().strip()
        except Exception:
            installed_version = "0.0.0"
    if os.path.exists(GECKODRIVER_PATH) and installed_version == latest_version:
        logger.info(f"Geckodriver v{installed_version} is already installed and up-to-date. Skipping download.")
        return True
    logger.warning(f"Local driver v{installed_version} is missing or old. Downloading v{latest_version}.")
    for f in [GECKODRIVER_PATH, VERSION_FILE]:
        if os.path.exists(f):
            try:
                os.remove(f)
            except OSError as e:
                logger.error(f"Error cleaning up file {f}: {e}. Please manually delete {f}")
                return False
    try:
        r = requests.get(download_url, stream=True, timeout=30)
        r.raise_for_status()
        logger.debug(f"Starting download from: {download_url}")
        if download_url.endswith('.zip'):
            file_obj = zipfile.ZipFile(io.BytesIO(r.content))
            extract_member = GECKODRIVER_FILENAME
        else:
            file_obj = tarfile.open(fileobj=io.BytesIO(r.content), mode="r:gz")
            executables = [name for name in file_obj.getnames() if GECKODRIVER_FILENAME in name]
            extract_member = executables[0] if executables else None
            if not extract_member: raise Exception("Could not find the executable inside the downloaded archive.")
        with file_obj:
            with open(GECKODRIVER_PATH, "wb") as f:
                member_content = file_obj.read(extract_member) if download_url.endswith(
                    '.zip') else file_obj.extractfile(extract_member).read()
                f.write(member_content)
        logger.info(f"Successfully installed Geckodriver v{latest_version} to: {GECKODRIVER_PATH}")
        if platform.system() != "Windows": os.chmod(GECKODRIVER_PATH, 0o755)
        with open(VERSION_FILE, 'w') as f:
            f.write(latest_version)
        return True
    except Exception as e:
        logger.error(f"Error during Geckodriver download/extraction: {e}")
        return False


# --- SQL (READ ONLY) ---

def load_skipped_image_ids(logger):
    """Read Japanese skipped image names from DB."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(f"SELECT image_name FROM {TABLE_NAME} WHERE language=?", (LANGUAGE_TYPE,))
        result = {str(row[0]) for row in cursor.fetchall()}
        conn.close()
        logger.debug(f"Database connection closed.")
        logger.info(f"Loaded {len(result)} skipped Japanese image names from database.")
        return result
    except sqlite3.OperationalError as e:
        logger.error(f"CRITICAL SQL ERROR: Database structure is invalid. Error: {e}")
        return set()
    except Exception as e:
        logger.error(f"Error reading skipped images: {e}")
        return set()


# --- Selenium & Dynamic Page Count ---

def setup_driver():
    """Initializes a new Firefox WebDriver instance."""
    options = webdriver.FirefoxOptions()
    options.add_argument("--headless")
    service = FirefoxService(executable_path=GECKODRIVER_PATH)
    if not os.path.exists(GECKODRIVER_PATH):
        raise FileNotFoundError(f"Geckodriver not found at: {GECKODRIVER_PATH}. Installation failed.")
    return webdriver.Firefox(service=service, options=options)


def get_total_pages(driver, site_id, selector, logger):
    """Finds the total number of pages using a specific CSS selector."""
    first_page_url = f"https://tcgrepublic.com/category/category_page_{site_id}.html?p=1"
    max_page = 1

    try:
        driver.get(first_page_url)
        logger.debug(f"Checking URL: {first_page_url} with selector: '{selector}'")

        # 10s timeout for dynamic elements check
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
        )

        page_elements = driver.find_elements(By.CSS_SELECTOR, selector)

        for element in page_elements:
            text = element.text.strip()

            if not text and element.tag_name in ('div', 'ul', 'ol'):
                for link in element.find_elements(By.TAG_NAME, 'a'):
                    try:
                        page_num = int(link.text.strip())
                        if page_num > max_page: max_page = page_num
                    except ValueError:
                        continue
            else:
                try:
                    page_num = int(text)
                    if page_num > max_page: max_page = page_num
                except ValueError:
                    continue

        if max_page > 1: return max_page

    except TimeoutException:
        logger.debug(f"Selector '{selector}' timed out or not present.")
        return 1
    except Exception as e:
        logger.debug(f"Error checking selector '{selector}': {e}")
        return 1


def find_pagination_selector(driver, site_id, logger):
    """Iterates through common selectors to find the best page count."""
    max_pages_found = 1

    logger.info("Attempting to dynamically find the last page number...")

    for selector in COMMON_PAGINATION_SELECTORS:
        pages = get_total_pages(driver, site_id, selector, logger)

        if pages > max_pages_found:
            max_pages_found = pages
            logger.debug(f"-> Found better selector: '{selector}' yielding {max_pages_found} pages.")

    return max_pages_found


# --- Scraping ---

def scrape_page(driver, logger, site_name, site_id, page):
    """
    Scrapes a single page. Logs the page URL if zero images are found after timeout.
    """
    url = f"https://tcgrepublic.com/category/category_page_{site_id}.html?p={page}"
    image_urls = set()

    try:
        driver.get(url)

        # Wait for image elements to be present (using PAGE_LOAD_TIMEOUT = 12s)
        WebDriverWait(driver, PAGE_LOAD_TIMEOUT).until(
            EC.presence_of_element_located((By.TAG_NAME, "img"))
        )

        for img in driver.find_elements(By.TAG_NAME, "img"):
            src = img.get_attribute("src")
            # Filter for the specific image URL format
            if src and re.match(r"https://tcgrepublic\.com/media/binary/\d+/\d+/\d+/\d+\.jpg\.l2_thumbnail\.jpg", src):
                # Save the full-resolution image URL
                image_urls.add(src.replace(".l2_thumbnail.jpg", ""))

    except TimeoutException:
        logger.warning(
            f"[{site_name} Page {page}] Timed out waiting for image elements (Page likely has no cards). URL: {url}"
        )
    except Exception as e:
        logger.error(f"[{site_name} Page {page}] Unknown error during scraping: {e}")

    # LOGIC TO TRACK EMPTY PAGES
    if not image_urls:
        if 'TimeoutException' not in str(sys.exc_info()[1]):
            logger.warning(f"[{site_name} Page {page}] Returned 0 images. URL: {url}")

    return image_urls


def scrape_images(logger, site_name, site_data):
    """Coordinates sequential scraping of all pages for a site using a single driver."""
    total_pages = site_data["total_pages"]
    driver = None
    try:
        driver = setup_driver()
        logger.debug("WebDriver successfully started for main scraping loop.")
    except Exception as e:
        logger.critical(f"Driver setup failed: {e}")
        return set()

    all_urls = set()
    logger.info(f"Starting sequential scrape for {site_name} across {total_pages} pages.")

    try:
        # Tqdm handles the terminal progress
        for page in tqdm(range(1, total_pages + 1), desc=f"Scraping {site_name}", unit="page"):
            urls = scrape_page(driver, logger, site_name, site_data["id"], page)
            all_urls.update(urls)
    finally:
        if driver: driver.quit()
        logger.debug("WebDriver quit after scraping.")

    logger.info(f"Finished scraping {site_name}. Found {len(all_urls)} potential image URLs.")
    return all_urls


# --- Download ---

def download_image(url, skipped_image_ids, existing_images, site_name, save_folder, logger):
    """Downloads a single image, skipping if already present or in the skip list."""
    image_name = url.split("/")[-1]

    # Check 1: Skip if image name is in the database skip list
    if image_name in skipped_image_ids:
        # Using print() for terminal only output
        print(f"[{site_name}] Skipping (DB): {image_name}")
        return

    # Check 2: Skip if image name is in the combined set of existing files
    if image_name in existing_images:
        # Using print() for terminal only output
        print(f"[{site_name}] Skipping (Exists): {image_name}")
        return

    save_path = os.path.join(save_folder, image_name)
    session = requests.Session()
    retry = Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    try:
        response = session.get(url, headers={"User-Agent": "Mozilla/5.0"}, stream=True, timeout=10)
        if response.status_code == 200:
            with open(save_path, "wb") as f:
                for chunk in response.iter_content(1024): f.write(chunk)
            # SUCCESSFUL DOWNLOAD - Now using print() for terminal-only output
            print(f"[{site_name}] Downloaded: {image_name}")
        else:
            # FAILED DOWNLOAD - Keep logger.warning() for audit file
            logger.warning(f"[{site_name}] Failed ({response.status_code}): {url}")
    except requests.exceptions.RequestException as e:
        logger.error(f"[{site_name}] Network/Request Error downloading {url}: {e}")
    except Exception as e:
        logger.error(f"[{site_name}] Unexpected Error downloading {url}: {e}")


# --- Main Application Function ---

def main():
    """The main entry point for the scraper logic."""

    # 1. Setup Directories & Loggers
    setup_directories(LOG_DIR, BASE_SAVE_DIR, CHECK_FOLDER)
    logger = setup_logger(LOG_DIR)

    if GITHUB_TOKEN == "YOUR_PERSONAL_ACCESS_TOKEN_HERE":
        logger.critical("GitHub Token not set. Script will likely fail due to API rate limit.")
        print("\n\n*** CRITICAL ERROR ***\nGitHub Token is not set. Please update it.\n**********************")
        return

    # 2. Install Geckodriver
    if not install_geckodriver(logger):
        logger.critical("Failed to install/verify Geckodriver. Exiting script.")
        print("\n\n*** CRITICAL ERROR ***\nGeckodriver installation/verification failed.\n**********************")
        return

    # 3. Load Skips
    skipped_image_ids = load_skipped_image_ids(logger)
    existing_check_images = set(os.listdir(CHECK_FOLDER))
    logger.debug(f"Total images in CHECK_FOLDER: {len(existing_check_images)}")

    # --- Process All Sites ---
    for site_name, site_data in SITES.items():
        logger.info(f"\n--- Processing Site: {site_name} (ID: {site_data['id']}) ---")
        site_id = site_data["id"]

        # Save the hardcoded/last known value before running dynamic check
        hardcoded_page_count = site_data["total_pages"]

        # --- PHASE 0: DYNAMIC CHECK & ALERT ---
        temp_driver = None
        dynamic_page_count = hardcoded_page_count
        check_ran = False

        # Conditional Check: Skip the dynamic check if the hardcoded value is small
        if hardcoded_page_count <= 5:
            logger.info(
                f"[{site_name}] Hardcoded page count is {hardcoded_page_count}. Skipping dynamic check for speed/stability.")
        else:
            check_ran = True
            try:
                temp_driver = setup_driver()

                # Run the dynamic check
                dynamic_page_count = find_pagination_selector(temp_driver, site_id, logger)

            except Exception as e:
                logger.error(f"Dynamic check failed. Error: {e}")
            finally:
                if temp_driver:
                    temp_driver.quit()
                    logger.debug("Temporary WebDriver quit.")

        # 🎯 Report the number found, if the check ran
        if check_ran and dynamic_page_count > 1:
            logger.info(f"[{site_name}] Dynamic check **found {dynamic_page_count} pages**.")

        # 💡 COLORAMA: Total Pages Alert - RED
        if dynamic_page_count > hardcoded_page_count:
            # Print highly visible alert to the terminal
            alert_message = f"!!! CRITICAL UPDATE NEEDED FOR: {site_name} !!!\n"
            alert_message += f"!!! DYNAMIC CHECK FOUND {dynamic_page_count} PAGES (Hardcoded is {hardcoded_page_count}) !!!\n"
            alert_message += "!!! PLEASE UPDATE YOUR SITES CONFIGURATION !!!"

            # Use print for maximum visibility outside the logger formatting
            print(f"\n{Fore.RED + Style.BRIGHT}{'=' * 80}")
            print(alert_message)
            print(f"{'=' * 80}{Style.RESET_ALL}\n")

            # Log the alert to the single log file in RED using ANSI codes
            ANSI_RED = "\033[31m"
            ANSI_RESET = "\033[0m"

            # We use logger.critical here to ensure the log level is captured
            logger.critical(
                f"{ANSI_RED}[{site_name}] NEW MAX PAGES FOUND: {dynamic_page_count} (Hardcoded Used: {hardcoded_page_count}){ANSI_RESET}"
            )

        elif dynamic_page_count == 1 and hardcoded_page_count > 1 and check_ran:
            # Only warn if the check fails AND the expected count is > 1
            logger.warning(
                f"[{site_name}] Dynamic check failed to find pagination (returned 1). Using hardcoded count.")

        # Finalize the page count used for scraping: ALWAYS use the hardcoded/last known value
        site_data["total_pages"] = hardcoded_page_count

        # LOG the final plan to the terminal AND the single file
        logger.info(
            f"[{site_name}] **Final Page Count Determined:** {site_data['total_pages']} pages (Using Hardcoded Value).")

        # --- SETUP FOR DOWNLOAD ---
        save_folder = os.path.join(BASE_SAVE_DIR, site_name)
        os.makedirs(save_folder, exist_ok=True)
        existing_site_images = set(os.listdir(save_folder))
        combined_existing_images = existing_check_images.union(existing_site_images)
        logger.info(f"Found {len(combined_existing_images)} total existing images across all folders to skip.")

        # --- PHASE 1 & 2: SCRAPE AND DOWNLOAD ---
        urls = scrape_images(logger, site_name, site_data)

        if not urls:
            logger.warning(f"Skipping download for {site_name} as no URLs were scraped.")
            continue

        logger.info(f"Starting parallel download for {site_name} with {len(urls)} unique URLs.")
        download_tasks = [
            (u, skipped_image_ids, combined_existing_images, site_name, save_folder, logger)
            for u in urls
        ]

        with ThreadPoolExecutor(max_workers=MAX_DOWNLOAD_WORKERS) as executor:
            list(tqdm(executor.map(lambda p: download_image(*p), download_tasks),
                      total=len(download_tasks),
                      desc=f"Downloading {site_name}",
                      unit="images"))

        logger.info(f"Finished processing site: {site_name}.")


if __name__ == "__main__":
    main()