import asyncio
import json
import os
import random
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote, quote, urlunparse

import requests
import nodriver as uc


# ============================================================
# CONFIGURATION
# ============================================================

BASE_URL = "https://www.ccgtrader.net"
GAMES_URL = "https://www.ccgtrader.net/games/"

BROWSER_PATH = (
    r"C:\Users\seeya\AppData\Local\Vivaldi\Application\vivaldi.exe"
)

OUTPUT_ROOT = Path(
    r"G:\My Drive\CCG Trader"
)

MIN_DELAY = 0.1
MAX_DELAY = 1.0

MIN_PAGE_DELAY = 1.0
MAX_PAGE_DELAY = 2.0

MAX_RETRIES = 3

DISCOVERY_ONLY = False

GAME_PAGE_WAIT = 4
SET_PAGE_WAIT = 5

SET_DISCOVERY_RETRIES = 3

MANIFEST_NAME = "_download_manifest.json"
PROGRESS_NAME = "_harvest_progress.json"


# ============================================================
# VERBOSE LOGGING — everything prints, nothing is silent
# ============================================================

def log(msg):
    print(msg, flush=True)


def log_step(msg):
    log(f"  >> {msg}")


def log_card(msg):
    log(f"        >> {msg}")


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
})


# ============================================================
# GENERAL HELPERS
# ============================================================

def polite_delay():
    delay = random.uniform(MIN_DELAY, MAX_DELAY)
    log_card(f"Waiting {delay:.1f}s before next download...")
    time.sleep(delay)


def page_delay():
    delay = random.uniform(MIN_PAGE_DELAY, MAX_PAGE_DELAY)
    log_step(f"Page delay: {delay:.1f}s...")
    time.sleep(delay)


def safe_filename(name):
    if not name:
        name = "Unknown Card"

    name = unquote(str(name))
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = re.sub(r"[\x00-\x1f]", "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    name = name.rstrip(". ")

    if not name:
        name = "Unknown Card"

    return name[:180]


def safe_folder_name(name):
    return safe_filename(name)


def normalize_url(url):
    if not url:
        return None

    return urljoin(BASE_URL, url)


def manifest_key(card):
    card_id = card.get("id")

    if card_id:
        return f"id:{card_id}"

    return f"url:{card.get('card_url', '')}"


# ============================================================
# URL QUOTING — fixes the latin-1 codec error
# ============================================================

def _quote_url(url):
    if not url:
        return url

    parts = urlparse(url)

    quoted_path = quote(parts.path, safe="/%")
    quoted_query = quote(parts.query, safe="=&%")

    return urlunparse((
        parts.scheme,
        parts.netloc,
        quoted_path,
        parts.params,
        quoted_query,
        parts.fragment,
    ))


# ============================================================
# MANIFEST / PROGRESS
# ============================================================

def load_json(path):
    if not path.exists():
        log_step(f"No existing file at {path.name} — starting fresh")
        return {}

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            log_step(f"Loaded {path.name} ({len(data)} entries)")
            return data

    except Exception as e:
        log_step(f"WARNING: Could not read {path.name}: {e}")

    return {}


def save_json(path, data):
    temp_path = path.with_suffix(path.suffix + ".tmp")

    with temp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    os.replace(temp_path, path)
    log_step(f"Saved {path.name}")


def load_progress():
    return load_json(OUTPUT_ROOT / PROGRESS_NAME)


def save_progress(progress):
    save_json(OUTPUT_ROOT / PROGRESS_NAME, progress)


# ============================================================
# IMAGE VALIDATION
# ============================================================

def is_valid_image_response(response):
    if response.status_code != 200:
        log_card(f"Invalid: HTTP {response.status_code}")
        return False

    content_type = (
        response.headers
        .get("Content-Type", "")
        .lower()
        .split(";")[0]
        .strip()
    )

    if not content_type.startswith("image/"):
        log_card(f"Invalid: Content-Type '{content_type}' is not an image")
        return False

    if not response.content:
        log_card("Invalid: Empty body")
        return False

    if len(response.content) < 1000:
        log_card(f"Invalid: Only {len(response.content)} bytes (<1000)")
        return False

    data = response.content[:32]

    if data.startswith(b"\xff\xd8\xff"):
        return True

    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return True

    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return True

    if (
        len(data) >= 12
        and data[:4] == b"RIFF"
        and data[8:12] == b"WEBP"
    ):
        return True

    return True


def get_image_extension(image_url, content_type):
    parsed = urlparse(image_url or "")
    path = parsed.path.lower()

    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".bmp"):
        if path.endswith(ext):
            if ext == ".jpeg":
                return ".jpg"
            return ext

    content_type = (content_type or "").lower()

    if "jpeg" in content_type:
        return ".jpg"
    if "png" in content_type:
        return ".png"
    if "webp" in content_type:
        return ".webp"
    if "gif" in content_type:
        return ".gif"
    if "avif" in content_type:
        return ".avif"

    return ".jpg"


