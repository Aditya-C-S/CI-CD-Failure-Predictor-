"""Result models for orchestrator."""

from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict
from enum import Enum
from datetime import datetime


class GraphSyncStatus(str, Enum):
    """Graph synchronization status."""
    SYNCHRONIZED = "SYNCHRONIZED"
    SYNC_FAILED = "SYNC_FAILED"
    SKIPPED = "SKIPPED"


@dataclass
class SuspiciousFile:
    """A file candidate for investigation due to commit risk."""
    file_path: str
    centrality_score: float  # [0.0, 1.0]
    reasons: List[str] = field(default_factory=list)  # Why this file is suspicious


@dataclass
class CommitPredictionResult:
    """Unified result from prediction + graph sync + investigation."""
    
    # Identity
    repository_identity: str  # "owner/repo"
    target_sha: str  # Full commit SHA
    
    # Prediction results
    failure_probability: float  # [0.0, 1.0]
    verdict: str  # "FAST-TRACK", "STANDARD GATE", "ALERT", "PRE-MERGE BLOCK"
    shap_drivers: Dict  # {"positive": [...], "negative": [...]}
    
    # Graph synchronization status
    graph_status: GraphSyncStatus
    graph_files_changed: Optional[Dict] = None  # {"added": int, "modified": int, "deleted": int}
    
    # Suspicious files (populated only if risk >= threshold)
    suspicious_files: Optional[List[SuspiciousFile]] = None
    
    # Metadata
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    processing_time_ms: float = 0.0
    
    # Prediction features (for debugging)
    features: Optional[Dict] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary, handling nested dataclasses."""
        result = asdict(self)
        # Convert SuspiciousFile objects to dicts
        if self.suspicious_files:
            result["suspicious_files"] = [asdict(sf) for sf in self.suspicious_files]
        # Convert enum to string
        result["graph_status"] = self.graph_status.value
        return result
