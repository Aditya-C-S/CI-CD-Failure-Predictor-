"""src/parser/parser_v2.py

Unified facade and entry point for Parser V2.
Preserves the underlying log_parser implementation while providing a clean,
consistent interface for ingestion, API, and testing.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# Ensure src directory is on sys.path
_SRC_DIR = Path(__file__).resolve().parent.parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

try:
    from src.parser.log_parser import (
        LogRecord,
        parse_log_text,
        parse_log_file,
        parse_batch,
        parse_all_categories,
    )
except ImportError:
    from parser.log_parser import (
        LogRecord,
        parse_log_text,
        parse_log_file,
        parse_batch,
        parse_all_categories,
    )

__all__ = [
    "LogRecord",
    "parse_log_text",
    "parse_log_file",
    "parse_batch",
    "parse_all_categories",
]
