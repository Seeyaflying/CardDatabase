import subprocess
import os
import sys
import keyboard  # pip install keyboard
import signal
import time

# Global reference for the running process
active_process = None


def kill_process():
    """Emergency Stop: Kills the child script without closing the manager."""
    global active_process
    if active_process and active_process.poll() is None:
        print("\n\n[!!!] KILL SIGNAL: Terminating active script...")
        if os.name == 'nt':
            active_process.terminate()
        else:
            os.killpg(os.getpgid(active_process.pid), signal.SIGTERM)
        print(">>> Script Stopped. Returning to Menu.")
    else:
        pass


def run_script(script_name):
    """Executes script and tracks it for the global killer."""
    global active_process
    if not os.path.exists(script_name):
        print(f"\n[!] Error: {script_name} not found.")
        time.sleep(1.5)
        return

    print(f"\n>>> RUNNING: {script_name}")
    print(">>> STOP COMMAND: [Ctrl + Shift + K]")

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
    except Exception as e:
        print(f"\n[Runtime Error]: {e}")
        time.sleep(2)
    finally:
        active_process = None


def check_files():
    """Quick visual check of your active data files."""
    # photo_history.db removed as requested
    files = ["skipped_images.sqlite", "skipped_images.json"]
    status = []
    for f in files:
        icon = "✔" if os.path.exists(f) else "✖"
        status.append(f"{icon} {f}")
    return " | ".join(status)


def draw_menu():
    os.system('cls' if os.name == 'nt' else 'clear')
    print("=" * 64)
    print("                 AI PROJECT MASTER MANAGER                 ")
    print("=" * 64)
    print(f" ACTIVE DATA: {check_files()}")
    print("-" * 64)
    print(" [1] AI GUI (AI_gui.py)          [5] Magic Scraper")
    print(" [2] Headless AI                 [6] Neopets Scraper")
    print(" [3] Web Base (web_base.py)      [7] Altered Scraper")
    print(" [4] Resize Tool                 [8] Sorter (sorter.py)")
    print("-" * 64)
    print(" [9] SQL Update                  [0] Card AI Update")
    print(" [J] Japanese Cards (japall)     [A] All Cards Sync")
    print("-" * 64)
    print(" [T] Run Tests (test.py)         [ESC] Exit Manager")
    print("-" * 64)
    print(" EMERGENCY KILL SWITCH: [Ctrl + Shift + K]")
    print("=" * 64)
    print("\nSelect a script to launch...")


def main():
    # Register the global kill hotkey
    keyboard.add_hotkey('ctrl+shift+k', kill_process)

    mapping = {
        "1": "AI_gui.py",
        "2": "ai_headless.py",
        "3": "web_base.py",
        "4": "ResizeTool.py",
        "5": "magic.py",
        "6": "neopets.py",
        "7": "Altered.py",
        "8": "sorter.py",
        "9": "sql_update.py",
        "0": "card_ai_update.py",
        "j": "japallcards.py",
        "a": "allcards.py",
        "t": "test.py"
    }

    while True:
        draw_menu()

        event = keyboard.read_event()
        if event.event_type == keyboard.KEY_DOWN:
            key = event.name.lower()
            if key in mapping:
                run_script(mapping[key])
            elif key == 'esc':
                print("\nShutting down Manager...")
                break
            time.sleep(0.2)


if __name__ == "__main__":
    main()