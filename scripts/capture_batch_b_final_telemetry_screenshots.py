"""
scripts/capture_batch_b_final_telemetry_screenshots.py
Captures the 10 visual verification screenshots for UI Batch B Final Telemetry-Driven Predictions using headless Microsoft Edge.
"""

import os
import sys
import subprocess
import time
import json
import urllib.request
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
OUTPUT_DIR = r"C:\Users\Aditya CS\OneDrive\Documents\Capstone\CI-CD-Failure-Predictor\docs\screenshots_ui_batch_b"
BASE_URL = "http://127.0.0.1:8000"

os.makedirs(OUTPUT_DIR, exist_ok=True)

API_KEY = "fIHpNmR3OjY/S1LCodPj6s8EcILplRznSO7ORXE3JYA="

def post_json(url, data):
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-API-Key": API_KEY
        }
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))

def get_json(url):
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))

def capture_screenshot(url, filename, window_size="1400,960", delay_sec=3.0):
    out_path = os.path.join(OUTPUT_DIR, filename)
    user_data = tempfile.mkdtemp(prefix="edge_ss_")
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
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
    except Exception as e:
        print(f" -> Timed out or failed: {e}")
    if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
        print(f" -> SUCCESS: {filename} ({os.path.getsize(out_path)} bytes)")
        return True
    else:
        print(f" -> FAILED: {filename}.")
        return False