def data_uri_extension(image_url):
    match = re.search(r"data:image/([a-zA-Z0-9.+-]+)", image_url)

    if not match:
        return ".jpg"

    mime_type = match.group(1).lower()

    if mime_type in ("png", "jpeg", "jpg", "gif", "webp", "avif", "bmp"):
        if mime_type == "jpeg":
            return ".jpg"
        return f".{mime_type}"

    return ".jpg"


def card_image_extension(image_url):
    if not image_url:
        return ".jpg"

    if image_url.startswith("data:"):
        return data_uri_extension(image_url)

    return get_image_extension(image_url, "")


# ============================================================
# FIND GAMES ON /games/
# ============================================================

async def find_games_on_page(page):
    log_step("Scanning /games/ page for game links...")

    links = await page.select_all('a[href*="/games/"]')
    games = {}

    for link in links:
        try:
            attrs = getattr(link, "attrs", None)

            if not attrs:
                continue

            href = attrs.get("href")

            if not href:
                continue

            href = normalize_url(href)

            parsed = urlparse(href)
            path = parsed.path.rstrip("/")

            if not path.startswith("/games/"):
                continue

            remainder = path[len("/games/"):].strip("/")

            if not remainder:
                continue

            parts = [p for p in remainder.split("/") if p]

            if len(parts) != 1:
                continue

            slug = parts[0]

            if not slug:
                continue

            try:
                name = await link.text
            except Exception:
                name = ""

            name = (name or "").strip()

            if not name:
                name = slug.replace("-", " ").title()

            games[href] = {
                "name": name,
                "url": href,
                "slug": slug,
            }

        except Exception:
            continue

    games_list = sorted(games.values(), key=lambda x: x["name"].lower())
    log_step(f"Found {len(games_list)} games on page")

    return games_list


# ============================================================
# DISCOVER SETS INSIDE ONE GAME
# ============================================================

async def discover_sets(page, game):
    game_url = game["url"]
    game_slug = game["slug"]

    log("")
    log("=" * 70)
    log(f"ENTERING GAME: {game['name']}")
    log(f"URL: {game_url}")
    log("=" * 70)

    log_step(f"Loading game page: {game_url}")
    await page.get(game_url)
    log_step(f"Waiting {GAME_PAGE_WAIT}s for page to render...")
    await asyncio.sleep(GAME_PAGE_WAIT)

    log_step(f"Scanning for set links under /games/{game_slug}/...")
    links = await page.select_all(f'a[href*="/games/{game_slug}/"]')

    sets = {}

    for link in links:
        try:
            attrs = getattr(link, "attrs", None)

            if not attrs:
                continue

            href = attrs.get("href")

            if not href:
                continue

            href = normalize_url(href)

            parsed = urlparse(href)
            path = parsed.path.rstrip("/")

            prefix = f"/games/{game_slug}/"

            if not path.startswith(prefix):
                continue

            remainder = path[len(prefix):].strip("/")

            if not remainder:
                continue

            if "/" in remainder:
                continue

            set_slug = remainder

            try:
                name = await link.text
            except Exception:
                name = ""

            name = (name or "").strip()

            if not name:
                name = set_slug.replace("-", " ").title()

            sets[href] = {
                "name": name,
                "url": href,
                "slug": set_slug,
                "game_name": game["name"],
                "game_url": game_url,
            }

        except Exception:
            continue

    sets_list = sorted(sets.values(), key=lambda x: x["name"].lower())

    log(f"Sets discovered: {len(sets_list)}")

    for s in sets_list:
        log(f"    - {s['name']}  ({s['url']})")

    return sets_list


