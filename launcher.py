import os
import subprocess
import sys
import signal
import time
from datetime import datetime
from pymongo import MongoClient

MONGO_URI = "mongodb://card_manager:1369@100.80.179.119:27018/carddb"
DB_NAME   = "carddb"
HISTORY_COLLECTION = "last_run"

IS_WINDOWS = os.name == 'nt'
active_process = None

# Anchor everything to launcher.py's own folder, so it works no matter where you launch from
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class Color:
    PURPLE = '\033[95m'; CYAN = '\033[96m'; DARKCYAN = '\033[36m'
    BLUE = '\033[94m'; GREEN = '\033[92m'; YELLOW = '\033[93m'
    RED = '\033[91m'; BOLD = '\033[1m'; END = '\033[0m'


def get_history_collection():
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    return client[DB_NAME][HISTORY_COLLECTION], client


def save_history_db(script_name, status="Success"):
    now = datetime.now().isoformat()
    try:
        coll, client = get_history_collection()
        coll.update_one(
            {"script_name": script_name},
            {"$set": {"script_name": script_name, "last_run_time": now, "status": status}},
            upsert=True,
        )
        client.close()
    except Exception as e:
        print(f"{Color.RED}Mongo Error: {e}{Color.END}")


def get_run_info(script_name):
    try:
        coll, client = get_history_collection()
        doc = coll.find_one({"script_name": script_name})
        client.close()
        if not doc:
            return f"{Color.YELLOW}Never{Color.END}", Color.YELLOW

        last_run = datetime.fromisoformat(doc["last_run_time"])
        diff = datetime.now() - last_run
        status_color = Color.GREEN if doc["status"] == "Success" else Color.RED

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
    except Exception:
        return "Error", Color.RED


def kill_active_process():
    global active_process
    if active_process and active_process.poll() is None:
        print(f"\n{Color.BOLD}{Color.RED} [!] KILL SIGNAL: Terminating child process...{Color.END}")
        if IS_WINDOWS:
            active_process.terminate()
        else:
            os.kill(active_process.pid, signal.SIGTERM)


def run_script(script_name):
    global active_process
    full_path = os.path.join(BASE_DIR, script_name)
    if not os.path.exists(full_path):
        print(f"\n{Color.RED}[!] Error: {script_name} not found.{Color.END}")
        time.sleep(1.5)
        return

    os.system("cls" if IS_WINDOWS else "clear")
    print(f"{Color.PURPLE}{'=' * 60}")
    print(f"{Color.BOLD}{Color.YELLOW} EXECUTING: {script_name}")

    if IS_WINDOWS:
        print(f"{Color.CYAN} Press Ctrl+Shift+K to Force Stop")
    else:
        print(f"{Color.CYAN} Running in Subprocess (Standard Linux Terminal)")

    print(f"{Color.PURPLE}{'=' * 60}{Color.END}\n")

    try:
        active_process = subprocess.Popen([sys.executable, full_path])
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


def print_line(key, filename, display_name):
    time_str, status_color = get_run_info(filename)
    print(
        f" {status_color}•{Color.END} [{Color.BOLD}{key.upper()}{Color.END}] {display_name:<22} {Color.DARKCYAN}»{Color.END} Last: {time_str}")