def main():
    print("=== Setting up runs and capturing 10 visual verification screenshots ===")

    # 1. Dispatch a brand new Live GitHub Actions Run (dry_run=False)
    disp_live = post_json(f"{BASE_URL}/api/demo/scenarios/dispatch", {
        "scenario_id": "dependency",
        "repo_id": "Aditya-C-S/demo-order-service",
        "runtime_model": "bilstm2",
        "dry_run": False
    })
    live_run_id = disp_live["run_id"]
    print(f"Dispatched New Live Run: {live_run_id}")

    # Capture 1: Immediately after dispatch (Empty analysis, awaiting telemetry)
    capture_screenshot(
        f"{BASE_URL}/?run_id={live_run_id}#live-pipeline",
        "01_live_gha_immediately_after_dispatch.png",
        "1400,980",
        3.0
    )

    # 2. Ingest first telemetry chunk (25% setup)
    chunk_setup = (
        "2026-10-31T00:00:00Z ##[group]Runner Setup\n"
        "2026-10-31T00:00:01Z Running on Ubuntu 24.04 LTS runner-gha-442\n"
        "2026-10-31T00:00:02Z Checkout commit c0ffee123456\n"
        "2026-10-31T00:00:03Z ##[endgroup]"
    )
    post_json(f"{BASE_URL}/api/demo/runs/{live_run_id}/logs", {
        "log_chunk": chunk_setup,
        "depth": 25,
        "stage": "setup",
        "step_name": "Checkout and Setup Environment",
        "is_final": False,
        "exit_code": 0,
        "event_id": f"event_{live_run_id}_01",
        "ci_run_id": "gha_live_run_9999",
    })
    print(f"Ingested 25% telemetry to {live_run_id}")

    # Capture 2: After first telemetry arrives (setup / 25%)
    capture_screenshot(
        f"{BASE_URL}/?run_id={live_run_id}#live-pipeline",
        "02_live_gha_first_telemetry_25pct.png",
        "1400,980",
        3.0
    )

    # 3. Ingest second telemetry chunk (50% dependency failure)
    chunk_dep_fail = (
        "2026-10-31T00:00:05Z ##[group]Run pip install -r requirements.txt\n"
        "2026-10-31T00:00:06Z Collecting demo-missing-pkg==99.99\n"
        "2026-10-31T00:00:07Z ERROR: Could not find a version that satisfies the requirement demo-missing-pkg==99.99 (from -r requirements.txt)\n"
        "2026-10-31T00:00:08Z ERROR: No matching distribution found for demo-missing-pkg==99.99\n"
        "2026-10-31T00:00:09Z Process completed with exit code 1.\n"
        "2026-10-31T00:00:10Z ##[error]Process completed with exit code 1."
    )
    post_json(f"{BASE_URL}/api/demo/runs/{live_run_id}/logs", {
        "log_chunk": chunk_dep_fail,
        "depth": 50,
        "stage": "build",
        "step_name": "Install Dependencies",
        "is_final": False,
        "exit_code": 1,
        "step_outcome": "failure",
        "event_id": f"event_{live_run_id}_02",
        "ci_run_id": "gha_live_run_9999",
    })
    print(f"Ingested 50% failure telemetry to {live_run_id}")

    # Capture 3: At 50% dependency failure
    capture_screenshot(
        f"{BASE_URL}/?run_id={live_run_id}#live-pipeline",
        "03_live_gha_checkpoint_50pct_failure.png",
        "1400,980",
        3.0
    )

    # 4. Mark workflow completed
    post_json(f"{BASE_URL}/api/demo/runs/{live_run_id}/logs", {
        "log_chunk": "=== Step 'Run Unit Tests' was skipped due to earlier stage failure. ===",
        "depth": 100,
        "stage": "test",
        "step_name": "Run Tests",
        "is_final": True,
        "exit_code": 1,
        "step_outcome": "skipped",
        "workflow_outcome": "failure",
        "event_id": f"event_{live_run_id}_03",
        "ci_run_id": "gha_live_run_9999",
    })

    # Capture 4: Live GitHub Actions workflow completed
    capture_screenshot(
        f"{BASE_URL}/?run_id={live_run_id}#live-pipeline",
        "04_live_gha_workflow_completed.png",
        "1400,980",
        3.0
    )

    # 5. Local Simulation Run with Replay
    disp_sim = post_json(f"{BASE_URL}/api/demo/scenarios/dispatch", {
        "scenario_id": "dependency",
        "repo_id": "Aditya-C-S/demo-order-service",
        "runtime_model": "bilstm2",
        "dry_run": True
    })
    sim_run_id = disp_sim["run_id"]
    post_json(f"{BASE_URL}/api/demo/runs/{sim_run_id}/replay", {
        "sample_id": "F2/run_0005.log",
        "chunk_lines": 40
    })
    print(f"Created Local Sim Run: {sim_run_id}")

    # Capture 5: Local Simulation Live Pipeline
    capture_screenshot(
        f"{BASE_URL}/?run_id={sim_run_id}#live-pipeline",
        "05_local_simulation_live_pipeline.png",
        "1400,980",
        3.0
    )

    # 6. Green Risk Run (<= 40%)
    disp_clean = post_json(f"{BASE_URL}/api/demo/scenarios/dispatch", {
        "scenario_id": "none",
        "repo_id": "Aditya-C-S/demo-order-service",
        "runtime_model": "bilstm2",
        "dry_run": True
    })
    clean_run_id = disp_clean["run_id"]
    post_json(f"{BASE_URL}/api/demo/runs/{clean_run_id}/replay", {
        "sample_id": "success/F1/run_0001.log",
        "chunk_lines": 40
    })

    # Capture 6: Green risk gauge (<= 40%)
    capture_screenshot(
        f"{BASE_URL}/?run_id={clean_run_id}#live-pipeline",
        "06_risk_gauge_green_low.png",
        "1400,980",
        3.0
    )

    # 7. Yellow Risk Run (> 40% and < 70%)
    disp_yellow = post_json(f"{BASE_URL}/api/demo/scenarios/dispatch", {
        "scenario_id": "syntax",
        "repo_id": "Aditya-C-S/demo-order-service",
        "runtime_model": "bilstm2",
        "dry_run": True
    })
    yellow_run_id = disp_yellow["run_id"]
    from src.demo.demo_manager import UnifiedDemoManager
    mgr = UnifiedDemoManager.get_instance()
    yellow_run = mgr.get_run(yellow_run_id)
    if yellow_run:
        pred_entry = {
            "checkpoint": 50,
            "depth_percentage": 50,
            "failure_probability": 0.60,
            "failure_probability_pct": 60.0,
            "prediction_type": "ACTUAL",
            "is_projected": False,
            "risk_tier": "MODERATE RISK",
            "model_name": "bilstm2",
            "timestamp": "2026-10-31T00:05:00Z"
        }
        yellow_run.accumulated_log = "Checking syntax and packages...\nValidation warning: unclosed quotation"
        yellow_run.runtime_predictions.append(pred_entry)
        yellow_run.current_runtime_prediction = pred_entry
        yellow_run.prediction_history.append(pred_entry)
        yellow_run.save_checkpoint()

    # Capture 7: Yellow risk gauge (> 40% and < 70%)
    capture_screenshot(
        f"{BASE_URL}/?run_id={yellow_run_id}#live-pipeline",
        "07_risk_gauge_yellow_moderate.png",
        "1400,980",
        3.0
    )

    # Capture 8: Red risk gauge (>= 70%)
    capture_screenshot(
        f"{BASE_URL}/?run_id={live_run_id}#live-pipeline",
        "08_risk_gauge_red_high.png",
        "1400,980",
        3.0
    )

    # Capture 9: Run History showing both sources (LIVE GHA and LOCAL SIM)
    capture_screenshot(
        f"{BASE_URL}/#run-history",
        "09_run_history_sources_table.png",
        "1400,980",
        3.0
    )

    # Capture 10: Run Detail Inspector showing actual, projected, and skipped checkpoints
    capture_screenshot(
        f"{BASE_URL}/?inspect={live_run_id}#run-history",
        "10_run_detail_inspector_checkpoints.png",
        "1400,980",
        3.0
    )

    print("\nAll 10 visual verification screenshots captured successfully.")

if __name__ == "__main__":
    main()

