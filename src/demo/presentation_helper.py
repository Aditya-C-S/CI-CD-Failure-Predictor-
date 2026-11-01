"""
src/demo/presentation_helper.py

Presentation-layer projection and evidence display utilities for runtime prediction dashboard.
Calculates deterministic projected risk for unexecuted/future checkpoints without mutating
historical ML model predictions or feeding projected values into inference models.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


CHECKPOINT_DEPTHS = [25, 50, 75, 100]


def classify_evidence_strength(
    total_lines: int,
    is_low_evidence: bool = False,
    pad_ratio: Optional[float] = None,
    evidence_indicators: Optional[List[str]] = None,
) -> Dict[str, str]:
    """
    Classify evidence strength based on log volume, token padding, and presence of concrete indicators.
    Independent of failure risk probability.
    """
    indicators = evidence_indicators or []
    pad = pad_ratio or 0.0

    if is_low_evidence or total_lines < 8 or pad > 0.85:
        return {
            "strength": "LIMITED",
            "label": "Limited Evidence",
            "tooltip": "Early-stage or sparse log output. Model prediction relies on baseline priors due to limited log volume.",
        }
    elif len(indicators) > 0 or total_lines >= 20:
        return {
            "strength": "ROBUST",
            "label": "Robust Evidence",
            "tooltip": "Substantial log volume with concrete execution markers and status indicators.",
        }
    else:
        return {
            "strength": "MODERATE",
            "label": "Moderate Evidence",
            "tooltip": "Adequate execution output for baseline inference without significant padding dominance.",
        }


def get_latest_actual_prediction(
    runtime_predictions: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    Return the most recent valid actual model prediction (excluding skipped and projected entries).
    """
    valid = [
        p
        for p in (runtime_predictions or [])
        if p.get("failure_probability") is not None
        and not p.get("is_skipped")
        and not p.get("is_projected")
    ]
    return valid[-1] if valid else None


def compute_checkpoint_projections(
    runtime_predictions: List[Dict[str, Any]],
) -> Dict[int, Dict[str, Any]]:
    """
    Generate continuous visual checkpoint representation for the presentation layer.

    Rules:
    - If an actual prediction exists for a checkpoint depth, return it with type='ACTUAL'.
    - For future checkpoints without fresh actual predictions:
      * First future checkpoint: previous actual prediction + 3.0 percentage points.
      * Subsequent future checkpoints: previous projected value + 2.0 percentage points.
      * All projected values are capped at 99.0%.
      * Type is 'PROJECTED'.
    - If no actual prediction has arrived yet for a checkpoint and no earlier actual prediction exists:
      * Type is 'NONE', values are None.

    Does NOT modify historical runtime predictions.
    Does NOT persist projected values as actual model outputs.
    """
    # 1. Map existing valid actual predictions by depth
    actual_by_depth: Dict[int, Dict[str, Any]] = {}
    for p in runtime_predictions or []:
        dp = p.get("depth_percentage")
        if (
            dp in CHECKPOINT_DEPTHS
            and p.get("failure_probability") is not None
            and not p.get("is_skipped")
            and not p.get("is_projected")
        ):
            actual_by_depth[dp] = p

    results: Dict[int, Dict[str, Any]] = {}
    last_actual_pct: Optional[float] = None
    last_val_pct: Optional[float] = None
    steps_from_actual: int = 0

    for d in CHECKPOINT_DEPTHS:
        if d in actual_by_depth:
            act = actual_by_depth[d]
            prob = act["failure_probability"]
            pct = act.get("failure_probability_pct")
            if pct is None and prob is not None:
                pct = round(prob * 100.0, 2)
            else:
                pct = round(float(pct), 2)

            last_actual_pct = pct
            last_val_pct = pct
            steps_from_actual = 0

            # Assign calibrated risk tier (<=40%: Low, 40-70%: Moderate, >=70%: High)
            if prob >= 0.70:
                tier = "HIGH RISK"
            elif prob > 0.40:
                tier = "MODERATE RISK"
            else:
                tier = "LOW RISK"

            results[d] = {
                "depth_percentage": d,
                "type": "ACTUAL",
                "is_projected": False,
                "failure_probability_pct": pct,
                "failure_probability": round(prob, 4),
                "model_name": act.get("model_name"),
                "risk_tier": tier,
                "evidence_strength": act.get("evidence_strength", "MODERATE"),
                "evidence_strength_label": act.get("evidence_strength_label", "Moderate Evidence"),
                "insufficient_evidence": act.get("insufficient_evidence", False),
            }
        elif last_actual_pct is not None:
            # Future checkpoint projection
            steps_from_actual += 1
            if steps_from_actual == 1:
                proj_pct = min(99.0, round(last_actual_pct + 3.0, 2))
            else:
                proj_pct = min(99.0, round(last_val_pct + 2.0, 2))

            last_val_pct = proj_pct
            proj_prob = round(proj_pct / 100.0, 4)

            # Determine risk tier for projected value according to calibrated thresholds
            if proj_prob >= 0.70:
                tier = "HIGH RISK"
            elif proj_prob > 0.40:
                tier = "MODERATE RISK"
            else:
                tier = "LOW RISK"

            results[d] = {
                "depth_percentage": d,
                "type": "PROJECTED",
                "is_projected": True,
                "failure_probability_pct": proj_pct,
                "failure_probability": proj_prob,
                "risk_tier": tier,
                "projection_basis_pct": last_actual_pct,
                "steps_from_actual": steps_from_actual,
            }
        else:
            results[d] = {
                "depth_percentage": d,
                "type": "NONE",
                "is_projected": False,
                "failure_probability_pct": None,
                "failure_probability": None,
            }

    return results

