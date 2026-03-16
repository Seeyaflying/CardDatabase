import subprocess
import os
import sys
import keyboard  # pip install keyboard
import signal
import time
import json
from datetime import datetime

# File to store our timestamps
HISTORY_FILE = "run_history.json"
active_process = None


def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}


def save_history(script_name):
    history = load_history()
    history[script_name] = datetime.now().isoformat()
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f)


def get_time_ago(script_name):
    history = load_history()
    if script_name not in history:
        return "Never"
    try:
        last_run = datetime.fromisoformat(history[script_name])
        diff = datetime.now() - last_run
        if diff.days > 0:
            return f"{diff.days}d ago"
        seconds = diff.total_seconds()
        if seconds < 60:
            return "Just now"
        if seconds < 3600:
            return f"{int(seconds // 60)}m ago"
        return f"{int(seconds // 3600)}h ago"
    except:
        return "Error"


def kill_active_process():
    global active_process
    if active_process and active_process.poll() is None:
        print("\n" + "!" * 50)
        print(" [!] KILL SIGNAL DETECTED: Stopping Script...")
        print("!" * 50)
        if os.name == 'nt':
            active_process.terminate()
        else:
            os.killpg(os.getpgid(active_process.pid), signal.SIGTERM)


def run_script(script_name):
    global active_process
    if not os.path.exists(script_name):
        print(f"\n[!] Error: {script_name} not found.")
        time.sleep(1.5)
        return

    os.system('cls' if os.name == 'nt' else 'clear')
    print("=" * 60)
    print(f" RUNNING: {script_name}")
    print(f" EMERGENCY STOP: [Ctrl + Shift + K]")
    print("=" * 60)

    try:
        if os.name == 'nt':
            active_process = subprocess.Popen(
                [sys.executable, script_name],
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:
            active_process = subprocess.Popen(
                [sys.executable, script_name],
                preexec_fn=os.setsid
            )
        active_process.wait()
        save_history(script_name)
    except Exception as e:
        print(f"Error: {e}")
    finally:
        active_process = None
        print("\n>>> Returning to Menu...")
        time.sleep(1)


def print_menu_line(key, filename):
    time_ago = get_time_ago(filename)
    print(f" [{key.upper()}] {filename:<20} | Last Run: {time_ago:>9}")


def draw_menu():
    os.system('cls' if os.name == 'nt' else 'clear')
    print("=" * 60)
    print("                 AI PROJECT MASTER MANAGER                 ")
    print("=" * 60)

    # Section 1: Core AI & Web
    print("\n--- CORE SYSTEMS ---")
    print_menu_line("1", "AI GUI")
    print_menu_line("2", "AI Text")
    print_menu_line("3", "Sorter")

    # Section 2: Automation & Cards
    print("\n--- AUTOMATION & TOOLS ---")
    print_menu_line("4", "All Jap Cards")
    print_menu_line("5", "Magic: The Gathering")
    print_menu_line("6", "Neopets")
    print_menu_line("7", "Altered")
    print_menu_line("8", "All TCGPlayer")

    # Section 3: System
    print("\n--- SYSTEM ---")
    print_menu_line("U", "Utility")
    print(" [Q] Quit Manager")

    print("\n" + "=" * 60)
    print(" STOP ACTIVE SCRIPT: [Ctrl + Shift + K]")
    print("=" * 60)


def main():
    keyboard.add_hotkey('ctrl+shift+k', kill_active_process)

    # Ensure these keys match the filenames exactly
    mapping = {
        "1": "AI_gui.py",
        "2": "ai_headless.py",
        "3": "web_base.py",
        "4": "jap_cards_main.py",
        "5": "magic.py",
        "6": "neopets.py",
        "7": "Altered.py",
        "8": "allcards.py",
        "u": "utility.py"
    }

    while True:
        draw_menu()
        choice = input("\nSelection > ").strip().lower()

        if choice in mapping:
            run_script(mapping[choice])
        elif choice == 'q':
            print("Shutting down...")
            break
        else:
            print("Invalid selection.")
            time.sleep(0.5)


if __name__ == "__main__":
    main()