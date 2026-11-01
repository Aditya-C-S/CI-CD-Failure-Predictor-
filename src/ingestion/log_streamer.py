"""src/ingestion/log_streamer.py

Log streamer and snapshot segmenter.
Simulates real-time CI/CD log streaming and generates visibility snapshots
(25%, 50%, 75%, 100%) from raw log streams or log files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Generator, List, Union


class LogStreamer:
    """Streams and slices log streams into progressive visibility snapshots."""

    @staticmethod
    def split_into_lines(log_text: str) -> List[str]:
        """Split raw log text into non-empty lines while preserving formatting."""
        return [line for line in log_text.splitlines() if line.strip()]

    @classmethod
    def get_snapshot_at_depth(cls, log_text: str, depth_pct: int) -> str:
        """
        Extract log prefix corresponding to a specific execution percentage.

        Parameters
        ----------
        log_text : str
            Full raw log text.
        depth_pct : int
            Visibility depth (25, 50, 75, 100).

        Returns
        -------
        str
            Prefix snapshot containing exactly depth_pct% of log lines.
        """
        lines = cls.split_into_lines(log_text)
        if not lines:
            return ""

        depth_pct = min(max(depth_pct, 1), 100)
        num_lines = max(1, int(len(lines) * (depth_pct / 100.0)))
        return "\n".join(lines[:num_lines])

    @classmethod
    def generate_all_snapshots(cls, log_text: str) -> Dict[int, str]:
        """Generate all four standard visibility snapshots: 25%, 50%, 75%, 100%."""
        return {
            25: cls.get_snapshot_at_depth(log_text, 25),
            50: cls.get_snapshot_at_depth(log_text, 50),
            75: cls.get_snapshot_at_depth(log_text, 75),
            100: cls.get_snapshot_at_depth(log_text, 100),
        }

    @classmethod
    def stream_lines(cls, log_text: str, chunk_size: int = 5) -> Generator[List[str], None, None]:
        """Yield progressive batches of lines to simulate live WebSocket streaming."""
        lines = cls.split_into_lines(log_text)
        for i in range(0, len(lines), chunk_size):
            yield lines[i : i + chunk_size]
