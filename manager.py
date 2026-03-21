import subprocess
import os
import sys
import sqlite3
import time
import traceback
import signal
from datetime import datetime

# ==============================================================
# 1. PLATFORM DETECTION & CONFIGURATION
# ==============================================================
IS_WINDOWS = os.name == 'nt'
DB_FILE = "skipped_images.sqlite"
active_process = None

# Keyboard library is touchy on Ubuntu (requires sudo).
# We will use it on Windows and a safer alternative or signal on Linux.
if IS_WINDOWS:
    import keyboard

    CLEAR_CMD = 'cls'
else:
    CLEAR_CMD = 'clear'


class Color:
    PURPLE = '\033[95m';
    CYAN = '\033[96m';
    DARKCYAN = '\033[36m'
    BLUE = '\033[94m';
    GREEN = '\033[92m';
    YELLOW = '\033[93m'
    RED = '\033[91m';
    BOLD = '\033[1m';
    END = '\033[0m'


# ==============================================================
# 2. DATABASE & SYSTEM HELPERS
# ==============================================================
def setup_db():
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""
                     CREATE TABLE IF NOT EXISTS last_run
                     (
                         script_name
                         TEXT
                         PRIMARY
                         KEY,
                         last_run_time
                         TEXT,
                         status
                         TEXT
                     )
                     """)
        conn.commit()


def save_history_db(script_name, status="Success"):
    now = datetime.now().isoformat()
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("INSERT OR REPLACE INTO last_run (script_name, last_run_time, status) VALUES (?, ?, ?)",
                         (script_name, now, status))
            conn.commit()
    except Exception as e:
        print(f"{Color.RED}DB Error: {e}{Color.END}")


def get_run_info(script_name):
    try:
        with sqlite3.connect(DB_FILE) as conn:
            row = conn.execute("SELECT last_run_time, status FROM last_run WHERE script_name = ?",
                               (script_name,)).fetchone()
            if not row: return f"{Color.YELLOW}Never{Color.END}", Color.YELLOW

            last_run = datetime.fromisoformat(row[0])
            diff = datetime.now() - last_run
            status_color = Color.GREEN if row[1] == "Success" else Color.RED

            if diff.days > 0:
                t_str = f"{diff.days}d ago"
            else:
                seconds = diff.total_seconds()
                if seconds < 60:
                    t_str = "Just now"
                elif seconds < 3600:
                    t_str = f"{int(seconds // 60)}m ago"
                else:
                    t_str = f"{int(seconds // 3600)}h ago"

            return f"{Color.CYAN}{t_str}{Color.END}", status_color
    except:
        return "Error", Color.RED


def kill_active_process():
    """Forcefully stops the currently running child script."""
    global active_process
    if active_process and active_process.poll() is None:
        print(f"\n{Color.BOLD}{Color.RED} [!] KILL SIGNAL: Terminating child process...{Color.END}")
        if IS_WINDOWS:
            active_process.terminate()
        else:
            # On Linux, sending SIGTERM is cleaner
            os.kill(active_process.pid, signal.SIGTERM)


# ==============================================================
# 3. EXECUTION ENGINE
# ==============================================================
def run_script(script_name):
    global active_process
    if not os.path.exists(script_name):
        print(f"\n{Color.RED}[!] Error: {script_name} not found.{Color.END}")
        time.sleep(1.5)
        return

    os.system(CLEAR_CMD)
    print(f"{Color.PURPLE}{'=' * 60}")
    print(f"{Color.BOLD}{Color.YELLOW} EXECUTING: {script_name}")

    if IS_WINDOWS:
        print(f"{Color.CYAN} Press Ctrl+Shift+K to Force Stop")
    else:
        print(f"{Color.CYAN} Running in Subprocess (Standard Linux Terminal)")

    print(f"{Color.PURPLE}{'=' * 60}{Color.END}\n")

    try:
        # Use sys.executable to ensure we use the same Python/Conda environment
        active_process = subprocess.Popen([sys.executable, script_name])
        active_process.wait()

        status = "Success" if active_process.returncode == 0 else "Stopped/Failed"
        save_history_db(script_name, status)
    except Exception as e:
        print(f"{Color.RED}Execution Error: {e}{Color.END}")
        save_history_db(script_name, "Failed")
    finally:
        active_process = None
        print(f"\n{Color.DARKCYAN}Finished. Returning to menu...{Color.END}")
        time.sleep(1.5)


# ==============================================================
# 4. UI DRAWING
# ==============================================================
def print_line(key, filename, display_name):
    time_str, status_color = get_run_info(filename)
    print(
        f" {status_color}•{Color.END} [{Color.BOLD}{key.upper()}{Color.END}] {display_name:<22} {Color.DARKCYAN}»{Color.END} Last: {time_str}")


def draw_menu():
    os.system(CLEAR_CMD)
    print(f"{Color.BLUE}┌{'─' * 58}┐")
    print(f"│{Color.BOLD}{'AI PROJECT MASTER MANAGER'.center(58)}{Color.END}{Color.BLUE}│")
    print(f"└{'─' * 58}┘{Color.END}")

    print(f"\n {Color.BOLD}{Color.PURPLE}💠 CORE SYSTEMS{Color.END}")
    print_line("1", "AI_gui.py", "AI GUI Interface")
    print_line("2", "ai_headless.py", "AI Text Engine")
    print_line("3", "web_base.py", "Web Sorter")

    print(f"\n {Color.BOLD}{Color.GREEN}📂 AUTOMATION & CARDS{Color.END}")
    print_line("4", "jap_cards_main.py", "All Jap Cards")
    print_line("5", "magic.py", "MTG Scraper")
    print_line("6", "neopets.py", "Neopets Scraper")
    print_line("7", "altered.py", "Altered Scraper")
    print_line("8", "allcards.py", "Global TCG Scraper")
    print_line("V", "vibes.py", "Vibes TCG Scraper")

    print(f"\n {Color.BOLD}{Color.CYAN}🛠  SYSTEM{Color.END}")
    print_line("U", "utility.py", "Maintenance Utility")
    print(f" {Color.RED}•{Color.END} [{Color.BOLD}Q{Color.END}] {Color.RED}Quit Manager{Color.END}")

    if IS_WINDOWS:
        print(
            f"\n{Color.DARKCYAN}{'─' * 60}\n{Color.BOLD} EMERGENCY STOP: {Color.RED}Ctrl + Shift + K{Color.END}\n{Color.DARKCYAN}{'─' * 60}{Color.END}")
    else:
        print(
            f"\n{Color.DARKCYAN}{'─' * 60}\n{Color.BOLD} Use {Color.RED}Ctrl + C{Color.END} to terminate current script\n{Color.DARKCYAN}{'─' * 60}{Color.END}")


# ==============================================================
# 5. ENTRY POINT
# ==============================================================
def main():
    setup_db()

    # Hotkey registration (Windows Only)
    if IS_WINDOWS:
        try:
            keyboard.add_hotkey('ctrl+shift+k', kill_active_process, suppress=True)
        except:
            pass

    mapping = {
        "1": "AI_gui.py", "2": "ai_headless.py", "3": "web_base.py",
        "4": "jap_cards_main.py", "5": "magic.py", "6": "neopets.py",
        "7": "altered.py", "8": "allcards.py", "v": "vibes.py", "u": "utility.py"
    }

    while True:
        draw_menu()
        try:
            choice = input(f"\n{Color.BOLD}{Color.YELLOW} Selection > {Color.END}").strip().lower()
            if choice in mapping:
                run_script(mapping[choice])
            elif choice == 'q':
                break
        except KeyboardInterrupt:
            # On Linux, hitting Ctrl+C in the menu shouldn't crash the manager
            print(f"\n{Color.YELLOW}Use 'Q' to exit properly.{Color.END}")
            time.sleep(1)


if __name__ == "__main__":
    main()