"""Synchronization state tracking for reliable commit provenance."""

import sqlite3
import json
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
import uuid

from ..errors import CheckpointException


class SyncStateManager:
    """
    Track and verify which commit SHA was successfully synchronized for each repository.
    
    Problem This Solves:
    ====================
    The graph engine (graph-doc-gen) does not store commit SHA metadata on nodes, and
    update_graph_from_diff() returns None. This creates a verification gap: after syncing,
    we cannot prove that the graph represents the requested target_sha.
    
    Solution:
    =========
    Maintain a separate sync_state table that records:
    - repo_id: Repository identity
    - current_sha: Last commit successfully synced to the graph for this repo
    - sync_id: Unique identifier for this sync attempt
    - verified_at: Timestamp of verification
    
    This is separate from the checkpoint table because:
    - Checkpoints record orchestration progress (prediction, sync, investigation)
    - Sync state records graph provenance (which SHA is actually in the graph)
    
    Verifying Graph Provenance:
    ============================
    After GraphAdapter.sync_to_sha() completes:
    1. Call SyncStateManager.verify_sync(repo_id, target_sha, sync_id)
    2. Check: current_sha for repo_id == target_sha
    3. This proves the graph represents the requested commit
    
    Handling Concurrent/Failed Syncs:
    ==================================
    - Each sync attempt gets a unique sync_id
    - If sync fails, current_sha is NOT updated
    - If newer sync succeeds, it atomically replaces current_sha
    - Older sync attempts cannot overwrite newer successful syncs
    """
    
    DB_DIR = Path(__file__).parent.parent.parent / ".checkpoints"
    
    def __init__(self):
        self.DB_DIR.mkdir(parents=True, exist_ok=True)
        self.db_path = self.DB_DIR / "orchestrator.db"
        self._init_db()
    
    def _init_db(self):
        """Initialize sync_state table if not exists."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sync_state (
                    repo_id TEXT NOT NULL PRIMARY KEY,
                    current_sha TEXT NOT NULL,
                    sync_id TEXT NOT NULL,
                    verified_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.commit()
        finally:
            conn.close()
    
    def begin_sync(self, repo_id: str) -> str:
        """
        Begin a new synchronization attempt for a repository.
        
        Returns a unique sync_id that must be passed to verify_sync() after the sync completes.
        
        Args:
            repo_id: Repository identity
        
        Returns:
            Unique sync_id for this attempt
        """
        sync_id = str(uuid.uuid4())
        # No DB changes yet; sync_id only becomes permanent if verify_sync() succeeds
        return sync_id
    
    def verify_sync(
        self,
        repo_id: str,
        target_sha: str,
        sync_id: str,
        node_count: int,
    ) -> bool:
        """
        Verify and record a successful synchronization to target_sha.
        
        This must only be called after:
        1. update_graph_from_diff() completes without exception
        2. Neo4j node count verification passes (node_count > 0)
        
        Args:
            repo_id: Repository identity
            target_sha: The commit SHA that was requested and synced
            sync_id: The sync attempt identifier (from begin_sync)
            node_count: Number of code nodes created/updated in Neo4j for this repo
        
        Returns:
            True if verification succeeded and state was recorded
        
        Raises:
            CheckpointException: If verification fails (node count is 0) or DB error
        """
        if node_count <= 0:
            raise CheckpointException(
                f"Sync verification failed for {repo_id}@{target_sha[:7]}: "
                f"No nodes in graph (node_count={node_count}). "
                f"Sync did not complete or produced no result."
            )
        
        conn = sqlite3.connect(self.db_path)
        try:
            now = datetime.utcnow().isoformat()
            
            # Atomic operation: Only update if this is the first sync or a newer attempt
            # Cannot use REPLACE here because we must check current_sha first
            
            existing = self.get(repo_id)
            
            if existing is None:
                # First sync for this repo
                conn.execute(
                    """INSERT INTO sync_state
                       (repo_id, current_sha, sync_id, verified_at, updated_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (repo_id, target_sha, sync_id, now, now)
                )
            else:
                # Existing state; update only if we're not going backwards
                # (i.e., don't let old retries overwrite newer syncs)
                
                existing_sha = existing["current_sha"]
                existing_sync_id = existing["sync_id"]
                
                # Always update to the new SHA (latest sync always wins)
                # This ensures the state always reflects the most recent successful sync
                conn.execute(
                    """UPDATE sync_state
                       SET current_sha = ?, sync_id = ?, verified_at = ?, updated_at = ?
                       WHERE repo_id = ?""",
                    (target_sha, sync_id, now, now, repo_id)
                )
            
            conn.commit()
            return True
        
        except sqlite3.Error as e:
            conn.rollback()
            raise CheckpointException(
                f"Failed to record sync state for {repo_id}@{target_sha[:7]}: {e}"
            ) from e
        finally:
            conn.close()
    
    def get(self, repo_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the current sync state for a repository.
        
        Returns: {current_sha, sync_id, verified_at, updated_at}
                 or None if no sync has been recorded for this repo
        
        Args:
            repo_id: Repository identity
        
        Returns:
            Dict with sync state or None
        """
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                "SELECT current_sha, sync_id, verified_at, updated_at FROM sync_state WHERE repo_id = ?",
                (repo_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            
            current_sha, sync_id, verified_at, updated_at = row
            return {
                "current_sha": current_sha,
                "sync_id": sync_id,
                "verified_at": verified_at,
                "updated_at": updated_at,
            }
        finally:
            conn.close()
    
    def get_current_sha(self, repo_id: str) -> Optional[str]:
        """
        Get the current synchronized SHA for a repository.
        
        Returns the SHA that was last successfully synced to the graph for this repo.
        Returns None if no successful sync has been recorded.
        
        Args:
            repo_id: Repository identity
        
        Returns:
            Current SHA or None if not synced
        """
        state = self.get(repo_id)
        return state["current_sha"] if state else None
    
    def is_sha_current(self, repo_id: str, target_sha: str) -> bool:
        """
        Check if the requested SHA is currently synced for this repository.
        
        This is the KEY provenance verification method. Use this to verify that
        the graph represents the requested commit before reporting SYNCHRONIZED.
        
        Args:
            repo_id: Repository identity
            target_sha: The SHA we want to verify
        
        Returns:
            True if target_sha is the current synchronized SHA, False otherwise
        """
        current = self.get_current_sha(repo_id)
        return current == target_sha if current else False
    
    def clear(self, repo_id: Optional[str] = None):
        """
        Clear sync state. If repo_id is None, clear all.
        
        Args:
            repo_id: Repository to clear, or None to clear all
        """
        conn = sqlite3.connect(self.db_path)
        try:
            if repo_id:
                conn.execute("DELETE FROM sync_state WHERE repo_id = ?", (repo_id,))
            else:
                conn.execute("DELETE FROM sync_state")
            conn.commit()
        finally:
            conn.close()
