"""
scripts/capture_metadata_graph_screenshots.py
Captures updated screenshots for Metadata Intel Redesign and Graph Intel GIS / Full Architecture.
"""

import os
import sys
import subprocess
import time
import tempfile
import shutil

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
OUTPUT_DIR = r"C:\Users\Aditya CS\OneDrive\Documents\Capstone\CI-CD-Failure-Predictor\docs\screenshots_ui_batch_c"
ARTIFACT_DIR = r"C:\Users\Aditya CS\.gemini\antigravity\brain\09717549-be0c-43d2-998c-d9f742d425e9\screenshots_c"
BASE_URL = "http://127.0.0.1:8000"

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(ARTIFACT_DIR, exist_ok=True)


def capture_screenshot(url, filename, window_size="1440,960", delay_sec=4.0):
    out_path = os.path.join(OUTPUT_DIR, filename)
    user_data = tempfile.mkdtemp(prefix="edge_ss_redesign_")
    cmd = [
        EDGE_PATH,
        "--headless=new",
        "--no-sandbox",
        "--disable-gpu",
        f"--user-data-dir={user_data}",
        f"--window-size={window_size}",
        "--run-all-compositor-stages-before-draw",
        f"--virtual-time-budget={int(delay_sec * 1000)}",
        f"--screenshot={out_path}",
        url
    ]
    print(f"Capturing: {filename} from {url}...")
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if os.path.exists(out_path):
            shutil.copy2(out_path, os.path.join(ARTIFACT_DIR, filename))
            print(f" -> Saved {filename} ({os.path.getsize(out_path)} bytes)")
            return True
        else:
            print(f" -> File not created: {res.stderr}")
            return False
    except Exception as e:
        print(f" -> Timed out or failed: {e}")
        return False
    finally:
        try:
            shutil.rmtree(user_data, ignore_errors=True)
        except Exception:
            pass


def main():
    print("=== Capturing Redesigned Metadata Intel & Verified Graph Intel Screenshots ===")
    capture_screenshot(f"{BASE_URL}/#metadata-intel", "01_metadata_overview_redesign.png", "1440,1050", 4.5)
    capture_screenshot(f"{BASE_URL}/#metadata-intel", "02_metadata_shap_and_summary.png", "1440,1400", 5.0)
    capture_screenshot(f"{BASE_URL}/#graph-intel", "03_graph_intel_gis_score_card.png", "1440,1000", 4.5)
    capture_screenshot(f"{BASE_URL}/graph-explorer?repo_id=Aditya-C-S/demo-order-service&mode=blast_radius", "04_graph_explorer_blast_radius.png", "1440,900", 4.0)
    capture_screenshot(f"{BASE_URL}/graph-explorer?repo_id=Aditya-C-S/demo-order-service&mode=full", "05_graph_explorer_full_architecture.png", "1440,900", 4.5)
    print("\nCapture finished successfully.")


if __name__ == "__main__":
    main()

