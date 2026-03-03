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
    """Stops the running script and returns control to the menu prompt."""
    global active_process
    if active_process and active_process.poll() is None:
        print("\n" + "!" * 50)
        print(" [!] KILL SIGNAL DETECTED: Stopping Script...")
        print(" [!] Returning to Menu Input...")
        print("!" * 50)

        if os.name == 'nt':
            active_process.terminate()
        else:
            os.killpg(os.getpgid(active_process.pid), signal.SIGTERM)
    else:
        pass


def run_script(script_name):
    global active_process
    if not os.path.exists(script_name):
        print(f"\n[!] Error: {script_name} not found.")
        input("Press Enter to continue...")
        return

    os.system('cls' if os.name == 'nt' else 'clear')
    print("=" * 50)
    print(f" RUNNING: {script_name}")
    print(f" EMERGENCY STOP: [Ctrl + Shift + K]")
    print("=" * 50)

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
        print("\n>>> Script execution finished.")
        time.sleep(1)


def draw_menu():
    os.system('cls' if os.name == 'nt' else 'clear')
    print("=" * 78)
    print("                        AI PROJECT MASTER MANAGER                        ")
    print("=" * 78)

    menu_items = [
        ("1", "AI_gui.py"), ("5", "magic.py"),
        ("2", "ai_headless.py"), ("6", "neopets.py"),
        ("3", "web_base.py"), ("7", "Altered.py"),
        ("4", "ResizeTool.py"), ("8", "sorter.py"),
        ("9", "sql_update.py"), ("0", "card_ai_update.py"),
        ("J", "japallcards.py"), ("A", "allcards.py"),
        ("T", "test.py"), ("Q", "Quit Manager")
    ]

    # Print in two columns
    for i in range(0, len(menu_items), 2):
        k1, f1 = menu_items[i]
        t1 = get_time_ago(f1) if f1 != "Quit Manager" else ""

        if i + 1 < len(menu_items):
            k2, f2 = menu_items[i + 1]
            t2 = get_time_ago(f2) if f2 != "Quit Manager" else ""
            line = f" [{k1}] {f1:<18} ({t1:>9})    |    [{k2}] {f2:<18} ({t2:>9})"
        else:
            line = f" [{k1}] {f1:<18} ({t1:>9})"
        print(line)

    print("-" * 78)
    print(" STOP RUNNING SCRIPT: [Ctrl + Shift + K]")
    print("=" * 78)


def main():
    # Keep the global kill listener active in the background
    keyboard.add_hotkey('ctrl+shift+k', kill_active_process)

    mapping = {
        "1": "AI_gui.py", "2": "ai_headless.py", "3": "web_base.py",
        "4": "ResizeTool.py", "5": "magic.py", "6": "neopets.py",
        "7": "Altered.py", "8": "sorter.py", "9": "sql_update.py",
        "0": "card_ai_update.py", "j": "japallcards.py", "a": "allcards.py",
        "t": "test.py"
    }

    while True:
        draw_menu()
        choice = input("\nEnter selection and press Enter: ").strip().lower()

        if choice in mapping:
            run_script(mapping[choice])
        elif choice == 'q':
            print("Shutting down...")
            break
        else:
            print("Invalid selection. Try again.")
            time.sleep(0.8)


if __name__ == "__main__":
    main()