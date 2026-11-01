"""
scripts/capture_preset_simulation.py
Captures screenshots of Metadata Intel in Scenario Simulation Mode.
"""
import os
import subprocess
import tempfile
import shutil

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
OUTPUT_DIR = r"C:\Users\Aditya CS\OneDrive\Documents\Capstone\CI-CD-Failure-Predictor\docs\screenshots_ui_batch_c"
ARTIFACT_DIR = r"C:\Users\Aditya CS\.gemini\antigravity\brain\09717549-be0c-43d2-998c-d9f742d425e9\screenshots_c"
BASE_URL = "http://127.0.0.1:8000"

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(ARTIFACT_DIR, exist_ok=True)


def capture(url, filename, window_size="1440,1100", delay_sec=4.0):
    out_path = os.path.join(OUTPUT_DIR, filename)
    user_data = tempfile.mkdtemp(prefix="edge_preset_")
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
            print(f" -> Failed: {res.stderr}")
            return False
    finally:
        try:
            shutil.rmtree(user_data, ignore_errors=True)
        except Exception:
            pass


def main():
    capture(f"{BASE_URL}/?meta_preset=syntax#metadata-intel", "06_metadata_preset_syntax_simulation.png", "1440,1150", 4.5)
    capture(f"{BASE_URL}/?meta_preset=dependency#metadata-intel", "07_metadata_preset_dependency_simulation.png", "1440,1150", 4.5)


if __name__ == "__main__":
    main()
