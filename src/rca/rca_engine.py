"""src/rca/rca_engine.py

Unified facade and entry point for the Root Cause Analysis (RCA) Engine.
Preserves the underlying rule engine and analyzer dispatch chain while providing
a clean interface for the pipeline and API.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional, Union

# Ensure src directory is on sys.path
_SRC_DIR = Path(__file__).resolve().parent.parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

try:
    from src.rca.engine import RCAEngine, get_default_engine, analyze_record
    from src.rca.schema import (
        RCAReport,
        CAUSAL_CODE_DEFECT,
        CAUSAL_DEPENDENCY,
        CAUSAL_TEST,
        CAUSAL_TEST_EXECUTION,
        CAUSAL_TIMEOUT,
        CAUSAL_UNKNOWN,
    )
    from src.rca.advanced_rca import (
        AdvancedRCAEngine,
        AdvancedRCAReport,
        FailureCategory,
        EvidenceItem,
        RootCauseCandidate,
    )
except ImportError:
    from rca.engine import RCAEngine, get_default_engine, analyze_record
    from rca.schema import (
        RCAReport,
        CAUSAL_CODE_DEFECT,
        CAUSAL_DEPENDENCY,
        CAUSAL_TEST,
        CAUSAL_TEST_EXECUTION,
        CAUSAL_TIMEOUT,
        CAUSAL_UNKNOWN,
    )
    from rca.advanced_rca import (
        AdvancedRCAEngine,
        AdvancedRCAReport,
        FailureCategory,
        EvidenceItem,
        RootCauseCandidate,
    )

__all__ = [
    "RCAEngine",
    "get_default_engine",
    "analyze_record",
    "RCAReport",
    "CAUSAL_CODE_DEFECT",
    "CAUSAL_DEPENDENCY",
    "CAUSAL_TEST",
    "CAUSAL_TEST_EXECUTION",
    "CAUSAL_TIMEOUT",
    "CAUSAL_UNKNOWN",
    "AdvancedRCAEngine",
    "AdvancedRCAReport",
    "FailureCategory",
    "EvidenceItem",
    "RootCauseCandidate",
]
