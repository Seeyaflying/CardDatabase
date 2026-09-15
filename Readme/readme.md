Card Database Manager
A collection of Python tools for managing a large TCG card-image collection. The system indexes cards, copies and archives them to Google Drive, uploads them to Immich, and scrapes new cards from various sources.

Overview
The project is organized around a few core pieces:

config.py — Central configuration. Reads environment variables for folder paths, the MongoDB connection, and the Immich endpoint. Edit this (or your .env) to point at your drives and database.
db.py — MongoDB helpers. Provides get_db(), coll(), and functions to mark cards as uploaded or missing.
card_manager.py — The main menu-driven manager. Rebuilds the card index, copies & archives cards, reorganizes the database, and runs verification.
db_check.py — Reconciliation tool that compares the database against the filesystem and can re-copy missing files.
immich_uploader.py — Uploads card images to Immich and sorts them into albums.
web_base.py — Card sorter web app (in Utilities/).
tcg_core.py — Shared CardDBManager class used by the TCG wrapper scripts (in TCG Wrapper/).
The Card Flow
Build the index — Scans the Card Upload folder and records every image in MongoDB.
Copy & archive — Copies each indexed card to Google Drive, verifies the copy, then moves the original into the Card Database archive.
Upload to Immich — Sends the images to Immich and organizes them into per-game albums.
Verify — Compares the database against the filesystem to catch missing or orphaned files.
Setup
Install dependencies:

pip install -r requirements.txt
Copy
Configure paths and credentials. The key settings live in config.py, which reads from environment variables or a .env file:

CARD_UPLOAD — folder where scraped cards land
CARD_DATABASE — archive folder for processed cards
G_DRIVE — Google Drive destination
MONGO_URI — MongoDB connection string
IMMICH_URL / IMMICH_API_KEY — Immich server and API key
Make sure MongoDB is running and reachable at the URI in config.py.

Running the Manager
Launch the menu-driven interface:

python utilities.py
Copy
From the menu you can:

Build the card index
Scan for new cards
Copy & archive (to G Drive + archive)
Archive only (no G Drive)
Reorganize the card database
Remove empty folders
Run a verification report
Run the Immich uploader
Run a DB check (reconciliation + fix)
Scrapers
The scrapers download new card images from various sources into the Card Upload folders. Most check an existing-image index (either the filesystem or MongoDB) so they don't re-download cards you already have.

Script	Source	Notes
magic.py	Scryfall bulk data	Downloads all Magic card images; no database dependency
altered.py	Altered.gg	Selenium scraper
neopets.py	Upper Deck	Selenium scraper
jap_cards_main.py	TCG Republic	Japanese cards, uses nodriver
English Harvester	TCG Player API	Downloads by TCG category
vibes.py	Vibes.game	Selenium scraper; no database dependency
Storage Layout
The system expects folders organized by game, for example:

Card Upload/
  Magic the Gathering/
  Altered/
  NeoPets Battledome/
  ...

Card Database/          # Archived originals, organized by game
  Magic the Gathering/
  ...

G:/My Drive/Card Database/   # Google Drive copy, organized by game
  Magic the Gathering/
  ...
Copy
Notes
The scrapers use headless browsers (Selenium / nodriver). On Linux, the flags --no-sandbox and --disable-dev-shm-usage are included for stability.
Some scrapers may ask you to confirm a VPN is enabled before running, depending on the site.
The project was recently migrated from SQLite to MongoDB; db.py and config.py are the touchpoints for the database connection.