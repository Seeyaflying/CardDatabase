import asyncio
import json
import os
import random
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote

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

# ------------------------------------------------------------
# Download timing
# ------------------------------------------------------------

MIN_DELAY = 1.0
MAX_DELAY = 2.0

# Delay between pages/sets/games
MIN_PAGE_DELAY = 2.0
MAX_PAGE_DELAY = 4.0

MAX_RETRIES = 3

# ------------------------------------------------------------
# Testing
# ------------------------------------------------------------

# True = discover only
# False = actually download images
DISCOVERY_ONLY = False

# ------------------------------------------------------------
# Page loading
# ------------------------------------------------------------

GAME_PAGE_WAIT = 4
SET_PAGE_WAIT = 5

# Retry a set if it temporarily renders with no cards
SET_DISCOVERY_RETRIES = 3

# ------------------------------------------------------------
# Files
# ------------------------------------------------------------

MANIFEST_NAME = "_download_manifest.json"
PROGRESS_NAME = "_harvest_progress.json"


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
    print(f"        Waiting {delay:.1f}s...")
    time.sleep(delay)


def page_delay():
    delay = random.uniform(
        MIN_PAGE_DELAY,
        MAX_PAGE_DELAY
    )
    print(f"    Page delay: {delay:.1f}s...")
    time.sleep(delay)


def safe_filename(name):
    if not name:
        name = "Unknown Card"

    name = unquote(str(name))

    name = re.sub(
        r'[<>:"/\\|?*]',
        "_",
        name
    )

    name = re.sub(
        r"[\x00-\x1f]",
        "_",
        name
    )

    name = re.sub(
        r"\s+",
        " ",
        name
    ).strip()

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
# MANIFEST / PROGRESS
# ============================================================

def load_json(path):
    if not path.exists():
        return {}

    try:
        with path.open(
            "r",
            encoding="utf-8"
        ) as f:
            data = json.load(f)

        if isinstance(data, dict):
            return data

    except Exception as e:
        print(
            f"    WARNING: Could not read "
            f"{path.name}: {e}"
        )

    return {}


def save_json(path, data):
    temp_path = path.with_suffix(
        path.suffix + ".tmp"
    )

    with temp_path.open(
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            data,
            f,
            indent=2,
            ensure_ascii=False
        )

    os.replace(
        temp_path,
        path
    )


def load_progress():
    return load_json(
        OUTPUT_ROOT / PROGRESS_NAME
    )


def save_progress(progress):
    save_json(
        OUTPUT_ROOT / PROGRESS_NAME,
        progress
    )


# ============================================================
# IMAGE VALIDATION
# ============================================================

def is_valid_image_response(response):

    if response.status_code != 200:
        return False

    content_type = (
        response.headers
        .get("Content-Type", "")
        .lower()
        .split(";")[0]
        .strip()
    )

    if not content_type.startswith("image/"):
        return False

    if not response.content:
        return False

    if len(response.content) < 1000:
        return False

    data = response.content[:32]

    # JPEG
    if data.startswith(b"\xff\xd8\xff"):
        return True

    # PNG
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return True

    # GIF
    if (
        data.startswith(b"GIF87a")
        or data.startswith(b"GIF89a")
    ):
        return True

    # WEBP
    if (
        len(data) >= 12
        and data[:4] == b"RIFF"
        and data[8:12] == b"WEBP"
    ):
        return True

    # Other image formats
    # Accept if the server explicitly identifies
    # it as an image and it has reasonable size.
    return True


def get_image_extension(
    image_url,
    content_type
):
    parsed = urlparse(
        image_url or ""
    )

    path = parsed.path.lower()

    for ext in (
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".gif",
        ".avif",
        ".bmp",
    ):
        if path.endswith(ext):
            if ext == ".jpeg":
                return ".jpg"

            return ext

    content_type = (
        content_type or ""
    ).lower()

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


# ============================================================
# FIND GAMES ON /games/
# ============================================================

