"""src/prediction/model_interface.py

Defines the model-independent prediction interface and data contracts.
Ensures that any failure prediction model (LR, SVM, ModernBERT, BiLSTM)
can be swapped seamlessly without modifying the parser, RCA, API, or frontend.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Union


@dataclass
class PredictionResult:
    """Unified container for failure prediction outputs across all models."""
    failure_probability: float
    predicted_label: str  # 'failure' or 'success'
    model_name: str
    visibility_stage: str  # e.g., '25%', '50%', '75%', '100%'
    decision_score: Optional[float] = None
    confidence: Optional[float] = None
    predicted_error_class: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to serializable dictionary."""
        return {
            "failure_probability": round(self.failure_probability, 4),
            "predicted_label": self.predicted_label,
            "model_name": self.model_name,
            "visibility_stage": self.visibility_stage,
            "decision_score": round(self.decision_score, 4) if self.decision_score is not None else None,
            "confidence": round(self.confidence, 4) if self.confidence is not None else None,
            "predicted_error_class": self.predicted_error_class,
            "metadata": self.metadata,
        }


class BasePredictor(ABC):
    """Abstract base predictor defining the pluggable model interface."""

    def __init__(self, model_name: str, visibility: Union[int, str] = 25):
        self.model_name = model_name
        self.visibility = self._normalize_visibility(visibility)

    @staticmethod
    def _normalize_visibility(visibility: Union[int, str]) -> int:
        """Normalize visibility representations (e.g. '25%', 'depth025', 25) to integer."""
        if isinstance(visibility, int):
            return visibility
        clean = str(visibility).replace("%", "").replace("depth", "").strip()
        return int(clean)

    @abstractmethod
    def predict_failure(self, log_text: str, visibility: Optional[Union[int, str]] = None) -> PredictionResult:
        """
        Estimate failure risk for a given log snapshot text.

        Parameters
        ----------
        log_text : str
            Raw or partial CI/CD log content.
        visibility : int or str, optional
            Log visibility depth (25, 50, 75, 100). If omitted, uses predictor default.

        Returns
        -------
        PredictionResult
            Standardized failure probability, predicted label, and metadata.
        """
        pass
