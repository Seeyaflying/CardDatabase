import subprocess
import os
import sys
import time
import signal
import launcher

# ==============================================================
# CONFIGURATION
# ==============================================================
IS_WINDOWS = os.name == 'nt'

if IS_WINDOWS:
    import keyboard
    CLEAR_CMD = 'cls'
else:
    CLEAR_CMD = 'clear'


def draw_menu():
    os.system(CLEAR_CMD)
    print(f"{launcher.Color.BLUE}┌{'─' * 58}┐")
    print(f"│{launcher.Color.BOLD}{'AI PROJECT MASTER MANAGER'.center(58)}{launcher.Color.END}{launcher.Color.BLUE}│")
    print(f"└{'─' * 58}┘{launcher.Color.END}")

    print(f"\n {launcher.Color.BOLD}{launcher.Color.PURPLE}💠 CORE SYSTEMS{launcher.Color.END}")
    launcher.print_line("1", "AI/AI_gui.py", "AI GUI Interface")
    launcher.print_line("2", "AI/ai_headless.py", "AI Text Engine")
    launcher.print_line("3", "Utilities/web_base.py", "Web Sorter")

    print(f"\n {launcher.Color.BOLD}{launcher.Color.GREEN}📂 AUTOMATION & CARDS{launcher.Color.END}")
    launcher.print_line("4", "TCGs/jap_cards_main.py", "All Jap Cards")
    launcher.print_line("5", "TCGs/magic.py", "MTG Scraper")
    launcher.print_line("6", "TCGs/neopets.py", "Neopets Scraper")
    launcher.print_line("7", "TCGs/Altered.py", "Altered Scraper")
    launcher.print_line("8", "TCGs/allcards.py", "Global TCG Scraper")
    launcher.print_line("9", "TCGs/vibes.py", "Vibes TCG Scraper")

    print(f"\n {launcher.Color.BOLD}{launcher.Color.CYAN}🛠  UTILITIES{launcher.Color.END}")
    launcher.print_line("10", "TCG Wrapper/tcg_view_tables.py", "TCG View Tables")
    launcher.print_line("11", "TCG Wrapper/tcg_search.py", "TCG Search")
    launcher.print_line("12", "TCG Wrapper/tcg_import_skipped.py", "TCG Import Skipped")
    launcher.print_line("13", "TCG Wrapper/tcg_discovery.py", "TCG Discovery Wizard")
    launcher.print_line("14", "TCG Wrapper/tcg_deep_inspect.py", "TCG Deep Inspect")
    launcher.print_line("15", "TCG Wrapper/tcg_rename.py", "TCG Rename/Swap")
    launcher.print_line("16", "TCG Wrapper/tcg_delete_tables.py", "TCG Delete Tables")
    launcher.print_line("17", "TCG Wrapper/tcg_purge_dupes.py", "TCG Purge Dupes")
    launcher.print_line("18", "TCG Wrapper/tcg_sync.py", "TCG Sync Library")

    print(f"\n {launcher.Color.BOLD}{launcher.Color.BLUE}🗂  CARD DATABASE{launcher.Color.END}")
    launcher.print_line("19", "Utilities/card_build_index.py", "Build Card Index")
    launcher.print_line("20", "Utilities/card_scan_new.py", "Scan for New Cards")
    launcher.print_line("21", "Utilities/card_copy_archive.py", "Copy & Archive")
    launcher.print_line("22", "Utilities/card_archive_only.py", "Archive Only")
    launcher.print_line("23", "Utilities/card_reorganize.py", "Reorganize Database")
    launcher.print_line("24", "Utilities/card_remove_empty.py", "Remove Empty Folders")
    launcher.print_line("25", "Utilities/card_verify.py", "Verification Report")
    launcher.print_line("26", "Utilities/immich_uploader.py", "Immich Uploader")
    launcher.print_line("27", "Utilities/db_check.py", "DB Check (matrix)")

    print(f" {launcher.Color.RED}•{launcher.Color.END} [{launcher.Color.BOLD}Q{launcher.Color.END}] {launcher.Color.RED}Quit Manager{launcher.Color.END}")

    if IS_WINDOWS:
        print(
            f"\n{launcher.Color.DARKCYAN}{'─' * 60}\n{launcher.Color.BOLD} EMERGENCY STOP: {launcher.Color.RED}Ctrl + Shift + K{launcher.Color.END}\n{launcher.Color.DARKCYAN}{'─' * 60}{launcher.Color.END}")
    else:
        print(
            f"\n{launcher.Color.DARKCYAN}{'─' * 60}\n{launcher.Color.BOLD} Use {launcher.Color.RED}Ctrl + C{launcher.Color.END} to terminate current script\n{launcher.Color.DARKCYAN}{'─' * 60}{launcher.Color.END}")


def main():
    if IS_WINDOWS:
        try:
            keyboard.add_hotkey('ctrl+shift+k', launcher.kill_active_process, suppress=True)
        except:
            pass

    mapping = {
        "1": "AI_gui.py", "2": "ai_headless.py", "3": "web_base.py",
        "4": "jap_cards_main.py", "5": "magic.py", "6": "neopets.py",
        "7": "altered.py", "8": "allcards.py", "v": "vibes.py",
        "s": "TCG Wrapper/tcg_view_tables.py", "e": "TCG Wrapper/tcg_search.py",
        "i": "TCG Wrapper/tcg_import_skipped.py", "g": "TCG Wrapper/tcg_discovery.py",
        "p": "TCG Wrapper/tcg_deep_inspect.py", "x": "TCG Wrapper/tcg_rename.py",
        "y": "TCG Wrapper/tcg_delete_tables.py", "z": "TCG Wrapper/tcg_purge_dupes.py",
        "l": "TCG Wrapper/tcg_sync.py",
        "b": "Utilities/card_build_index.py", "n": "Utilities/card_scan_new.py",
        "c": "Utilities/card_copy_archive.py", "a": "Utilities/card_archive_only.py",
        "r": "Utilities/card_reorganize.py", "f": "Utilities/card_remove_empty.py",
        "w": "Utilities/card_verify.py", "m": "Utilities/immich_uploader.py",
        "d": "Utilities/db_check.py",
    }

    while True:
        draw_menu()
        try:
            choice = input(f"\n{launcher.Color.BOLD}{launcher.Color.YELLOW} Selection > {launcher.Color.END}").strip().lower()
            if choice in mapping:
                launcher.run_script(mapping[choice])
            elif choice == 'q':
                break
        except KeyboardInterrupt:
            print(f"\n{launcher.Color.YELLOW}Use 'Q' to exit properly.{launcher.Color.END}")
            time.sleep(1)


if __name__ == "__main__":
    main()

