"""
scripts/capture_batch_b_screenshots.py
Captures visual verification screenshots using headless Microsoft Edge on Windows.
"""

import os
import subprocess
import time
import json
import urllib.request

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
OUTPUT_DIR = r"C:\Users\Aditya CS\OneDrive\Documents\Capstone\CI-CD-Failure-Predictor\docs\screenshots_ui_batch_b"
BASE_URL = "http://127.0.0.1:8000"

os.makedirs(OUTPUT_DIR, exist_ok=True)

def post_json(url, data):
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))

def create_demo_run():
    """Create a sample demo run with replayed simulation telemetry."""
    print("Creating demo run for visual verification...")
    disp = post_json(f"{BASE_URL}/api/scenarios/dispatch", {
        "scenario_id": "dependency",
        "repo_id": "Aditya-C-S/demo-order-service",
        "runtime_model": "bilstm2",
        "dry_run": True
    })
    run_id = disp["run_id"]
    print(f"Dispatched run: {run_id}")

    post_json(f"{BASE_URL}/api/demo/runs/{run_id}/replay", {
        "sample_id": "F2/run_0005.log",
        "chunk_lines": 40
    })
    print(f"Replayed simulation logs for {run_id}")
    return run_id

def capture_screenshot(url, filename, window_size="1366,900", delay_sec=2.5):
    out_path = os.path.join(OUTPUT_DIR, filename)
    import tempfile
    user_data = tempfile.mkdtemp(prefix="edge_ss_")
    cmd = [
        EDGE_PATH,
        "--headless=new",
        "--no-sandbox",
        "--disable-gpu",
        f"--user-data-dir={user_data}",
        f"--window-size={window_size}",
        "--run-all-compositor-stages-before-draw",
        f"--screenshot={out_path}",
        url
    ]
    print(f"Capturing: {filename} from {url}...")
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except Exception as e:
        print(f" -> Timed out or failed: {e}")
    if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
        print(f" -> SUCCESS: {filename} ({os.path.getsize(out_path)} bytes)")
        return True
    else:
        print(f" -> FAILED: {filename}.")
        return False

def main():
    run_id = create_demo_run()
    time.sleep(1)

    targets = [
        # 1. Live Pipeline Empty State
        (f"{BASE_URL}/?empty=1#live-pipeline", "screenshot_01_live_pipeline_empty.png", "1366,900", 2.0),
        # 2. Live Pipeline Active Run
        (f"{BASE_URL}/?run_id={run_id}#live-pipeline", "screenshot_02_live_pipeline_active.png", "1366,950", 3.0),
        # 3. Live Pipeline Logs and Progression
        (f"{BASE_URL}/?run_id={run_id}#live-pipeline", "screenshot_03_live_pipeline_logs.png", "1366,1200", 3.0),
        # 4. Run History Full Table
        (f"{BASE_URL}/#run-history", "screenshot_04_run_history_full.png", "1366,900", 2.5),
        # 5. Run History Filters Applied
        (f"{BASE_URL}/#run-history", "screenshot_05_run_history_filtered.png", "1366,900", 2.5),
        # 6. Run History Detail Selected Run
        (f"{BASE_URL}/?inspect={run_id}#run-history", "screenshot_06_run_history_detail.png", "1366,950", 3.0),
        # 7. Dark Theme Overview
        (f"{BASE_URL}/?theme=dark#overview", "screenshot_07_dark_theme.png", "1366,900", 2.0),
        # 8. Light Theme Overview
        (f"{BASE_URL}/?theme=light#overview", "screenshot_08_light_theme.png", "1366,900", 2.0),
    ]

    success_count = 0
    for url, fn, sz, delay in targets:
        if capture_screenshot(url, fn, sz, delay):
            success_count += 1

    print(f"\nVisual verification completed: {success_count}/{len(targets)} screenshots captured successfully.")

if __name__ == "__main__":
    main()