# ============================================================
# DISCOVER CARDS INSIDE ONE SET
# ============================================================

async def discover_cards(page, set_info):
    set_url = set_info["url"]

    for attempt in range(1, SET_DISCOVERY_RETRIES + 1):
        log("")
        log(f"    Discovering cards in '{set_info['name']}' "
            f"(attempt {attempt}/{SET_DISCOVERY_RETRIES})")

        try:
            log_step(f"Loading set page: {set_url}")
            await page.get(set_url)
            log_step(f"Waiting {SET_PAGE_WAIT}s for cards to render...")
            await asyncio.sleep(SET_PAGE_WAIT)

            set_name = None

            try:
                set_name = await page.evaluate("""
                    (() => {
                        const h1 = document.querySelector("h1");
                        return h1 ? h1.innerText.trim() : "";
                    })()
                """)
            except Exception:
                pass

            if not set_name:
                set_name = set_info["name"]

            set_name = set_name.strip()
            log_step(f"Set name from page: '{set_name}'")

            log_step("Extracting card data from DOM...")
            raw_json = await page.evaluate("""
                (() => {

                    const elements = Array.from(
                        document.querySelectorAll('a[href*="/card/"]')
                    );

                    const cards = elements.map((a) => {

                        const img = a.querySelector("img");

                        const titleElement = a.querySelector(
                            ".MuiImageListItemBar-title"
                        );

                        const subtitleElement = a.querySelector(
                            ".MuiImageListItemBar-subtitle"
                        );

                        return {
                            href: a.href || "",

                            image_src: img
                                ? (
                                    img.currentSrc ||
                                    img.src ||
                                    img.getAttribute("src") ||
                                    img.getAttribute("data-src") ||
                                    img.getAttribute("data-lazy-src") ||
                                    ""
                                )
                                : "",

                            alt: img
                                ? (img.getAttribute("alt") || "")
                                : "",

                            title: titleElement
                                ? titleElement.innerText.trim()
                                : "",

                            rarity: subtitleElement
                                ? subtitleElement.innerText.trim()
                                : ""
                        };

                    });

                    return JSON.stringify(cards);

                })()
            """)

            if not raw_json:
                log_step("Browser returned no card data")

                if attempt < SET_DISCOVERY_RETRIES:
                    retry_delay = random.uniform(5, 8)
                    log_step(f"Retrying in {retry_delay:.1f}s...")
                    await asyncio.sleep(retry_delay)

                continue

            try:
                raw_cards = json.loads(raw_json)
            except Exception as e:
                log_step(f"ERROR parsing browser JSON: {e}")

                if attempt < SET_DISCOVERY_RETRIES:
                    retry_delay = random.uniform(5, 8)
                    log_step(f"Retrying in {retry_delay:.1f}s...")
                    await asyncio.sleep(retry_delay)

                continue

            log_step(f"Raw card elements found: {len(raw_cards)}")

            cards = {}

            for raw in raw_cards:
                try:
                    card_url = (raw.get("href") or "").strip()

                    if not card_url:
                        continue

                    card_url = normalize_url(card_url)

                    match = re.search(r"/card/(\d+)", card_url)
                    card_id = match.group(1) if match else None

                    image_url = (raw.get("image_src") or "").strip()

                    if image_url:
                        image_url = normalize_url(image_url)

                    card_name = (raw.get("title") or raw.get("alt") or "").strip()

                    if not card_name:
                        path_parts = urlparse(card_url).path.strip("/").split("/")

                        if len(path_parts) >= 3:
                            card_name = path_parts[-1].replace("-", " ").title()
                        else:
                            card_name = f"Card {card_id or 'Unknown'}"

                    rarity = (raw.get("rarity") or "").strip()

                    card = {
                        "id": card_id,
                        "name": card_name,
                        "rarity": rarity,
                        "card_url": card_url,
                        "image_url": image_url,
                    }

                    cards[manifest_key(card)] = card

                except Exception as e:
                    log_step(f"WARNING processing card: {e}")
                    continue

            cards_list = list(cards.values())

            cards_with_images = sum(
                1 for card in cards_list if card.get("image_url")
            )
            cards_without_images = len(cards_list) - cards_with_images

            log(f"    Cards discovered: {len(cards_list)}")
            log(f"    With image URLs:   {cards_with_images}")
            log(f"    Without image URLs: {cards_without_images}")

            if cards_list:
                log("")
                log("    First 5 cards:")
                for card in cards_list[:5]:
                    log(f"    CARD: {card['name']}")
                    log(f"        ID:    {card.get('id')}")
                    log(f"        Image: {card.get('image_url')}")
                    log(f"        Rarity: {card.get('rarity')}")

                if len(cards_list) > 5:
                    log(f"    ... {len(cards_list) - 5} more")

                log("")

                return {
                    **set_info,
                    "name": set_name,
                    "cards": cards_list,
                }

            log("    No usable cards were parsed.")

            if attempt < SET_DISCOVERY_RETRIES:
                retry_delay = random.uniform(5, 8)
                log(f"    Retrying in {retry_delay:.1f}s...")
                await asyncio.sleep(retry_delay)

        except Exception as e:
            log(f"    ERROR discovering cards: {e}")

            if attempt < SET_DISCOVERY_RETRIES:
                retry_delay = random.uniform(5, 8)
                log(f"    Retrying in {retry_delay:.1f}s...")
                await asyncio.sleep(retry_delay)

    return {
        **set_info,
        "name": set_info["name"],
        "cards": [],
        "error": "No cards found after retries",
    }


