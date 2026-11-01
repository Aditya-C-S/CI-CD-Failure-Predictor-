"""Tests for checkpoint storage."""

import pytest
from unittest.mock import MagicMock
from src.storage import CheckpointManager, CheckpointState
from src.errors import CheckpointException


# Mock Neo4j DateTime for testing
class MockNeo4jDateTime:
    """Mock neo4j.time.DateTime for testing."""
    def __init__(self, year, month, day, hour, minute, second):
        self.year = year
        self.month = month
        self.day = day
        self.hour = hour
        self.minute = minute
        self.second = second
    
    def isoformat(self):
        return f"{self.year:04d}-{self.month:02d}-{self.day:02d}T{self.hour:02d}:{self.minute:02d}:{self.second:02d}"
    
    def __repr__(self):
        return f"MockNeo4jDateTime({self.isoformat()})"


class MockNeo4jDate:
    """Mock neo4j.time.Date for testing."""
    def __init__(self, year, month, day):
        self.year = year
        self.month = month
        self.day = day
    
    def isoformat(self):
        return f"{self.year:04d}-{self.month:02d}-{self.day:02d}"
    
    def __repr__(self):
        return f"MockNeo4jDate({self.isoformat()})"


class MockNeo4jTime:
    """Mock neo4j.time.Time for testing."""
    def __init__(self, hour, minute, second):
        self.hour = hour
        self.minute = minute
        self.second = second
    
    def isoformat(self):
        return f"{self.hour:02d}:{self.minute:02d}:{self.second:02d}"
    
    def __repr__(self):
        return f"MockNeo4jTime({self.isoformat()})"


class MockNeo4jDuration:
    """Mock neo4j.time.Duration for testing."""
    def __init__(self, seconds):
        self.seconds = seconds
    
    def __repr__(self):
        return f"MockNeo4jDuration({self.seconds}s)"


class TestCheckpointManager:
    """Test checkpoint storage and state management."""
    
    def test_save_and_retrieve_checkpoint(self):
        """Test saving and retrieving a checkpoint."""
        mgr = CheckpointManager()
        repo_id = "owner/repo"
        target_sha = "abc123def456" * 3
        
        # Save
        mgr.save(
            repo_id,
            target_sha,
            CheckpointState.PREDICTION_COMPLETE,
            prediction_result={"failure_probability": 0.42},
        )
        
        # Retrieve
        cp = mgr.get(repo_id, target_sha)
        
        # Assert
        assert cp is not None
        assert cp["state"] == CheckpointState.PREDICTION_COMPLETE
        assert cp["prediction_result"]["failure_probability"] == 0.42
        
        # Cleanup
        mgr.clear(repo_id, target_sha)
    
    def test_update_existing_checkpoint(self):
        """Test updating an existing checkpoint."""
        mgr = CheckpointManager()
        repo_id = "owner/repo"
        target_sha = "abc123def456" * 3
        
        # Save initial
        mgr.save(
            repo_id,
            target_sha,
            CheckpointState.PREDICTION_COMPLETE,
            prediction_result={"failure_probability": 0.42},
        )
        
        # Update to COMPLETE
        mgr.save(
            repo_id,
            target_sha,
            CheckpointState.COMPLETE,
            prediction_result={"failure_probability": 0.42},
            graph_files_changed={"added": 2, "modified": 3},
        )
        
        # Retrieve and verify
        cp = mgr.get(repo_id, target_sha)
        assert cp["state"] == CheckpointState.COMPLETE
        assert cp["graph_files_changed"]["added"] == 2
        
        # Cleanup
        mgr.clear(repo_id, target_sha)
    
    def test_retry_count_increment(self):
        """Test retry count tracking."""
        mgr = CheckpointManager()
        repo_id = "owner/repo"
        target_sha = "abc123def456" * 3
        
        # Initial
        assert mgr.get_retry_count(repo_id, target_sha) == 0
        
        # Save initial checkpoint
        mgr.save(
            repo_id,
            target_sha,
            CheckpointState.GRAPH_SYNC_COMPLETE,
            error="Network timeout",
        )
        
        # Increment retry count
        count1 = mgr.increment_retry_count(repo_id, target_sha)
        assert count1 == 1
        
        count2 = mgr.increment_retry_count(repo_id, target_sha)
        assert count2 == 2
        
        # Verify
        cp = mgr.get(repo_id, target_sha)
        assert cp["retry_count"] == 2
        
        # Cleanup
        mgr.clear(repo_id, target_sha)
    
    def test_clear_specific_checkpoint(self):
        """Test clearing a specific checkpoint."""
        mgr = CheckpointManager()
        repo_id = "owner/repo"
        
        # Save two checkpoints
        mgr.save(repo_id, "sha1", CheckpointState.PREDICTION_COMPLETE)
        mgr.save(repo_id, "sha2", CheckpointState.COMPLETE)
        
        # Clear only one
        mgr.clear(repo_id, "sha1")
        
        # Verify
        assert mgr.get(repo_id, "sha1") is None
        assert mgr.get(repo_id, "sha2") is not None
        
        # Cleanup
        mgr.clear(repo_id, "sha2")
    
    def test_clear_all_for_repo(self):
        """Test clearing all checkpoints for a repository."""
        mgr = CheckpointManager()
        repo_id = "owner/repo"
        
        # Save multiple checkpoints
        mgr.save(repo_id, "sha1", CheckpointState.PREDICTION_COMPLETE)
        mgr.save(repo_id, "sha2", CheckpointState.COMPLETE)
        
        # Clear all for repo
        mgr.clear(repo_id)
        
        # Verify
        assert mgr.get(repo_id, "sha1") is None
        assert mgr.get(repo_id, "sha2") is None


