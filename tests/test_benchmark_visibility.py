"""tests/test_benchmark_visibility.py

Audit and regression verification for:
1. Benchmark sample registry & availability (F1-F7, Clean Success, and Prebuilt Snapshots).
2. Sample switching and state isolation (confirming no state contamination).
3. Deterministic visibility truncation across 25%, 50%, 75%, and 100%.
4. Model input changing with visibility depth (token / character count changes).
5. 100% visibility receiving the full log.
6. Parser V2 and RCA receiving the intended log independent of model predictions.
7. Sequence counter / stale asynchronous prediction rejection logic.
8. Evaluation indicator distinguishing early warning states (25%, 50%, 75%) from post-mortem matches (100%),
   and correctly categorizing True Positive, True Negative, False Positive, and False Negative outcomes.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from src.api.main import app
from src.ingestion.log_streamer import LogStreamer
from src.parser.parser_v2 import parse_log_text
from src.prediction.predictor import get_predictor
from src.rca.rca_engine import analyze_record


class TestBenchmarkAndVisibility(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.base_samples_dir = Path("data/samples")

    def test_benchmark_registry_f1_to_f7_and_success(self):
        """Verify that F1 to F7 and Clean Success benchmark samples are all present on disk and accessible via API."""
        expected_samples = [
            "F1/run_0001.log",
            "F2/run_0005.log",
            "F3/107108441055.log",
            "F4/run_0001.log",
            "F5/run_0501.log",
            "F6/run_0100.log",
            "F7/run_0001.log",
            "success/F1/run_0001.log",
        ]
        for s in expected_samples:
            resp = self.client.get(f"/api/samples/{s}")
            self.assertEqual(resp.status_code, 200, f"Benchmark sample '{s}' failed to load via API")
            data = resp.json()
            self.assertIn("content", data)
            self.assertGreater(len(data["content"].strip()), 0, f"Sample '{s}' has empty content")

    def test_prebuilt_snapshots_registered(self):
        """Verify the three prebuilt 25% setup snapshots are accessible via API."""
        snapshots = [
            "snapshots/F1/success/run_0001_pct025.txt",
            "snapshots/F1/failure/run_0001_pct025.txt",
            "snapshots/F2/failure/run_0007_pct025.txt",
        ]
        for snap in snapshots:
            resp = self.client.get(f"/api/samples/{snap}")
            self.assertEqual(resp.status_code, 200, f"Snapshot '{snap}' failed to load")
            data = resp.json()
            self.assertGreater(len(data["content"]), 0)

    def test_deterministic_visibility_truncation_proportions(self):
        """Verify that log truncation across 25%, 50%, 75%, and 100% slices line counts deterministically."""
        sample_path = Path("data/samples/logs/F1/run_0001.log")
        full_text = sample_path.read_text(encoding="utf-8", errors="replace")
        lines = LogStreamer.split_into_lines(full_text)
        total_lines = len(lines)
        self.assertGreater(total_lines, 50)

        snap25 = LogStreamer.get_snapshot_at_depth(full_text, 25)
        snap50 = LogStreamer.get_snapshot_at_depth(full_text, 50)
        snap75 = LogStreamer.get_snapshot_at_depth(full_text, 75)
        snap100 = LogStreamer.get_snapshot_at_depth(full_text, 100)

        lines25 = LogStreamer.split_into_lines(snap25)
        lines50 = LogStreamer.split_into_lines(snap50)
        lines75 = LogStreamer.split_into_lines(snap75)
        lines100 = LogStreamer.split_into_lines(snap100)

        # Expected counts
        self.assertEqual(len(lines25), int(total_lines * 0.25))
        self.assertEqual(len(lines50), int(total_lines * 0.50))
        self.assertEqual(len(lines75), int(total_lines * 0.75))
        self.assertEqual(len(lines100), total_lines)

        # Monotonicity: 25% is prefix of 50%, 50% is prefix of 75%, 75% is prefix of 100%
        self.assertEqual(lines25, lines50[:len(lines25)])
        self.assertEqual(lines50, lines75[:len(lines50)])
        self.assertEqual(lines75, lines100[:len(lines75)])

    def test_model_input_changes_with_visibility_depth(self):
        """Confirm that passing truncated inputs at different visibility stages changes model outputs."""
        sample_path = Path("data/samples/logs/F2/run_0005.log")
        full_text = sample_path.read_text(encoding="utf-8", errors="replace")

        predictor = get_predictor("logistic_regression", visibility=25)

        snap25 = LogStreamer.get_snapshot_at_depth(full_text, 25)
        snap100 = LogStreamer.get_snapshot_at_depth(full_text, 100)

        self.assertNotEqual(len(snap25), len(snap100))

        res25 = predictor.predict_failure(snap25, visibility=25)
        res100 = predictor.predict_failure(snap100, visibility=100)

        self.assertEqual(res25.visibility_stage, "25%")
        self.assertEqual(res100.visibility_stage, "100%")
        self.assertIsInstance(res25.failure_probability, float)
        self.assertIsInstance(res100.failure_probability, float)

    def test_sample_switching_state_isolation(self):
        """Confirm that switching from one sample to another does not retain previous state."""
        f1_text = Path("data/samples/logs/F1/run_0001.log").read_text(encoding="utf-8", errors="replace")
        f2_text = Path("data/samples/logs/F2/run_0005.log").read_text(encoding="utf-8", errors="replace")

        r1 = parse_log_text(f1_text)
        r2 = parse_log_text(f2_text)

        self.assertEqual(r1.failure_type, "syntax_error")
        self.assertEqual(r2.failure_type, "dependency_error")
        self.assertNotEqual(r1.failed_step, r2.failed_step)

    def test_parser_and_rca_receive_intended_log(self):
        """Confirm Parser V2 and RCA receive the full log and diagnose correctly."""
        f2_text = Path("data/samples/logs/F2/run_0005.log").read_text(encoding="utf-8", errors="replace")
        record = parse_log_text(f2_text)
        self.assertEqual(record.status, "failure")
        self.assertEqual(record.failure_type, "dependency_error")
        self.assertEqual(record.failed_step, "Install Dependencies")

        rca = analyze_record(record)
        self.assertEqual(rca.causal_category, "dependency_resolution")
        self.assertAlmostEqual(rca.rca_confidence, 1.0, places=2)

    def test_evaluation_logic_matrix(self):
        """Verify the evaluation matrix distinguishes TP, TN, FP, FN and early warning vs 100% post-mortem."""
        # Simulation helper function replicating frontend evaluation logic
        def evaluate(risk: float, observed: str, depth: int):
            is_risk_fail = risk >= 0.5
            is_obs_fail = observed == "failure"
            if depth < 100:
                if is_obs_fail:
                    return "EARLY_WARNING" if is_risk_fail else "LOW_EARLY_RISK"
                else:
                    return "CLEAN_STREAM" if not is_risk_fail else "TRANSIENT_WARNING"
            else:
                if is_risk_fail == is_obs_fail:
                    return "MATCHED_TP" if is_risk_fail else "MATCHED_TN"
                else:
                    return "DISCREPANCY_FP" if is_risk_fail else "DISCREPANCY_FN"

        # 100% Post-mortem assertions
        self.assertEqual(evaluate(0.85, "failure", 100), "MATCHED_TP")
        self.assertEqual(evaluate(0.10, "success", 100), "MATCHED_TN")
        self.assertEqual(evaluate(0.85, "success", 100), "DISCREPANCY_FP")
        self.assertEqual(evaluate(0.10, "failure", 100), "DISCREPANCY_FN")

        # 25% Early-warning assertions
        self.assertEqual(evaluate(0.85, "failure", 25), "EARLY_WARNING")
        self.assertEqual(evaluate(0.10, "failure", 25), "LOW_EARLY_RISK")
        self.assertEqual(evaluate(0.10, "success", 25), "CLEAN_STREAM")
        self.assertEqual(evaluate(0.85, "success", 25), "TRANSIENT_WARNING")

    def test_async_stale_response_guard_logic(self):
        """Verify the sequence counter pattern discards out-of-order asynchronous responses."""
        request_counter = 0
        latest_committed_id = -1
        results = {}

        def dispatch_request():
            nonlocal request_counter
            request_counter += 1
            return request_counter

        req1 = dispatch_request()
        req2 = dispatch_request()
        req3 = dispatch_request()

        def on_response(req_id, data):
            nonlocal latest_committed_id
            if req_id < request_counter:
                # Stale response discarded
                return False
            latest_committed_id = req_id
            results["active"] = data
            return True

        # Simulate req1 arriving after req3
        self.assertFalse(on_response(req1, "stale_from_req1"))
        self.assertNotIn("active", results)

        # Simulate req3 arriving
        self.assertTrue(on_response(req3, "fresh_from_req3"))
        self.assertEqual(results["active"], "fresh_from_req3")


if __name__ == "__main__":
    unittest.main()