# ============================================================
# DOWNLOAD ONE IMAGE
# ============================================================

def download_image(card, output_path, set_url):
    image_url = card.get("image_url")

    if not image_url:
        log_card("No image URL")
        return {"status": "failed", "error": "No image URL"}

    # ------------------------------------------------
    # Handle embedded base64 data URIs
    # ------------------------------------------------

    if image_url.startswith("data:"):
        log_card("Image is an embedded data URI — decoding base64...")

        try:
            import base64 as _base64

            header, b64data = image_url.split(",", 1)
            img_bytes = _base64.b64decode(b64data)

            if not img_bytes:
                log_card("Empty data URI payload")
                return {"status": "failed", "error": "Empty data URI payload"}

            temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
            temp_path.parent.mkdir(parents=True, exist_ok=True)

            with temp_path.open("wb") as f:
                f.write(img_bytes)

            if not temp_path.exists() or temp_path.stat().st_size < 1000:
                try:
                    temp_path.unlink()
                except Exception:
                    pass
                log_card("Data URI image too small")
                return {"status": "failed", "error": "Data URI image too small"}

            os.replace(temp_path, output_path)

            content_type = f"image/{output_path.suffix.lstrip('.')}"

            log_card(f"Data URI decoded to {output_path.name} "
                     f"({output_path.stat().st_size} bytes)")

            return {
                "status": "downloaded",
                "size": output_path.stat().st_size,
                "content_type": content_type,
            }

        except Exception as e:
            log_card(f"Data URI decode failed: {e}")
            return {"status": "failed", "error": f"Data URI decode failed: {e}"}

    # ------------------------------------------------
    # Normal HTTP download — quote URL and Referer
    # ------------------------------------------------

    headers = {
        "Referer": _quote_url(set_url),
        "User-Agent": session.headers["User-Agent"],
        "Accept": (
            "image/avif,image/webp,"
            "image/apng,image/svg+xml,"
            "image/*,*/*;q=0.8"
        ),
    }

    temporary_statuses = {408, 425, 429, 500, 502, 503, 504}

    for attempt in range(1, MAX_RETRIES + 1):
        log_card(f"GET {_quote_url(image_url)} (attempt {attempt}/{MAX_RETRIES})")

        try:
            response = session.get(
                _quote_url(image_url),
                headers=headers,
                timeout=45
            )

            log_card(f"HTTP {response.status_code}, "
                     f"Content-Type: {response.headers.get('Content-Type', '')}")

            if is_valid_image_response(response):
                content_type = response.headers.get("Content-Type", "")

                temp_path = output_path.with_suffix(output_path.suffix + ".tmp")

                with temp_path.open("wb") as f:
                    f.write(response.content)

                if not temp_path.exists() or temp_path.stat().st_size < 1000:
                    try:
                        temp_path.unlink()
                    except Exception:
                        pass
                    raise RuntimeError("Image was empty or too small")

                os.replace(temp_path, output_path)

                log_card(f"Saved to {output_path.name} "
                         f"({output_path.stat().st_size} bytes)")

                return {
                    "status": "downloaded",
                    "size": output_path.stat().st_size,
                    "content_type": content_type,
                }

            status = response.status_code

            if status in temporary_statuses:
                log_card(f"Temporary HTTP {status} — will retry")

                if attempt < MAX_RETRIES:
                    wait = 3 * attempt
                    log_card(f"Retry in {wait}s...")
                    time.sleep(wait)
                    continue

            return {
                "status": "failed",
                "error": (
                    f"HTTP {status}, "
                    f"Content-Type: "
                    f"{response.headers.get('Content-Type', '')}"
                )
            }

        except Exception as e:
            log_card(f"Download error (attempt {attempt}/{MAX_RETRIES}): {e}")

            if "latin-1" in str(e):
                log_card(f">>> image_url:  {image_url!r}")
                log_card(f">>> quoted url: {_quote_url(image_url)!r}")
                log_card(f">>> referer:    {set_url!r}")
                log_card(f">>> quot ref:   {_quote_url(set_url)!r}")

            if attempt < MAX_RETRIES:
                wait = 3 * attempt
                log_card(f"Retry in {wait}s...")
                time.sleep(wait)
            else:
                return {"status": "failed", "error": str(e)}

    return {"status": "failed", "error": "Maximum retries exceeded"}


