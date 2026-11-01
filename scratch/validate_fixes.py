import json
from pathlib import Path
from src.ingestion.pipeline_simulator import PipelineSimulator
from src.parser.parser_v2 import parse_log_text
from src.rca.engine import get_default_engine

PROJECT_ROOT = Path(__file__).resolve().parent.parent

def test_samples():
    print("=" * 60)
    print("RUNNING VALIDATION OF FIXES (ISSUES 1-4)")
    print("=" * 60)

    # 1. Dependency failure sample
    dep_log_path = PROJECT_ROOT / "data" / "samples" / "logs" / "F2" / "run_0005.log"
    dep_text = dep_log_path.read_text(encoding="utf-8")

    sim = PipelineSimulator(model_name="logistic_regression")
    dep_report = sim.simulate(log_text=dep_text, run_id="test_dep_005")
    dep_dict = dep_report.to_dict()

    print("\n--- DEPENDENCY FAILURE SAMPLE ---")
    print(f"Observed Status: {dep_dict['parsed_record']['status']}")
    print(f"Failed Step: {dep_dict['parsed_record']['failed_step']}")
    print(f"Error Category: {dep_dict['parsed_record']['failure_type']}")
    print(f"RCA Category: {dep_dict['rca_report']['causal_category']}")
    print(f"RCA Confidence in report: {dep_dict['rca_report'].get('rca_confidence')} / {dep_dict['rca_report'].get('confidence')}")
    print(f"Overall Status: {dep_dict['overall_status']}")
    print(f"Predicted Outcome: {dep_dict['predicted_outcome']}")
    print(f"Observed Outcome: {dep_dict['observed_outcome']}")
    print(f"Outcome Agreement: {dep_dict['outcome_agreement']}")

    # Validation checks
    assert dep_dict['parsed_record']['status'] == "failure"
    assert "Install" in (dep_dict['parsed_record']['failed_step'] or "")
    assert dep_dict['parsed_record']['failure_type'] == "dependency_error"
    assert dep_dict['rca_report']['causal_category'] == "dependency_resolution"
    conf = dep_dict['rca_report'].get('confidence')
    assert conf is not None and not isinstance(conf, str) and conf >= 0.0, f"Invalid confidence: {conf}"
    print(">> Dependency Failure Checks: ALL PASSED")

    # 2. Successful build sample
    succ_log_path = PROJECT_ROOT / "data" / "samples" / "logs" / "success" / "F1" / "run_0001.log"
    succ_text = succ_log_path.read_text(encoding="utf-8")

    succ_report = sim.simulate(log_text=succ_text, run_id="test_succ_001")
    succ_dict = succ_report.to_dict()

    print("\n--- SUCCESSFUL BUILD SAMPLE ---")
    print(f"Observed Status: {succ_dict['parsed_record']['status']}")
    print(f"Parser Failed Step: {succ_dict['parsed_record']['failed_step']}")
    print(f"RCA Category: {succ_dict['rca_report']['causal_category']}")
    print(f"RCA Summary: {succ_dict['rca_report']['summary']}")
    print(f"RCA Confidence in report: {succ_dict['rca_report'].get('rca_confidence')} / {succ_dict['rca_report'].get('confidence')}")
    print(f"Overall Status: {succ_dict['overall_status']}")
    print(f"Predicted Outcome: {succ_dict['predicted_outcome']}")
    print(f"Observed Outcome: {succ_dict['observed_outcome']}")
    print(f"Outcome Agreement: {succ_dict['outcome_agreement']}")
    print(f"Predictions by Depth:")
    for d, p in succ_dict['predictions_by_depth'].items():
        print(f"  {d}: {p.get('failure_probability', 0.0) * 100:.1f}% risk")

    # Validation checks
    assert succ_dict['parsed_record']['status'] == "success"
    assert succ_dict['observed_outcome'] == "success"
    assert succ_dict['overall_status'] == "PASS"
    assert succ_dict['rca_report']['causal_category'] in ("causal_unknown", "unknown")
    print(">> Successful Build Checks: ALL PASSED")

    print("\n" + "=" * 60)
    print("ALL VALIDATION CRITERIA VERIFIED SUCCESSFULLY!")
    print("=" * 60)

if __name__ == "__main__":
    test_samples()