async def find_games_on_page(page):
    """
    Read the currently rendered /games/ page and return
    the game links currently visible.

    We do NOT build the entire crawl up front.
    This function is only responsible for finding the
    current game's links.
    """

    links = await page.select_all(
        'a[href*="/games/"]'
    )

    games = {}

    for link in links:

        try:

            # Use the element's attrs property.
            attrs = getattr(
                link,
                "attrs",
                None
            )

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

            remainder = (
                path[len("/games/"):]
                .strip("/")
            )

            if not remainder:
                continue

            parts = [
                p
                for p in remainder.split("/")
                if p
            ]

            # Exactly:
            #
            # /games/<game>/
            #
            if len(parts) != 1:
                continue

            slug = parts[0]

            if not slug:
                continue

            try:
                name = await link.text
            except Exception:
                name = ""

            name = (
                name or ""
            ).strip()

            if not name:
                name = (
                    slug
                    .replace("-", " ")
                    .title()
                )

            games[href] = {
                "name": name,
                "url": href,
                "slug": slug,
            }

        except Exception:
            continue

    return sorted(
        games.values(),
        key=lambda x: x["name"].lower()
    )


# ============================================================
# DISCOVER SETS INSIDE ONE GAME
# ============================================================

async def discover_sets(
    page,
    game
):
    game_url = game["url"]
    game_slug = game["slug"]

    print()
    print(
        "-" * 70
    )
    print(
        f"ENTERING GAME: {game['name']}"
    )
    print(
        game_url
    )
    print(
        "-" * 70
    )

    await page.get(
        game_url
    )

    await asyncio.sleep(
        GAME_PAGE_WAIT
    )

    links = await page.select_all(
        f'a[href*="/games/{game_slug}/"]'
    )

    sets = {}

    for link in links:

        try:

            attrs = getattr(
                link,
                "attrs",
                None
            )

            if not attrs:
                continue

            href = attrs.get("href")

            if not href:
                continue

            href = normalize_url(href)

            parsed = urlparse(href)

            path = parsed.path.rstrip("/")

            prefix = (
                f"/games/{game_slug}/"
            )

            if not path.startswith(prefix):
                continue

            remainder = (
                path[len(prefix):]
                .strip("/")
            )

            if not remainder:
                continue

            # Only direct sets.
            if "/" in remainder:
                continue

            set_slug = remainder

            try:
                name = await link.text
            except Exception:
                name = ""

            name = (
                name or ""
            ).strip()

            if not name:
                name = (
                    set_slug
                    .replace("-", " ")
                    .title()
                )

            sets[href] = {
                "name": name,
                "url": href,
                "slug": set_slug,
                "game_name": game["name"],
                "game_url": game_url,
            }

        except Exception:
            continue

    sets_list = sorted(
        sets.values(),
        key=lambda x: x["name"].lower()
    )

    print()
    print(
        f"Sets discovered: "
        f"{len(sets_list)}"
    )

    return sets_list


# ============================================================
# DISCOVER CARDS INSIDE ONE SET
# ============================================================