# ============================================================
# DOWNLOAD ONE SET
# ============================================================

def download_set(set_data):
    game_name = set_data["game_name"]
    set_name = set_data["name"]
    set_url = set_data["url"]
    cards = set_data.get("cards", [])

    game_folder = OUTPUT_ROOT / safe_folder_name(game_name)
    set_folder = game_folder / safe_folder_name(set_name)

    log_step(f"Creating folder: {set_folder}")
    set_folder.mkdir(parents=True, exist_ok=True)

    manifest_path = set_folder / MANIFEST_NAME
    manifest = load_json(manifest_path)

    results = {
        "downloaded": 0,
        "skipped": 0,
        "failed": 0,
        "failures": [],
    }

    log("")
    log("-" * 70)
    log(f"SET: {set_name}")
    log(f"Game: {game_name}")
    log(f"URL: {set_url}")
    log(f"Cards in set: {len(cards)}")
    log("-" * 70)

    for index, card in enumerate(cards, start=1):
        card_id = card.get("id")
        card_name = card.get("name")
        image_url = card.get("image_url")

        log(f"    [{index}/{len(cards)}] {card_name} (id={card_id})")

        if not image_url:
            log_card("No image URL — skipping")
            results["skipped"] += 1
            continue

        key = manifest_key(card)

        # Skip already-downloaded files
        if key in manifest and manifest[key].get("status") == "downloaded":
            log_card("Already in manifest — skipping")
            results["skipped"] += 1
            continue

        # Build output path with the correct extension
        ext = card_image_extension(image_url)
        output_path = set_folder / f"{safe_filename(card_name)}{ext}"

        # Skip if file already exists
        if output_path.exists() and output_path.stat().st_size >= 1000:
            manifest[key] = {
                "status": "downloaded",
                "file": output_path.name,
            }
            log_card(f"File already exists — skipping ({output_path.name})")
            results["skipped"] += 1
            continue

        if DISCOVERY_ONLY:
            manifest[key] = {"status": "discovered"}
            log_card("Discovery-only mode — not downloading")
            results["skipped"] += 1
            continue

        result = download_image(card, output_path, set_url)

        if result["status"] == "downloaded":
            manifest[key] = {
                "status": "downloaded",
                "file": output_path.name,
                "size": result.get("size"),
                "content_type": result.get("content_type"),
            }
            results["downloaded"] += 1
            log_card(f"DOWNLOADED -> {output_path.name}")
        else:
            manifest[key] = {
                "status": "failed",
                "error": result.get("error"),
            }
            results["failed"] += 1
            results["failures"].append(
                {
                    "card": card_name,
                    "id": card_id,
                    "error": result.get("error"),
                }
            )
            log_card(f"FAILED: {result.get('error')}")

        polite_delay()

    save_json(manifest_path, manifest)

    log("")
    log(f"SET COMPLETE: {set_name}")
    log(f"    Downloaded: {results['downloaded']}")
    log(f"    Skipped:    {results['skipped']}")
    log(f"    Failed:     {results['failed']}")

    if results["failures"]:
        log("")
        log("    Failures:")
        for failure in results["failures"][:10]:
            log(f"        - {failure['card']}: {failure['error']}")

    return results


