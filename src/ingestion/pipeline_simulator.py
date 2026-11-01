"""src/ingestion/pipeline_simulator.py

Simulates the end-to-end CI/CD failure prediction, evidence parsing,
root cause analysis, and remediation pipeline.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from src.ingestion.log_streamer import LogStreamer
from src.parser.parser_v2 import LogRecord, parse_log_text
from src.prediction.predictor import get_predictor
from src.rca.rca_engine import get_default_engine, RCAReport
from src.remediation.suggestions import RemediationAdvisor

logger = logging.getLogger(__name__)


@dataclass
class SimulationReport:
    """Full end-to-end pipeline execution report."""
    run_id: str
    model_name: str
    predictions_by_depth: Dict[str, Dict[str, Any]]
    final_failure_risk: float
    parsed_record: Dict[str, Any]
    rca_report: Dict[str, Any]
    remediation: Dict[str, Any]
    overall_status: str  # 'PASS' or 'FAIL' based on observed outcome
    predicted_outcome: str = "failure"  # 'failure' or 'success'
    observed_outcome: str = "unknown"   # 'failure' or 'success'
    outcome_agreement: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "model_name": self.model_name,
            "predictions_by_depth": self.predictions_by_depth,
            "final_failure_risk": round(self.final_failure_risk, 4),
            "parsed_record": self.parsed_record,
            "rca_report": self.rca_report,
            "remediation": self.remediation,
            "overall_status": self.overall_status,
            "predicted_outcome": self.predicted_outcome,
            "observed_outcome": self.observed_outcome,
            "outcome_agreement": self.outcome_agreement,
        }


class PipelineSimulator:
    """Coordinates end-to-end CI/CD pipeline simulation."""

    def __init__(self, model_name: str = "logistic_regression"):
        self.model_name = model_name
        self.rca_engine = get_default_engine()

    def simulate(
        self,
        log_text: str,
        run_id: str = "simulation_run",
        depths: Optional[List[int]] = None,
    ) -> SimulationReport:
        """
        Run the full progressive simulation:
        1. Slice log text into 25%, 50%, 75%, 100% snapshots.
        2. Predict failure probability at each stage.
        3. Parse complete log with Parser V2.
        4. Infer root cause with RCA Engine.
        5. Generate remediation guidance.
        """
        if depths is None:
            depths = [25, 50, 75, 100]

        # 1. Generate progressive snapshots & run predictions
        predictions: Dict[str, Dict[str, Any]] = {}
        for d in depths:
            snapshot = LogStreamer.get_snapshot_at_depth(log_text, d)
            try:
                predictor = get_predictor(self.model_name, visibility=d)
                res = predictor.predict_failure(snapshot, visibility=d)
                predictions[f"{d}%"] = res.to_dict()
            except Exception as e:
                logger.warning("Prediction failed at depth %d: %s", d, e)
                predictions[f"{d}%"] = {"error": str(e), "depth": d}

        # Use 25% or highest available early depth for primary risk indication
        primary_depth = "25%" if "25%" in predictions and "failure_probability" in predictions["25%"] else list(predictions.keys())[0]
        primary_risk = predictions.get(primary_depth, {}).get("failure_probability", 0.0)

        # 2. Extract structured evidence with Parser V2
        log_record = parse_log_text(log_text, run_id=run_id)
        parsed_dict = log_record.to_dict()

        # 3. Diagnose root cause with RCA Engine
        rca_res = self.rca_engine.analyze_record(log_record)
        rca_dict = rca_res.to_dict()
        rca_dict["confidence"] = getattr(rca_res, "rca_confidence", None)

        # 4. Generate remediation
        remediation = RemediationAdvisor.generate_remediation(rca_res, log_text=log_text)

        # 5. Distinctly compute observed outcome, predicted outcome, and agreement
        observed_status = (log_record.status or "unknown").lower()
        predicted_outcome = "failure" if primary_risk >= 0.5 else "success"
        outcome_agreement = (predicted_outcome == observed_status)
        overall_status = "PASS" if observed_status == "success" else "FAIL"

        return SimulationReport(
            run_id=run_id,
            model_name=self.model_name,
            predictions_by_depth=predictions,
            final_failure_risk=primary_risk,
            parsed_record=parsed_dict,
            rca_report=rca_dict,
            remediation=remediation,
            overall_status=overall_status,
            predicted_outcome=predicted_outcome,
            observed_outcome=observed_status,
            outcome_agreement=outcome_agreement,
        )


def run_pipeline_simulation(log_text: str, model_name: str = "logistic_regression", run_id: str = "sim_001") -> Dict[str, Any]:
    """Helper entry point for quick simulation."""
    sim = PipelineSimulator(model_name=model_name)
    report = sim.simulate(log_text=log_text, run_id=run_id)
    return report.to_dict()
