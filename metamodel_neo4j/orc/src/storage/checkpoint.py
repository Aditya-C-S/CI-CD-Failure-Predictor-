"""SQLite-based checkpoint storage for commit synchronization."""

import sqlite3
import json
import os
from pathlib import Path
from typing import Optional, Dict, Any
from enum import Enum
from datetime import datetime

from ..errors import CheckpointException


def _make_json_serializable(obj: Any) -> Any:
    """Convert non-JSON-serializable objects to JSON-compatible types.
    
    Handles Neo4j temporal types (DateTime, Date, Time, Duration) by converting
    them to ISO-8601 strings. Recursively processes dicts and lists.
    
    Args:
        obj: Object to convert (can be dict, list, or Neo4j temporal type)
        
    Returns:
        JSON-serializable version of the object
    """
    type_name = type(obj).__name__
    
    # Handle Neo4j DateTime type
    if type_name == "DateTime" or "DateTime" in type_name:
        # Neo4j DateTime has .isoformat() method
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        return str(obj)
    
    # Handle Neo4j Date type
    if type_name == "Date" or "Date" in type_name:
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        return str(obj)
    
    # Handle Neo4j Time type
    if type_name == "Time" or "Time" in type_name:
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        return str(obj)
    
    # Handle Neo4j Duration type
    if type_name == "Duration" or "Duration" in type_name:
        # Duration doesn't have isoformat; represent as ISO 8601 duration string
        # Format: P[n]Y[n]M[n]DT[n]H[n]M[n]S or total seconds
        if hasattr(obj, "seconds"):
            return f"PT{obj.seconds}S"
        return str(obj)
    
    # Recursively handle dicts
    if isinstance(obj, dict):
        return {key: _make_json_serializable(value) for key, value in obj.items()}
    
    # Recursively handle lists
    if isinstance(obj, list):
        return [_make_json_serializable(item) for item in obj]
    
    # Return primitives unchanged
    return obj


class CheckpointState(str, Enum):
    """Checkpoint state machine."""
    PREDICTION_COMPLETE = "PREDICTION_COMPLETE"
    GRAPH_SYNC_COMPLETE = "GRAPH_SYNC_COMPLETE"
    INVESTIGATION_IN_PROGRESS = "INVESTIGATION_IN_PROGRESS"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class CheckpointManager:
    """SQLite-backed checkpoint storage."""
    
    DB_DIR = Path(__file__).parent.parent.parent / ".checkpoints"
    
    def __init__(self):
        self.DB_DIR.mkdir(parents=True, exist_ok=True)
        self.db_path = self.DB_DIR / "orchestrator.db"
        self._init_db()
    
    def _init_db(self):
        """Initialize database schema."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS checkpoints (
                    repo_id TEXT NOT NULL,
                    target_sha TEXT NOT NULL,
                    state TEXT NOT NULL,
                    prediction_result TEXT,
                    graph_files_changed TEXT,
                    graph_sync_result TEXT,
                    error TEXT,
                    retry_count INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    PRIMARY KEY (repo_id, target_sha)
                )
            """)
            conn.commit()
        finally:
            conn.close()
    
    def get(self, repo_id: str, target_sha: str) -> Optional[Dict[str, Any]]:
        """Retrieve checkpoint by repo_id and target_sha."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                "SELECT state, prediction_result, graph_files_changed, graph_sync_result, error, retry_count, created_at, completed_at FROM checkpoints WHERE repo_id = ? AND target_sha = ?",
                (repo_id, target_sha)
            )
            row = cursor.fetchone()
            if not row:
                return None
            
            state, pred_json, graph_json, sync_json, error, retry_count, created_at, completed_at = row
            return {
                "state": CheckpointState(state),
                "prediction_result": json.loads(pred_json) if pred_json else None,
                "graph_files_changed": json.loads(graph_json) if graph_json else None,
                "graph_sync_result": json.loads(sync_json) if sync_json else None,
                "error": error,
                "retry_count": retry_count,
                "created_at": created_at,
                "completed_at": completed_at,
            }
        finally:
            conn.close()
    
    def save(
        self,
        repo_id: str,
        target_sha: str,
        state: CheckpointState,
        prediction_result: Optional[Dict] = None,
        graph_files_changed: Optional[Dict] = None,
        graph_sync_result: Optional[Dict] = None,
        error: Optional[str] = None,
        retry_count: int = 0,
    ):
        """Save or update checkpoint."""
        conn = sqlite3.connect(self.db_path)
        try:
            now = datetime.utcnow().isoformat()
            existing = self.get(repo_id, target_sha)
            
            if existing:
                # Update existing checkpoint
                conn.execute(
                    """UPDATE checkpoints 
                       SET state = ?, prediction_result = ?, graph_files_changed = ?, 
                           graph_sync_result = ?, error = ?, retry_count = ?, completed_at = ?
                       WHERE repo_id = ? AND target_sha = ?""",
                    (
                        state.value,
                        json.dumps(_make_json_serializable(prediction_result)) if prediction_result else None,
                        json.dumps(_make_json_serializable(graph_files_changed)) if graph_files_changed else None,
                        json.dumps(_make_json_serializable(graph_sync_result)) if graph_sync_result else None,
                        error,
                        retry_count,
                        now if state in [CheckpointState.COMPLETE, CheckpointState.FAILED] else existing["completed_at"],
                        repo_id,
                        target_sha,
                    )
                )
            else:
                # Insert new checkpoint
                conn.execute(
                    """INSERT INTO checkpoints
                       (repo_id, target_sha, state, prediction_result, graph_files_changed, 
                        graph_sync_result, error, retry_count, created_at, completed_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        repo_id,
                        target_sha,
                        state.value,
                        json.dumps(_make_json_serializable(prediction_result)) if prediction_result else None,
                        json.dumps(_make_json_serializable(graph_files_changed)) if graph_files_changed else None,
                        json.dumps(_make_json_serializable(graph_sync_result)) if graph_sync_result else None,
                        error,
                        retry_count,
                        now,
                        now if state in [CheckpointState.COMPLETE, CheckpointState.FAILED] else None,
                    )
                )
            conn.commit()
        except sqlite3.Error as e:
            raise CheckpointException(f"Failed to save checkpoint: {e}") from e
        finally:
            conn.close()
    
    def get_retry_count(self, repo_id: str, target_sha: str) -> int:
        """Get current retry count for a checkpoint."""
        checkpoint = self.get(repo_id, target_sha)
        return checkpoint["retry_count"] if checkpoint else 0
    
    def increment_retry_count(self, repo_id: str, target_sha: str) -> int:
        """Increment and return new retry count."""
        checkpoint = self.get(repo_id, target_sha)
        if not checkpoint:
            return 0
        
        new_count = checkpoint["retry_count"] + 1
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "UPDATE checkpoints SET retry_count = ? WHERE repo_id = ? AND target_sha = ?",
                (new_count, repo_id, target_sha)
            )
            conn.commit()
        finally:
            conn.close()
        
        return new_count
    
    def clear(self, repo_id: str, target_sha: Optional[str] = None):
        """Clear checkpoint(s). If target_sha is None, clear all for repo_id."""
        conn = sqlite3.connect(self.db_path)
        try:
            if target_sha:
                conn.execute("DELETE FROM checkpoints WHERE repo_id = ? AND target_sha = ?", (repo_id, target_sha))
            else:
                conn.execute("DELETE FROM checkpoints WHERE repo_id = ?", (repo_id,))
            conn.commit()
        finally:
            conn.close()