# ============================================================
# MAIN LOOP
# ============================================================

async def main():
    log("=" * 70)
    log("CCG TRADER HARVESTER")
    log("=" * 70)

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    progress = load_progress()
    processed_games = progress.get("processed_games", {})

    # Fix corrupted/legacy progress where processed_games is a list
    if not isinstance(processed_games, dict):
        log("WARNING: processed_games was not a dict — resetting it")
        processed_games = {}
        progress["processed_games"] = processed_games

    log(f"Previously processed games: {len(processed_games)}")

    log(f"Starting browser: {BROWSER_PATH}")
    browser = await uc.start(
        browser_executable_path=BROWSER_PATH,
        headless=False,
    )

    try:
        log(f"Opening {GAMES_URL}")
        page = await browser.get(GAMES_URL)

        log(f"Waiting {GAME_PAGE_WAIT}s for games page to render...")
        await asyncio.sleep(GAME_PAGE_WAIT)

        while True:
            games = await find_games_on_page(page)

            unprocessed = [
                game
                for game in games
                if game["url"] not in processed_games
            ]

            log("")
            log(f"Games on page: {len(games)}")
            log(f"Unprocessed:   {len(unprocessed)}")

            if not unprocessed:
                log("")
                log("All games on this page are already processed.")
                log("Reloading games page...")
                await page.get(GAMES_URL)
                await asyncio.sleep(GAME_PAGE_WAIT)

                games = await find_games_on_page(page)
                unprocessed = [
                    game
                    for game in games
                    if game["url"] not in processed_games
                ]

                if not unprocessed:
                    log("")
                    log("No unprocessed games found after reload.")
                    log("Harvest complete!")
                    break

            game = unprocessed[0]

            log("")
            log(f"Processing game: {game['name']}")
            log(f"URL: {game['url']}")

            sets = await discover_sets(page, game)

            if not sets:
                log("")
                log("No sets discovered for this game.")
                processed_games[game["url"]] = {
                    "name": game["name"],
                    "sets": 0,
                    "status": "no_sets",
                }
                progress["processed_games"] = processed_games
                save_progress(progress)
                continue

            for set_info in sets:
                set_data = await discover_cards(page, set_info)

                if not set_data.get("cards"):
                    log(f"    No cards for set: {set_info['name']}")
                    continue

                download_set(set_data)
                page_delay()

            processed_games[game["url"]] = {
                "name": game["name"],
                "sets": len(sets),
                "status": "complete",
            }

            progress["processed_games"] = processed_games
            save_progress(progress)

            log("")
            log(f"Game complete: {game['name']}")
            log(f"Total processed games: {len(processed_games)}")

            page_delay()

    finally:
        log("Stopping browser...")
        browser.stop()


if __name__ == "__main__":
    asyncio.run(main())