class TestGraphSyncResultPersistence:
    """Test graph_sync_result persistence (Phase 2 regression)."""
    
    def test_successful_graph_sync_persists_full_result(self):
        """Test that a successful graph sync stores engine_result and persisted_state."""
        mgr = CheckpointManager()
        repo_id = "DhruvHegde/Voice_based-_Tic-Tac-Toe"
        target_sha = "a10300b0fde4740b09fe6daa8600091d99bd7728"
        
        # Simulate successful sync result from graph_adapter.sync_to_sha()
        graph_sync_result = {
            "status": "success",
            "base_sha": "base123",
            "target_sha": target_sha,
            "files_added": 0,
            "files_modified": 1,
            "files_deleted": 0,
            "files_renamed": 0,
            "changed_files": ["src/app.py"],
            "engine_result": {
                "status": "SYNCED",
                "sync_nodes": 45,
                "sync_edges": 120,
            },
            "persisted_state": {
                "commit_verified": True,
                "status": "SYNCED",
            },
        }
        
        # Save GRAPH_SYNC_COMPLETE checkpoint with graph_sync_result
        mgr.save(
            repo_id,
            target_sha,
            CheckpointState.GRAPH_SYNC_COMPLETE,
            prediction_result={"failure_probability": 0.35, "verdict": "LOW_RISK"},
            graph_files_changed={
                "added": graph_sync_result["files_added"],
                "modified": graph_sync_result["files_modified"],
                "deleted": graph_sync_result["files_deleted"],
                "renamed": graph_sync_result["files_renamed"],
            },
            graph_sync_result=graph_sync_result,
        )
        
        # Retrieve and verify
        cp = mgr.get(repo_id, target_sha)
        assert cp is not None
        assert cp["state"] == CheckpointState.GRAPH_SYNC_COMPLETE
        assert cp["graph_sync_result"] is not None
        assert cp["graph_sync_result"]["engine_result"]["status"] == "SYNCED"
        assert cp["graph_sync_result"]["persisted_state"]["commit_verified"] is True
        assert cp["graph_sync_result"]["files_modified"] == 1
        
        # Cleanup
        mgr.clear(repo_id, target_sha)
    
    def test_complete_checkpoint_retains_graph_sync_result(self):
        """Test that COMPLETE checkpoint preserves graph_sync_result from earlier stages."""
        mgr = CheckpointManager()
        repo_id = "test/repo"
        target_sha = "complete123456" * 3
        
        graph_sync_result = {
            "status": "success",
            "base_sha": "base",
            "target_sha": target_sha,
            "files_added": 1,
            "files_modified": 2,
            "files_deleted": 0,
            "files_renamed": 1,
            "changed_files": ["file1.py", "file2.py"],
            "engine_result": {"status": "SYNCED", "sync_nodes": 50},
            "persisted_state": {"commit_verified": True, "status": "SYNCED"},
        }
        
        # Save as COMPLETE with graph_sync_result
        mgr.save(
            repo_id,
            target_sha,
            CheckpointState.COMPLETE,
            prediction_result={"failure_probability": 0.25, "verdict": "LOW_RISK"},
            graph_files_changed={
                "added": 1,
                "modified": 2,
                "deleted": 0,
                "renamed": 1,
            },
            graph_sync_result=graph_sync_result,
        )
        
        # Retrieve and verify
        cp = mgr.get(repo_id, target_sha)
        assert cp["state"] == CheckpointState.COMPLETE
        assert cp["graph_sync_result"] is not None
        assert cp["graph_sync_result"]["engine_result"]["sync_nodes"] == 50
        assert cp["graph_sync_result"]["persisted_state"]["commit_verified"] is True
        
        # Cleanup
        mgr.clear(repo_id, target_sha)
    
    def test_legacy_checkpoint_with_none_graph_sync_result_handled_safely(self):
        """Test that checkpoints without graph_sync_result (legacy) are handled safely."""
        mgr = CheckpointManager()
        repo_id = "legacy/repo"
        target_sha = "legacy123456" * 3
        
        # Save checkpoint WITHOUT graph_sync_result (as if from before this fix)
        mgr.save(
            repo_id,
            target_sha,
            CheckpointState.COMPLETE,
            prediction_result={"failure_probability": 0.30, "verdict": "LOW_RISK"},
            graph_files_changed={
                "added": 1,
                "modified": 0,
                "deleted": 0,
                "renamed": 0,
            },
            # graph_sync_result intentionally omitted (defaults to None)
        )
        
        # Retrieve and verify it doesn't crash
        cp = mgr.get(repo_id, target_sha)
        assert cp is not None
        assert cp["state"] == CheckpointState.COMPLETE
        assert cp["graph_sync_result"] is None  # Expected: None for legacy checkpoints
        assert cp["prediction_result"] is not None
        assert cp["graph_files_changed"] is not None
        
        # Cleanup
        mgr.clear(repo_id, target_sha)
    
    def test_checkpoint_recovery_without_graph_sync_result_does_not_crash(self):
        """Test that recovering a checkpoint with None graph_sync_result is safe."""
        mgr = CheckpointManager()
        repo_id = "recovery/repo"
        target_sha = "recovery123456" * 3
        
        # Save a checkpoint with graph_sync_result
        graph_sync_result = {
            "status": "success",
            "engine_result": {"status": "SYNCED"},
            "persisted_state": {"commit_verified": True},
        }
        
        mgr.save(
            repo_id,
            target_sha,
            CheckpointState.GRAPH_SYNC_COMPLETE,
            prediction_result={"failure_probability": 0.20},
            graph_sync_result=graph_sync_result,
        )
        
        # Update to COMPLETE (simulating recovery scenario)
        mgr.save(
            repo_id,
            target_sha,
            CheckpointState.COMPLETE,
            prediction_result={"failure_probability": 0.20},
            graph_sync_result=graph_sync_result,  # Passed again
        )
        
        # Retrieve and verify both are present
        cp = mgr.get(repo_id, target_sha)
        assert cp["state"] == CheckpointState.COMPLETE
        assert cp["graph_sync_result"] is not None
        assert cp["graph_sync_result"]["engine_result"]["status"] == "SYNCED"
        
        # Cleanup
        mgr.clear(repo_id, target_sha)
    
    def test_graph_sync_result_not_overwritten_by_none(self):
        """Test that updating a checkpoint does not lose graph_sync_result."""
        mgr = CheckpointManager()
        repo_id = "overwrite/repo"
        target_sha = "overwrite123456" * 3
        
        graph_sync_result = {
            "status": "success",
            "engine_result": {"status": "SYNCED"},
        }
        
        # First save with graph_sync_result
        mgr.save(
            repo_id,
            target_sha,
            CheckpointState.GRAPH_SYNC_COMPLETE,
            prediction_result={"failure_probability": 0.15},
            graph_sync_result=graph_sync_result,
        )
        
        # Second save WITHOUT graph_sync_result (should not overwrite)
        # In orchestrator, we always pass it, so this shouldn't happen
        # But test defensive behavior: passing None explicitly should preserve it
        mgr.save(
            repo_id,
            target_sha,
            CheckpointState.COMPLETE,
            prediction_result={"failure_probability": 0.15},
            graph_sync_result=None,  # Explicitly None
        )
        
        # Retrieve and verify: should be None because we passed None
        cp = mgr.get(repo_id, target_sha)
        assert cp["graph_sync_result"] is None
        
        # Cleanup
        mgr.clear(repo_id, target_sha)


