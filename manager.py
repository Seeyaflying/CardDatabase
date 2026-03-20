import subprocess
import os
import sys
import sqlite3
import keyboard
import time
import traceback
from datetime import datetime

# --- CONFIGURATION ---
DB_FILE = "skipped_images.sqlite"
active_process = None


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


def setup_db():
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS last_run (script_name TEXT PRIMARY KEY, last_run_time TEXT, status TEXT)")
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
    global active_process
    if active_process and active_process.poll() is None:
        print(f"\n{Color.BOLD}{Color.RED} [!] KILL SIGNAL: Terminating...{Color.END}")
        active_process.terminate()


def run_script(script_name):
    global active_process
    if not os.path.exists(script_name):
        print(f"\n{Color.RED}[!] Error: {script_name} not found.{Color.END}")
        time.sleep(1.2);
        return
    os.system('cls');
    print(
        f"{Color.PURPLE}{'=' * 60}\n{Color.BOLD}{Color.YELLOW} EXECUTING: {script_name}\n{Color.CYAN} Press Ctrl+Shift+K to Force Stop\n{Color.PURPLE}{'=' * 60}{Color.END}\n")
    try:
        active_process = subprocess.Popen([sys.executable, script_name])
        active_process.wait()
        status = "Success" if active_process.returncode == 0 else "Stopped/Failed"
        save_history_db(script_name, status)
    except:
        save_history_db(script_name, "Failed")
    finally:
        active_process = None
        time.sleep(1)


def print_line(key, filename, display_name):
    time_str, status_color = get_run_info(filename)
    print(
        f" {status_color}•{Color.END} [{Color.BOLD}{key.upper()}{Color.END}] {display_name:<22} {Color.DARKCYAN}│{Color.END} Last: {time_str}")


def draw_menu():
    os.system('cls')
    print(
        f"{Color.BLUE}╔{'═' * 58}╗\n║{Color.BOLD}{'AI PROJECT MASTER MANAGER'.center(58)}{Color.END}{Color.BLUE}║\n╚{'═' * 58}╝{Color.END}")

    print(f"\n {Color.BOLD}{Color.PURPLE}⚡ CORE SYSTEMS{Color.END}")
    print_line("1", "AI_gui.py", "AI GUI Interface")
    print_line("2", "ai_headless.py", "AI Text Engine")
    print_line("3", "web_base.py", "Web Sorter")

    print(f"\n {Color.BOLD}{Color.GREEN}🃏 AUTOMATION & CARDS{Color.END}")
    print_line("4", "jap_cards_main.py", "All Jap Cards")
    print_line("5", "magic.py", "MTG Scraper")
    print_line("6", "neopets.py", "Neopets Scraper")
    print_line("7", "altered.py", "Altered Scraper")
    print_line("8", "allcards.py", "Global TCG Scraper")
    # Added Vibes.py here
    print_line("V", "vibes.py", "Vibes TCG Scraper")

    print(f"\n {Color.BOLD}{Color.CYAN}⚙️  SYSTEM{Color.END}")
    print_line("U", "utility.py", "Maintenance Utility")
    print(f" {Color.RED}•{Color.END} [{Color.BOLD}Q{Color.END}] {Color.RED}Quit Manager{Color.END}")
    print(
        f"\n{Color.DARKCYAN}{'─' * 60}\n{Color.BOLD} EMERGENCY STOP: {Color.RED}Ctrl + Shift + K{Color.END}\n{Color.DARKCYAN}{'─' * 60}{Color.END}")


def main():
    setup_db()
    keyboard.add_hotkey('ctrl+shift+k', kill_active_process, suppress=True)

    mapping = {
        "1": "AI_gui.py", "2": "ai_headless.py", "3": "web_base.py",
        "4": "jap_cards_main.py", "5": "magic.py", "6": "neopets.py",
        "7": "altered.py", "8": "allcards.py", "v": "vibes.py", "u": "utility.py"
    }

    while True:
        draw_menu()
        choice = input(f"\n{Color.BOLD}{Color.YELLOW} Selection > {Color.END}").strip().lower()
        if choice in mapping:
            run_script(mapping[choice])
        elif choice == 'q':
            break


if __name__ == "__main__":
    main()