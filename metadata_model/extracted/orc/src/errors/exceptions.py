"""Custom exceptions for orchestrator."""


class OrchestratorException(Exception):
    """Base exception."""
    pass


class PredictionException(OrchestratorException):
    """Raised when metadata prediction fails."""
    pass


class GraphSyncException(OrchestratorException):
    """Raised when graph synchronization fails."""
    pass


class CheckpointException(OrchestratorException):
    """Raised when checkpoint operations fail."""
    pass


class RepositoryException(OrchestratorException):
    """Raised when repository operations fail."""
    pass


class InvalidCommitException(RepositoryException):
    """Raised when commit SHA is invalid or not found."""
    pass