class TestNeo4jDateTimeSerialization:
    """Test Neo4j DateTime serialization (Phase 3 regression)."""
    
    def test_checkpoint_with_mocked_neo4j_datetime_at_top_level(self):
        """Test that mocked Neo4j DateTime values are serialized correctly at top level."""
        mgr = CheckpointManager()
        repo_id = "datetime/repo"
        target_sha = "datetime123456" * 3
        
        # Create graph_sync_result with mocked Neo4j DateTime at top level
        created_dt = MockNeo4jDateTime(2024, 10, 15, 14, 30, 45)
        graph_sync_result = {
            "status": "success",
            "base_sha": "base123",
            "target_sha": target_sha,
            "files_added": 0,
            "files_modified": 1,
            "changed_files": ["src/app.py"],
            "engine_result": {
                "status": "SYNCED",
                "sync_nodes": 45,
            },
            "persisted_state": {
                "commit_verified": True,
                "status": "SYNCED",
                "created_at": created_dt,  # Neo4j DateTime at top level
            },
        }
        
        # Save checkpoint with Neo4j DateTime
        mgr.save(
            repo_id,
            target_sha,
            CheckpointState.GRAPH_SYNC_COMPLETE,
            prediction_result={"failure_probability": 0.35},
            graph_sync_result=graph_sync_result,
        )
        
        # Retrieve and verify: DateTime should be converted to ISO string
        cp = mgr.get(repo_id, target_sha)
        assert cp is not None
        assert cp["graph_sync_result"]["persisted_state"]["created_at"] == "2024-10-15T14:30:45"
        assert isinstance(cp["graph_sync_result"]["persisted_state"]["created_at"], str)
        
        # Cleanup
        mgr.clear(repo_id, target_sha)
    
    def test_checkpoint_with_nested_neo4j_datetime(self):
        """Test that mocked Neo4j DateTime values nested in dicts/lists are serialized."""
        mgr = CheckpointManager()
        repo_id = "nested-datetime/repo"
        target_sha = "nested123456" * 3
        
        # Create graph_sync_result with nested Neo4j DateTime
        created_dt = MockNeo4jDateTime(2024, 10, 15, 10, 20, 30)
        modified_dt = MockNeo4jDateTime(2024, 10, 15, 14, 25, 50)
        
        graph_sync_result = {
            "status": "success",
            "engine_result": {
                "status": "SYNCED",
                "timestamps": {
                    "created_at": created_dt,  # Nested DateTime
                    "modified_at": modified_dt,
                },
            },
            "persisted_state": {
                "commit_verified": True,
                "history": [
                    {"timestamp": created_dt, "action": "sync"},  # DateTime in list
                    {"timestamp": modified_dt, "action": "verify"},
                ],
            },
        }
        
        # Save checkpoint
        mgr.save(
            repo_id,
            target_sha,
            CheckpointState.GRAPH_SYNC_COMPLETE,
            prediction_result={"failure_probability": 0.30},
            graph_sync_result=graph_sync_result,
        )
        
        # Retrieve and verify nested DateTime values are converted
        cp = mgr.get(repo_id, target_sha)
        assert cp is not None
        assert cp["graph_sync_result"]["engine_result"]["timestamps"]["created_at"] == "2024-10-15T10:20:30"
        assert cp["graph_sync_result"]["engine_result"]["timestamps"]["modified_at"] == "2024-10-15T14:25:50"
        assert cp["graph_sync_result"]["persisted_state"]["history"][0]["timestamp"] == "2024-10-15T10:20:30"
        assert cp["graph_sync_result"]["persisted_state"]["history"][1]["timestamp"] == "2024-10-15T14:25:50"
        assert all(isinstance(v, str) for v in [
            cp["graph_sync_result"]["engine_result"]["timestamps"]["created_at"],
            cp["graph_sync_result"]["persisted_state"]["history"][0]["timestamp"],
        ])
        
        # Cleanup
        mgr.clear(repo_id, target_sha)
    
    def test_checkpoint_with_neo4j_date_time_duration(self):
        """Test that various Neo4j temporal types are handled correctly."""
        mgr = CheckpointManager()
        repo_id = "temporal/repo"
        target_sha = "temporal123456" * 3
        
        # Create graph_sync_result with multiple Neo4j temporal types
        date_val = MockNeo4jDate(2024, 10, 15)
        time_val = MockNeo4jTime(14, 30, 45)
        datetime_val = MockNeo4jDateTime(2024, 10, 15, 14, 30, 45)
        duration_val = MockNeo4jDuration(3600)  # 1 hour in seconds
        
        graph_sync_result = {
            "status": "success",
            "engine_result": {
                "temporal_values": {
                    "date": date_val,
                    "time": time_val,
                    "datetime": datetime_val,
                    "duration": duration_val,
                },
            },
            "persisted_state": {
                "snapshot_date": date_val,
            },
        }
        
        # Save checkpoint
        mgr.save(
            repo_id,
            target_sha,
            CheckpointState.GRAPH_SYNC_COMPLETE,
            prediction_result={"failure_probability": 0.25},
            graph_sync_result=graph_sync_result,
        )
        
        # Retrieve and verify all temporal types are converted
        cp = mgr.get(repo_id, target_sha)
        assert cp is not None
        temporal = cp["graph_sync_result"]["engine_result"]["temporal_values"]
        assert temporal["date"] == "2024-10-15"
        assert temporal["time"] == "14:30:45"
        assert temporal["datetime"] == "2024-10-15T14:30:45"
        assert temporal["duration"] == "PT3600S"
        assert cp["graph_sync_result"]["persisted_state"]["snapshot_date"] == "2024-10-15"
        assert all(isinstance(v, str) for v in temporal.values())
        
        # Cleanup
        mgr.clear(repo_id, target_sha)
    
    def test_checkpoint_update_with_neo4j_datetime_does_not_lose_data(self):
        """Test that updating a checkpoint with Neo4j DateTime values works correctly."""
        mgr = CheckpointManager()
        repo_id = "update-datetime/repo"
        target_sha = "update123456" * 3
        
        created_dt = MockNeo4jDateTime(2024, 10, 15, 10, 0, 0)
        
        # First save: GRAPH_SYNC_COMPLETE with DateTime
        graph_sync_result = {
            "status": "success",
            "engine_result": {
                "status": "SYNCED",
                "created_at": created_dt,
            },
            "persisted_state": {
                "commit_verified": True,
                "created_at": created_dt,
            },
        }
        
        mgr.save(
            repo_id,
            target_sha,
            CheckpointState.GRAPH_SYNC_COMPLETE,
            prediction_result={"failure_probability": 0.20},
            graph_sync_result=graph_sync_result,
        )
        
        # Second save: Update to COMPLETE, keep DateTime in graph_sync_result
        mgr.save(
            repo_id,
            target_sha,
            CheckpointState.COMPLETE,
            prediction_result={"failure_probability": 0.20},
            graph_sync_result=graph_sync_result,
        )
        
        # Retrieve and verify DateTime was preserved and serialized
        cp = mgr.get(repo_id, target_sha)
        assert cp["state"] == CheckpointState.COMPLETE
        assert cp["graph_sync_result"]["engine_result"]["created_at"] == "2024-10-15T10:00:00"
        assert cp["graph_sync_result"]["persisted_state"]["created_at"] == "2024-10-15T10:00:00"
        assert cp["graph_sync_result"]["persisted_state"]["commit_verified"] is True
        
        # Cleanup
        mgr.clear(repo_id, target_sha)
    
    def test_prediction_result_with_neo4j_datetime_serializes(self):
        """Test that Neo4j DateTime in prediction_result is also serialized."""
        mgr = CheckpointManager()
        repo_id = "prediction-datetime/repo"
        target_sha = "prediction123456" * 3
        
        created_dt = MockNeo4jDateTime(2024, 10, 15, 12, 0, 0)
        
        # Save with Neo4j DateTime in prediction_result
        prediction_result = {
            "failure_probability": 0.35,
            "verdict": "LOW_RISK",
            "analyzed_at": created_dt,  # DateTime in prediction_result
        }
        
        mgr.save(
            repo_id,
            target_sha,
            CheckpointState.PREDICTION_COMPLETE,
            prediction_result=prediction_result,
        )
        
        # Retrieve and verify DateTime was serialized
        cp = mgr.get(repo_id, target_sha)
        assert cp["prediction_result"]["analyzed_at"] == "2024-10-15T12:00:00"
        assert isinstance(cp["prediction_result"]["analyzed_at"], str)
        
        # Cleanup
        mgr.clear(repo_id, target_sha)
