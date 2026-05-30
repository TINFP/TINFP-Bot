#!/usr/bin/env python3
# tmanager.py - Watchdog Process Manager for tinfp.py

import subprocess
import time
import os
import signal
import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [MANAGER] %(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)

# --- Configuration ---
BOT_SCRIPT = "tinfp.py"
HEARTBEAT_FILE = "t-heartbeat.txt"   # File the bot updates to prove it's alive
HEARTBEAT_TIMEOUT = 10            # Seconds without an update before we consider it FROZEN
CHECK_INTERVAL = 5                # How often the manager checks the heartbeat
RESTART_DELAY = 0                  # Seconds to wait before restarting the bot
# ---------------------

def get_heartbeat_time():
    """Reads the last heartbeat timestamp from the file."""
    try:
        with open(HEARTBEAT_FILE, "r") as f:
            return float(f.read().strip())
    except (FileNotFoundError, ValueError):
        return 0

def kill_process(proc):
    """Gracefully kills the bot process, forcefully if needed."""
    if proc.poll() is not None:
        return  # Already dead
    
    pid = proc.pid
    logger.info(f"Terminating process {pid}...")
    
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return

    # Wait up to 10 seconds for it to close gracefully
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        logger.warning(f"Process {pid} did not exit gracefully. Force killing (SIGKILL)...")
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()

def main():
    logger.info(f"Starting manager for {BOT_SCRIPT}...")
    
    # Clean up old heartbeat file on manager start
    if os.path.exists(HEARTBEAT_FILE):
        os.remove(HEARTBEAT_FILE)

    proc = None

    while True:
        try:
            # 1. If the bot isn't running, start it
            if proc is None or proc.poll() is not None:
                if proc is not None and proc.poll() is not None:
                    exit_code = proc.poll()
                    logger.error(f"Bot crashed with exit code {exit_code}. Restarting in {RESTART_DELAY}s...")
                    time.sleep(RESTART_DELAY)
                else:
                    logger.info(f"Launching {BOT_SCRIPT}...")

                # Clean heartbeat before start
                if os.path.exists(HEARTBEAT_FILE):
                    os.remove(HEARTBEAT_FILE)

                # Run the bot script using the same Python executable
                proc = subprocess.Popen([sys.executable, BOT_SCRIPT])
                time.sleep(RESTART_DELAY) # Give it time to boot up
                continue

            # 2. Check heartbeat (Freeze Detection)
            heartbeat = get_heartbeat_time()
            current_time = time.time()

            if heartbeat > 0 and (current_time - heartbeat) > HEARTBEAT_TIMEOUT:
                logger.error(f"⚠️ BOT FROZEN! No heartbeat for {int(current_time - heartbeat)}s. Killing and restarting...")
                kill_process(proc)
                proc = None
                continue

            # 3. Wait before checking again
            time.sleep(CHECK_INTERVAL)

        except KeyboardInterrupt:
            logger.info("Manager stopping. Shutting down bot...")
            if proc and proc.poll() is None:
                kill_process(proc)
            break
        except Exception as e:
            logger.error(f"Manager internal error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()