Project Master Menu — What Each Option Does
Core Systems
1. AI GUI Interface (AI_gui.py) Launches the graphical AI interface.

2. AI Text Engine (ai_headless.py) Runs the AI text engine in headless mode (no GUI) — for text generation over terminal/SSH.

3. Web Sorter (web_base.py) Sorts and organizes web content.

Automation & Cards
4. All Jap Cards (jap_cards_main.py) The main Japanese card scraper. Downloads card images from the Japanese TCG site for every registered game and drops them into Card Upload, organized by game folder. The primary bulk downloader for Japanese-language cards.

5. MTG Scraper (magic.py) Scrapes Magic: The Gathering card images and adds them to the collection.

6. Neopets Scraper (neopets.py) Scrapes Neopets card images and adds them to the collection.

7. Altered Scraper (altered.py) Scrapes Altered TCG card images and adds them to the collection.

8. Global TCG Scraper (allcards.py) The general-purpose scraper for all the other TCGs. Downloads card images across the supported games and organizes them by game folder in Card Upload.

9. Vibes TCG Scraper (vibes.py) Scrapes Vibes TCG card images and adds them to the collection.

Utilities — TCG Database Tools
10. TCG View Tables (TCG Wrapper/tcg_view_tables.py) Opens the SQLite database and prints a summary of every table (skipped_images, progress, tcg_master) with its record count. A quick readout of what's in the database.

11. TCG Search (TCG Wrapper/tcg_search.py) Searches the skipped_images table by image name and prints every match with its game and language. Use it to look up whether a specific card ID is already recorded.

12. TCG Import Skipped (TCG Wrapper/tcg_import_skipped.py) Imports cards from the Skipped Cards folder into the database. It lists the registered TCGs from tcg_master, you pick one, and it pulls the matching folder's image files into skipped_images and marks them rejected in progress. Use this to log cards you deliberately skipped.

13. TCG Discovery Wizard (TCG Wrapper/tcg_discovery.py) The GUI mapping tool. It walks through the Card Database folders one at a time, shows a preview image, and lets you assign a site ID, page count, and language (Japanese / English / Both) for each. Saves the mapping into tcg_master. New mode only shows unmapped folders; All mode re-shows everything. Requires a display — won't work over headless SSH.

14. TCG Deep Inspect (TCG Wrapper/tcg_deep_inspect.py) Lists all database tables and lets you pick one for a deep view. For tcg_master it prints the full registry (name, language, site ID, pages, folder). For other tables it shows the first 5 and last 5 rows. Good for eyeballing what's actually stored.

15. TCG Rename / Swap (TCG Wrapper/tcg_rename.py) Renames a TCG across the whole database at once — updates tcg_master, skipped_images, and progress so the new name sticks everywhere. Use it when a game's display name changes.

16. TCG Delete Tables (TCG Wrapper/tcg_delete_tables.py) Lists all tables and lets you drop one after typing DELETE to confirm. Destructive — only use when you're sure you want to wipe a table's data.

17. TCG Purge Dupes (TCG Wrapper/tcg_purge_dupes.py) Scans the New Cards folder and deletes any file that already exists either in the database history or as a physical file in the Card Database. It's the cleanup step for removing cards you've already processed.

18. TCG Sync Library (TCG Wrapper/tcg_sync.py) The reconciliation tool for the TCG side. It compares the physical Card Database folders against the database records, flagging each file as [MATCH], [SKIPPED], or [NEW], and inserts any new ones into progress. Lets you scan one sector or all folders.

Card Database
19. Build Card Index (Utilities/card_build_index.py) Scans T:\Card Upload and registers every image file into the Mongo card_index database. For each file it stores the filename, game folder, source path, destination path (G Drive), status pending, and a timestamp. It skips anything already in the index. Use this for a fresh batch or full rebuild.

20. Scan for New Cards (Utilities/card_scan_new.py) Same idea, but lighter: it only adds files that aren't already in the index, and doesn't re-touch existing entries. Use this when you've dropped a few new cards into Card Upload and just want to pick up the additions without re-scanning everything.

21. Copy & Archive (Utilities/card_copy_archive.py) The main workhorse. For every index entry marked pending, it copies the file to G Drive (G:\My Drive\Card Database\<game>\), verifies the copy size matches, then moves the original from Card Upload into T (T:\Card Database\<game>\). It skips files whose source is missing, and skips ones already at the destination with the same size. Marks each entry uploaded when done. This is the only step that removes files from Card Upload.

22. Archive Only (Utilities/card_archive_only.py) Same as Copy & Archive but skips the G Drive copy entirely: it just moves files from Card Upload into T:\Card Database, organized by game folder. Use this for cards you want stored on T but not backed up to Google Drive. Note: it works off the folders directly, not the index.

23. Reorganize Database (Utilities/card_reorganize.py) Cleans up T:\Card Database by moving loose files into their proper game subfolders, based on the index. Files whose name appears in more than one game (duplicates) or isn't in the index at all get moved to an Unmatched folder instead of being guessed wrong.

24. Remove Empty Folders (Utilities/card_remove_empty.py) Deletes any empty game folders under Card Upload. Safe — it only removes folders with nothing in them.

25. Verification Report (Utilities/card_verify.py) Just prints counts from the index: how many are pending, uploaded, and missing_source. A quick status readout, no file operations.

26. Immich Uploader (Utilities/immich_uploader.py) Uploads images from Card Upload to your Immich server, creating one album per game folder. It hashes each file and records it in its own SQLite database (immich_uploads.db) so re-runs skip already-uploaded cards. It only uploads — it doesn't move or delete anything.

27. DB Check (Utilities/db_check.py) The reconciliation matrix. For each game it verifies every indexed card is present on G Drive and T, that the source is gone from Card Upload, and flags orphans (files on disk not in the index). It prints a matrix with totals, then can re-copy missing files from wherever a copy still exists.

Typical Batch Flow
The natural rhythm for a card batch is 19 → 26 → 21 → 27: index the new cards, upload to Immich, copy-and-archive them out, then run the check to confirm everything reconciled.

For the TCG side, the typical rhythm is 13 → 18 → 17: map any new folders with the Discovery Wizard, sync the physical library into the database, then purge duplicates.