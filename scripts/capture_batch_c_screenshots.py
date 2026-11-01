"""
scripts/capture_batch_c_screenshots.py
Captures the 17 visual verification screenshots for UI Batch C:
Metadata Intelligence, Neo4j Graph Intelligence, Multi-Model Comparison,
Root Cause Analysis, Clear Live Session, and Unified Run Summary.
"""

import os
import sys
import subprocess
import time
import tempfile
import urllib.request
import json
import shutil

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
OUTPUT_DIR = r"C:\Users\Aditya CS\OneDrive\Documents\Capstone\CI-CD-Failure-Predictor\docs\screenshots_ui_batch_c"
ARTIFACT_DIR = r"C:\Users\Aditya CS\.gemini\antigravity\brain\09717549-be0c-43d2-998c-d9f742d425e9\screenshots_c"
BASE_URL = "http://127.0.0.1:8000"

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(ARTIFACT_DIR, exist_ok=True)


def capture_screenshot(url, filename, window_size="1440,960", delay_sec=4.0):
    out_path = os.path.join(OUTPUT_DIR, filename)
    user_data = tempfile.mkdtemp(prefix="edge_ss_c_")
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
    print("=== UI Batch C Visual Verification Screenshot Capture ===")

    # 1-5: Metadata Intelligence
    capture_screenshot(f"{BASE_URL}/#metadata-intel", "01_metadata_overview_gauge.png", "1440,960", 4.0)
    capture_screenshot(f"{BASE_URL}/#metadata-intel", "02_metadata_38_feature_inspection.png", "1440,1200", 4.5)
    capture_screenshot(f"{BASE_URL}/#metadata-intel", "03_metadata_feature_provenance_completeness.png", "1440,960", 4.0)
    capture_screenshot(f"{BASE_URL}/#metadata-intel", "04_metadata_shap_waterfall.png", "1440,1100", 4.5)
    capture_screenshot(f"{BASE_URL}/#metadata-intel", "05_metadata_commit_comparison.png", "1440,1100", 4.5)

    # 6-10: Graph Intelligence
    capture_screenshot(f"{BASE_URL}/#graph-intel", "06_graph_overview_connection_status.png", "1440,960", 4.5)
    capture_screenshot(f"{BASE_URL}/#graph-intel", "07_graph_interactive_cytoscape_canvas.png", "1440,1080", 5.0)
    capture_screenshot(f"{BASE_URL}/#graph-intel", "08_graph_impact_score_card.png", "1440,960", 4.5)
    capture_screenshot(f"{BASE_URL}/#graph-intel", "09_graph_blast_radius_analysis.png", "1440,960", 4.5)
    capture_screenshot(f"{BASE_URL}/#graph-intel", "10_graph_node_inspector_panel.png", "1440,1080", 5.0)

    # 11-13: Model Comparison
    capture_screenshot(f"{BASE_URL}/#model-comparison", "11_model_comparison_overview_cards.png", "1440,960", 4.5)
    capture_screenshot(f"{BASE_URL}/#model-comparison", "12_model_comparison_checkpoint_table.png", "1440,1000", 4.5)
    capture_screenshot(f"{BASE_URL}/#model-comparison", "13_model_comparison_progression_chart.png", "1440,1080", 4.5)

    # 14-16: Root Cause Analysis
    capture_screenshot(f"{BASE_URL}/#rca", "14_rca_overview_failure_category.png", "1440,960", 4.5)
    capture_screenshot(f"{BASE_URL}/#rca", "15_rca_evidence_timeline_and_causes.png", "1440,1200", 4.5)
    capture_screenshot(f"{BASE_URL}/#rca", "16_rca_prescriptive_remediation_commands.png", "1440,1100", 4.5)

    # 17: Live Pipeline & Clear Live Session / Run Inspector
    capture_screenshot(f"{BASE_URL}/#live-pipeline", "17_clear_live_session_and_run_summary.png", "1440,960", 4.0)

    print("\nVisual verification screenshots captured successfully.")


if __name__ == "__main__":
    main()

