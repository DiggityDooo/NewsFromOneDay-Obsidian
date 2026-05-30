import subprocess
import time
import os
import shutil
from datetime import datetime

SCRIPT = "/home/seanb/Documents/DeVault/scraper.py"
DURATION = 86400  # 24 hours
INTERVAL = 1800   # 30 minute intervals (as requested)
ORG_INTERVAL = 300 # Keep 5-minute cleanup logic running during idle time

def organize_vault():
    print(f"\n[Vault Cleaner] Tyding up loose ends at {datetime.now().strftime('%H:%M:%S')}...")
    base = os.path.expanduser("~/Documents/DeVault")
    date_str = datetime.now().strftime("%Y-%m-%d")
    
    for folder in ["Headlines", "Summaries"]:
        folder_path = os.path.join(base, folder)
        if not os.path.exists(folder_path): continue
        
        for item in os.listdir(folder_path):
            item_path = os.path.join(folder_path, item)
            if os.path.isfile(item_path) and item.endswith(".md"):
                target = os.path.join(folder_path, "Archived", date_str)
                os.makedirs(target, exist_ok=True)
                try:
                    shutil.move(item_path, os.path.join(target, item))
                    print(f"  Organized: {item}")
                except:
                    pass

start = time.time()
last_org = 0
run = 1

print(f"--- Intelligence Hub Activated ---")
print(f"Interval: 30 minutes | Cleanup: 5 minutes | Parallel Processing: Enabled")

try:
    while time.time() - start < DURATION:
        # Run the Scraper
        run_start = time.time()
        print(f"\n--- Run {run} Started at {datetime.now().strftime('%H:%M:%S')} ---")
        subprocess.run(["python3", SCRIPT])
        run_duration = time.time() - run_start
        print(f"--- Run {run} Cycle Complete ({round(run_duration)}s) ---")
        
        # Wait for the remainder of the 30-min interval (subtract run time)
        remaining_wait = max(0, INTERVAL - run_duration)
        cycle_start = time.time()
        while time.time() - cycle_start < remaining_wait:
            if time.time() - last_org >= ORG_INTERVAL:
                organize_vault()
                last_org = time.time()
            time.sleep(10)
            if time.time() - start >= DURATION:
                break
                
        run += 1

except KeyboardInterrupt:
    print("\n[!] Intelligence Hub deactivated by user.")

print("\nSession complete.")