async def discover_cards(
    page,
    set_info
):
    set_url = set_info["url"]

    for attempt in range(
        1,
        SET_DISCOVERY_RETRIES + 1
    ):

        print()
        print(
            f"    Discovering cards "
            f"(attempt "
            f"{attempt}/"
            f"{SET_DISCOVERY_RETRIES})"
        )

        try:

            await page.get(
                set_url
            )

            # Give the dynamic page time to render.
            await asyncio.sleep(
                SET_PAGE_WAIT
            )

            # ------------------------------------------------
            # Get the actual set name.
            # ------------------------------------------------

            set_name = None

            try:

                set_name = await page.evaluate("""
                    (() => {
                        const h1 = document.querySelector("h1");
                        return h1
                            ? h1.innerText.trim()
                            : "";
                    })()
                """)

            except Exception:
                pass

            if not set_name:
                set_name = set_info["name"]

            set_name = set_name.strip()

            # ------------------------------------------------
            # Get card information directly from the browser.
            #
            # IMPORTANT:
            # Return JSON.stringify(...) so nodriver gives
            # Python one plain string instead of trying to
            # convert a JavaScript array of objects.
            # ------------------------------------------------

            raw_json = await page.evaluate("""
                (() => {

                    const elements = Array.from(
                        document.querySelectorAll(
                            'a[href*="/card/"]'
                        )
                    );

                    const cards = elements.map((a) => {

                        const img =
                            a.querySelector("img");

                        const titleElement =
                            a.querySelector(
                                ".MuiImageListItemBar-title"
                            );

                        const subtitleElement =
                            a.querySelector(
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
                                ? (
                                    img.getAttribute("alt") || ""
                                )
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

            # ------------------------------------------------
            # Convert JSON string into normal Python objects.
            # ------------------------------------------------

            if not raw_json:

                print(
                    "    Browser returned no card data."
                )

                if attempt < SET_DISCOVERY_RETRIES:

                    retry_delay = random.uniform(
                        5,
                        8
                    )

                    print(
                        f"    Retrying in "
                        f"{retry_delay:.1f}s..."
                    )

                    await asyncio.sleep(
                        retry_delay
                    )

                continue

            try:

                raw_cards = json.loads(
                    raw_json
                )

            except Exception as e:

                print(
                    "    ERROR parsing browser "
                    f"JSON: {e}"
                )

                print(
                    f"    Raw result type: "
                    f"{type(raw_json)}"
                )

                print(
                    f"    Raw result preview: "
                    f"{str(raw_json)[:500]}"
                )

                if attempt < SET_DISCOVERY_RETRIES:

                    retry_delay = random.uniform(
                        5,
                        8
                    )

                    print(
                        f"    Retrying in "
                        f"{retry_delay:.1f}s..."
                    )

                    await asyncio.sleep(
                        retry_delay
                    )

                continue

            print(
                f"    Raw card elements: "
                f"{len(raw_cards)}"
            )

            # ------------------------------------------------
            # Convert browser records into our card records.
            # ------------------------------------------------

            cards = {}

            for raw in raw_cards:

                try:

                    card_url = (
                        raw.get("href")
                        or ""
                    ).strip()

                    if not card_url:
                        continue

                    card_url = normalize_url(
                        card_url
                    )

                    # ------------------------------------------------
                    # Card ID
                    # ------------------------------------------------

                    match = re.search(
                        r"/card/(\d+)",
                        card_url
                    )

                    card_id = (
                        match.group(1)
                        if match
                        else None
                    )

                    # ------------------------------------------------
                    # Image URL
                    # ------------------------------------------------

                    image_url = (
                        raw.get("image_src")
                        or ""
                    ).strip()

                    if image_url:
                        image_url = normalize_url(
                            image_url
                        )

                    # ------------------------------------------------
                    # Card name
                    # ------------------------------------------------

                    card_name = (
                        raw.get("title")
                        or raw.get("alt")
                        or ""
                    ).strip()

                    if not card_name:

                        path_parts = (
                            urlparse(
                                card_url
                            )
                            .path
                            .strip("/")
                            .split("/")
                        )

                        if len(path_parts) >= 3:

                            card_name = (
                                path_parts[-1]
                                .replace(
                                    "-",
                                    " "
                                )
                                .title()
                            )

                        else:

                            card_name = (
                                f"Card "
                                f"{card_id or 'Unknown'}"
                            )

                    # ------------------------------------------------
                    # Rarity
                    # ------------------------------------------------

                    rarity = (
                        raw.get("rarity")
                        or ""
                    ).strip()

                    # ------------------------------------------------
                    # Build card
                    # ------------------------------------------------

                    card = {
                        "id": card_id,
                        "name": card_name,
                        "rarity": rarity,
                        "card_url": card_url,
                        "image_url": image_url,
                    }

                    cards[
                        manifest_key(card)
                    ] = card

                except Exception as e:

                    print(
                        "    WARNING processing "
                        f"card: {e}"
                    )

                    continue

            cards_list = list(
                cards.values()
            )

            # ------------------------------------------------
            # Diagnostics
            # ------------------------------------------------

            cards_with_images = sum(
                1
                for card in cards_list
                if card.get("image_url")
            )

            cards_without_images = (
                len(cards_list)
                - cards_with_images
            )

            print(
                f"    Cards discovered: "
                f"{len(cards_list)}"
            )

            print(
                f"    With image URLs:   "
                f"{cards_with_images}"
            )

            print(
                f"    Without image URLs:"
                f" {cards_without_images}"
            )

            # ------------------------------------------------
            # Show first few cards.
            # ------------------------------------------------

            if cards_list:

                print()

                for card in cards_list[:5]:

                    print(
                        f"    CARD: "
                        f"{card['name']}"
                    )

                    print(
                        f"        ID:    "
                        f"{card.get('id')}"
                    )

                    print(
                        f"        Image: "
                        f"{card.get('image_url')}"
                    )

                    print(
                        f"        Rarity: "
                        f"{card.get('rarity')}"
                    )

                if len(cards_list) > 5:

                    print(
                        f"    ... "
                        f"{len(cards_list) - 5} more"
                    )

                print()

                return {
                    **set_info,
                    "name": set_name,
                    "cards": cards_list,
                }

            # ------------------------------------------------
            # No cards successfully parsed.
            # ------------------------------------------------

            print(
                "    No usable cards were parsed."
            )

            if attempt < SET_DISCOVERY_RETRIES:

                retry_delay = random.uniform(
                    5,
                    8
                )

                print(
                    f"    Retrying in "
                    f"{retry_delay:.1f}s..."
                )

                await asyncio.sleep(
                    retry_delay
                )

        except Exception as e:

            print(
                f"    ERROR discovering cards: "
                f"{e}"
            )

            if attempt < SET_DISCOVERY_RETRIES:

                retry_delay = random.uniform(
                    5,
                    8
                )

                print(
                    f"    Retrying in "
                    f"{retry_delay:.1f}s..."
                )

                await asyncio.sleep(
                    retry_delay
                )

    return {
        **set_info,
        "name": set_info["name"],
        "cards": [],
        "error": (
            "No cards found after retries"
        ),
    }
# ============================================================
# DOWNLOAD ONE IMAGE
# ============================================================

def download_image(
    card,
    output_path,
    set_url
):

    image_url = card.get(
        "image_url"
    )

    if not image_url:

        return {
            "status": "failed",
            "error": "No image URL"
        }

    headers = {
        "Referer": set_url,
        "User-Agent": session.headers[
            "User-Agent"
        ],
        "Accept": (
            "image/avif,image/webp,"
            "image/apng,image/svg+xml,"
            "image/*,*/*;q=0.8"
        ),
    }

    temporary_statuses = {
        408,
        425,
        429,
        500,
        502,
        503,
        504,
    }

    for attempt in range(
        1,
        MAX_RETRIES + 1
    ):

        try:

            response = session.get(
                image_url,
                headers=headers,
                timeout=45
            )

            if is_valid_image_response(
                response
            ):

                content_type = (
                    response.headers.get(
                        "Content-Type",
                        ""
                    )
                )

                temp_path = (
                    output_path.with_suffix(
                        output_path.suffix
                        + ".tmp"
                    )
                )

                with temp_path.open(
                    "wb"
                ) as f:

                    f.write(
                        response.content
                    )

                if (
                    not temp_path.exists()
                    or temp_path.stat().st_size < 1000
                ):

                    try:
                        temp_path.unlink()
                    except Exception:
                        pass

                    raise RuntimeError(
                        "Image was empty "
                        "or too small"
                    )

                os.replace(
                    temp_path,
                    output_path
                )

                return {
                    "status": "downloaded",
                    "size": output_path.stat().st_size,
                    "content_type": content_type,
                }

            status = response.status_code

            if status in temporary_statuses:

                print(
                    f"        Temporary HTTP "
                    f"{status} "
                    f"(attempt "
                    f"{attempt}/"
                    f"{MAX_RETRIES})"
                )

                if attempt < MAX_RETRIES:

                    wait = (
                        3 * attempt
                    )

                    print(
                        f"        Retry in "
                        f"{wait}s..."
                    )

                    time.sleep(
                        wait
                    )

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

            print(
                f"        Download error "
                f"(attempt "
                f"{attempt}/"
                f"{MAX_RETRIES}): "
                f"{e}"
            )

            if attempt < MAX_RETRIES:

                wait = (
                    3 * attempt
                )

                print(
                    f"        Retry in "
                    f"{wait}s..."
                )

                time.sleep(
                    wait
                )

            else:

                return {
                    "status": "failed",
                    "error": str(e)
                }

    return {
        "status": "failed",
        "error": "Maximum retries exceeded"
    }


# ============================================================
# DOWNLOAD ONE SET
# ============================================================

def download_set(
    set_data
):

    game_name = set_data[
        "game_name"
    ]

    set_name = set_data[
        "name"
    ]

    set_url = set_data[
        "url"
    ]

    cards = set_data.get(
        "cards",
        []
    )

    game_folder = (
        OUTPUT_ROOT
        / safe_folder_name(game_name)
    )

    set_folder = (
        game_folder
        / safe_folder_name(set_name)
    )

    set_folder.mkdir(
        parents=True,
        exist_ok=True
    )

    manifest_path = (
        set_folder
        / MANIFEST_NAME
    )

    manifest = load_json(
        manifest_path
    )

    downloaded = 0
    skipped = 0
    failed = 0

    print()
    print(
        "=" * 70
    )

    print(
        f"DOWNLOADING: {game_name}"
    )

    print(
        f"SET:         {set_name}"
    )

    print(
        f"CARDS:       {len(cards)}"
    )

    print(
        f"FOLDER:      {set_folder}"
    )

    print(
        "=" * 70
    )

    for index, card in enumerate(
        cards,
        start=1
    ):

        card_name = (
            card.get(
                "name",
                f"Card {index}"
            )
        )

        key = manifest_key(
            card
        )

        existing = manifest.get(
            key
        )

        filename = (
            safe_filename(card_name)
            + ".jpg"
        )

        output_path = (
            set_folder
            / filename
        )

        # ====================================================
        # SKIP EXISTING FILE
        # ====================================================

        if output_path.exists():

            try:
                size = output_path.stat().st_size
            except Exception:
                size = 0

            if size >= 1000:

                skipped += 1

                # Keep manifest synchronized
                manifest[key] = {
                    **card,
                    "path": str(
                        output_path
                    ),
                    "status": "downloaded",
                    "size": size,
                    "content_type": (
                        existing.get(
                            "content_type"
                        )
                        if existing
                        else "image/*"
                    ),
                }

                save_json(
                    manifest_path,
                    manifest
                )

                print(
                    f"[{index}/{len(cards)}] "
                    f"SKIP  {card_name}"
                )

                continue

        # ====================================================
        # MANIFEST-BASED SKIP
        # ====================================================

        if existing:

            old_path = existing.get(
                "path"
            )

            if old_path:

                old_path_obj = Path(
                    old_path
                )

                if old_path_obj.exists():

                    try:
                        size = (
                            old_path_obj.stat()
                            .st_size
                        )
                    except Exception:
                        size = 0

                    if (
                        size >= 1000
                        and existing.get(
                            "status"
                        ) == "downloaded"
                    ):

                        skipped += 1

                        print(
                            f"[{index}/{len(cards)}] "
                            f"SKIP  {card_name}"
                        )

                        continue

        # ====================================================
        # DOWNLOAD
        # ====================================================

        print(
            f"[{index}/{len(cards)}] "
            f"GET   {card_name}"
        )

        result = download_image(
            card,
            output_path,
            set_url
        )

        if (
            result["status"]
            == "downloaded"
        ):

            downloaded += 1

            manifest[key] = {
                **card,
                "path": str(
                    output_path
                ),
                "status": "downloaded",
                "size": result.get(
                    "size"
                ),
                "content_type": result.get(
                    "content_type"
                ),
                "downloaded_at": (
                    time.strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                ),
            }

            save_json(
                manifest_path,
                manifest
            )

            print(
                f"        OK "
                f"({result.get('size', 0):,} bytes)"
            )

        else:

            failed += 1

            manifest[key] = {
                **card,
                "path": str(
                    output_path
                ),
                "status": "failed",
                "error": result.get(
                    "error",
                    "Unknown error"
                ),
                "failed_at": (
                    time.strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                ),
            }

            save_json(
                manifest_path,
                manifest
            )

            print(
                f"        FAILED: "
                f"{result.get('error')}"
            )

        if index < len(cards):
            polite_delay()

    print()
    print(
        f"SET COMPLETE: {set_name}"
    )

    print(
        f"    Downloaded: {downloaded}"
    )

    print(
        f"    Skipped:    {skipped}"
    )

    print(
        f"    Failed:     {failed}"
    )

    return {
        "game": game_name,
        "set": set_name,
        "cards": len(cards),
        "downloaded": downloaded,
        "skipped": skipped,
        "failed": failed,
    }


# ============================================================
# PROCESS ONE GAME
# ============================================================

async def process_game(
    page,
    game,
    game_number
):

    print()
    print()
    print(
        "#" * 70
    )

    print(
        f"GAME: {game_number}"
    )

    print(
        f"NAME: {game['name']}"
    )

    print(
        f"URL:  {game['url']}"
    )

    print(
        "#" * 70
    )

    try:

        sets = await discover_sets(
            page,
            game
        )

    except Exception as e:

        print(
            f"ERROR discovering sets "
            f"for {game['name']}: {e}"
        )

        return []

    results = []

    for set_number, set_info in enumerate(
        sets,
        start=1
    ):

        print()
        print(
            f"SET {set_number}/{len(sets)}"
        )

        try:

            set_data = await discover_cards(
                page,
                set_info
            )

            cards = set_data.get(
                "cards",
                []
            )

            if not cards:

                print(
                    "    WARNING: "
                    "No cards discovered "
                    "for this set."
                )

                results.append({
                    "game": game["name"],
                    "set": set_info["name"],
                    "cards": 0,
                    "downloaded": 0,
                    "skipped": 0,
                    "failed": 1,
                })

                continue

            if DISCOVERY_ONLY:

                print(
                    f"    DISCOVERY ONLY: "
                    f"{len(cards)} cards"
                )

                results.append({
                    "game": game["name"],
                    "set": set_data["name"],
                    "cards": len(cards),
                    "downloaded": 0,
                    "skipped": 0,
                    "failed": 0,
                })

            else:

                result = download_set(
                    set_data
                )

                results.append(
                    result
                )

        except Exception as e:

            print(
                f"    ERROR processing "
                f"set: {e}"
            )

            results.append({
                "game": game["name"],
                "set": set_info["name"],
                "cards": 0,
                "downloaded": 0,
                "skipped": 0,
                "failed": 1,
            })

        if set_number < len(sets):
            page_delay()

    return results


# ============================================================
# MAIN
# ============================================================

async def main():

    print()
    print(
        "=" * 70
    )

    print(
        "CCG TRADER CARD IMAGE HARVESTER"
    )

    print(
        "=" * 70
    )

    print()

    print(
        f"Browser:        {BROWSER_PATH}"
    )

    print(
        f"Output:         {OUTPUT_ROOT}"
    )

    print(
        f"Card delay:     "
        f"{MIN_DELAY}-{MAX_DELAY} seconds"
    )

    print(
        f"Discovery only: "
        f"{DISCOVERY_ONLY}"
    )

    print()

    OUTPUT_ROOT.mkdir(
        parents=True,
        exist_ok=True
    )

    if not os.path.exists(
        BROWSER_PATH
    ):

        raise FileNotFoundError(
            "Vivaldi was not found at:\n"
            f"{BROWSER_PATH}"
        )

    print(
        "Starting Vivaldi..."
    )

    browser = await uc.start(
        browser_executable_path=BROWSER_PATH,
        browser_args=[
            "--window-size=1920,1080",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ]
    )

    results = []

    try:

        page = await browser.get(
            GAMES_URL
        )

        # ====================================================
        # MAIN GAME LOOP
        # ====================================================

        game_number = 0

        while True:

            # ------------------------------------------------
            # Always return to /games/ before finding games.
            # ------------------------------------------------

            print()
            print(
                "=" * 70
            )

            print(
                "RETURNING TO GAME INDEX"
            )

            print(
                "=" * 70
            )

            await page.get(
                GAMES_URL
            )

            await asyncio.sleep(
                GAME_PAGE_WAIT
            )

            games = await find_games_on_page(
                page
            )

            print()
            print(
                f"Games currently visible: "
                f"{len(games)}"
            )

            if not games:

                print()
                print(
                    "ERROR: No games found."
                )

                break

            # ------------------------------------------------
            # Determine next game.
            #
            # We use a progress file so a restart doesn't
            # require starting from the beginning.
            # ------------------------------------------------

            progress = load_progress()

            completed_games = set(
                progress.get(
                    "completed_games",
                    []
                )
            )

            next_game = None

            for game in games:

                if game["url"] not in completed_games:

                    next_game = game

                    break

            # ------------------------------------------------
            # Everything currently discovered is complete.
            # ------------------------------------------------

            if next_game is None:

                print()
                print(
                    "=" * 70
                )

                print(
                    "ALL DISCOVERED GAMES COMPLETE"
                )

                print(
                    "=" * 70
                )

                break

            # ------------------------------------------------
            # Process next game
            # ------------------------------------------------

            game_number += 1

            game_results = await process_game(
                page,
                next_game,
                game_number
            )

            results.extend(
                game_results
            )

            # ------------------------------------------------
            # Mark game complete only after all its sets have
            # been processed.
            # ------------------------------------------------

            progress = load_progress()

            completed_games = set(
                progress.get(
                    "completed_games",
                    []
                )
            )

            completed_games.add(
                next_game["url"]
            )

            progress[
                "completed_games"
            ] = sorted(
                completed_games
            )

            progress[
                "last_completed_game"
            ] = {
                "name": next_game["name"],
                "url": next_game["url"],
                "completed_at": (
                    time.strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                ),
            }

            save_progress(
                progress
            )

            print()
            print(
                "=" * 70
            )

            print(
                f"GAME COMPLETE: "
                f"{next_game['name']}"
            )

            print(
                "=" * 70
            )

            # ------------------------------------------------
            # Wait before returning to index and finding the
            # next game.
            # ------------------------------------------------

            page_delay()

        # ====================================================
        # FINAL SUMMARY
        # ====================================================

        print()
        print()
        print(
            "=" * 70
        )

        print(
            "CCG TRADER HARVEST COMPLETE"
        )

        print(
            "=" * 70
        )

        if results:

            total_cards = sum(
                r.get(
                    "cards",
                    0
                )
                for r in results
            )

            total_downloaded = sum(
                r.get(
                    "downloaded",
                    0
                )
                for r in results
            )

            total_skipped = sum(
                r.get(
                    "skipped",
                    0
                )
                for r in results
            )

            total_failed = sum(
                r.get(
                    "failed",
                    0
                )
                for r in results
            )

            print()
            print(
                f"Cards discovered: "
                f"{total_cards}"
            )

            print(
                f"Downloaded:       "
                f"{total_downloaded}"
            )

            print(
                f"Skipped:          "
                f"{total_skipped}"
            )

            print(
                f"Failed:           "
                f"{total_failed}"
            )

        print()
        print(
            f"Progress file:"
        )

        print(
            OUTPUT_ROOT
            / PROGRESS_NAME
        )

        print()
        print(
            f"Output root:"
        )

        print(
            OUTPUT_ROOT
        )

    except KeyboardInterrupt:

        print()
        print()
        print(
            "=" * 70
        )

        print(
            "STOPPED BY USER"
        )

        print(
            "=" * 70
        )

        print()
        print(
            "Downloaded images and manifests "
            "have already been saved."
        )

        print(
            "Run the script again to resume."
        )

    finally:

        print()
        print(
            "Closing Vivaldi..."
        )

        try:
            browser.stop()
        except Exception:
            pass


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    asyncio.run(main())