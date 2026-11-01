import os
from unittest.mock import MagicMock, patch
import pytest

from database.neo4j_client import Neo4jClient
from tests.test_live_neo4j_integration import get_live_test_database_name


class TestNeo4jClientDatabaseSelection:
    @patch("database.neo4j_client.GraphDatabase.driver")
    def test_default_database_selection_when_env_absent(self, mock_driver_cls, monkeypatch):
        """Preserve previous behavior: absent NEO4J_DATABASE results in database=None and driver.session()."""
        monkeypatch.delenv("NEO4J_DATABASE", raising=False)
        mock_driver_instance = MagicMock()
        mock_driver_cls.return_value = mock_driver_instance

        client = Neo4jClient()
        assert client.database is None
        assert client.is_protected_database() is True

        _ = client.session()
        # Verify driver.session() was called with NO database argument (default database)
        mock_driver_instance.session.assert_called_once_with()

    @patch("database.neo4j_client.GraphDatabase.driver")
    def test_explicit_argument_database_selection(self, mock_driver_cls, monkeypatch):
        """Explicit database parameter is passed to session()."""
        monkeypatch.delenv("NEO4J_DATABASE", raising=False)
        mock_driver_instance = MagicMock()
        mock_driver_cls.return_value = mock_driver_instance

        client = Neo4jClient(database="custom_graph_db")
        assert client.database == "custom_graph_db"
        assert client.is_protected_database() is False

        _ = client.session()
        mock_driver_instance.session.assert_called_once_with(database="custom_graph_db")

    @patch("database.neo4j_client.GraphDatabase.driver")
    def test_env_database_selection(self, mock_driver_cls, monkeypatch):
        """NEO4J_DATABASE environment variable is picked up when argument is None."""
        monkeypatch.setenv("NEO4J_DATABASE", "env_configured_db")
        mock_driver_instance = MagicMock()
        mock_driver_cls.return_value = mock_driver_instance

        client = Neo4jClient()
        assert client.database == "env_configured_db"
        assert client.is_protected_database() is False

        _ = client.session()
        mock_driver_instance.session.assert_called_once_with(database="env_configured_db")

    @patch("database.neo4j_client.GraphDatabase.driver")
    def test_argument_overrides_env_database(self, mock_driver_cls, monkeypatch):
        """Explicit argument overrides NEO4J_DATABASE environment variable."""
        monkeypatch.setenv("NEO4J_DATABASE", "env_configured_db")
        mock_driver_instance = MagicMock()
        mock_driver_cls.return_value = mock_driver_instance

        client = Neo4jClient(database="param_override_db")
        assert client.database == "param_override_db"

        _ = client.session()
        mock_driver_instance.session.assert_called_once_with(database="param_override_db")

    @patch("database.neo4j_client.GraphDatabase.driver")
    def test_empty_or_whitespace_database_normalizes_to_none(self, mock_driver_cls, monkeypatch):
        """Empty or whitespace-only database values safely normalize to None."""
        monkeypatch.setenv("NEO4J_DATABASE", "   ")
        mock_driver_instance = MagicMock()
        mock_driver_cls.return_value = mock_driver_instance

        client = Neo4jClient()
        assert client.database is None
        assert client.is_protected_database() is True

        _ = client.session()
        mock_driver_instance.session.assert_called_once_with()


class TestNeo4jClientDestructiveOperationGuard:
    @patch("database.neo4j_client.GraphDatabase.driver")
    def test_clear_database_blocks_on_default_database_without_force(self, mock_driver_cls, monkeypatch):
        """Attempting to clear the default database without force=True raises RuntimeError."""
        monkeypatch.delenv("NEO4J_DATABASE", raising=False)
        mock_driver_cls.return_value = MagicMock()

        client = Neo4jClient()
        with pytest.raises(RuntimeError) as exc_info:
            client.clear_database()
        assert "Destructive operation blocked" in str(exc_info.value)
        assert "default" in str(exc_info.value)

    @patch("database.neo4j_client.GraphDatabase.driver")
    def test_clear_database_blocks_on_protected_neo4j_without_force(self, mock_driver_cls):
        """Attempting to clear the 'neo4j' database without force=True raises RuntimeError."""
        mock_driver_cls.return_value = MagicMock()

        client = Neo4jClient(database="neo4j")
        with pytest.raises(RuntimeError) as exc_info:
            client.clear_database()
        assert "Destructive operation blocked" in str(exc_info.value)
        assert "neo4j" in str(exc_info.value)

    @patch("database.neo4j_client.GraphDatabase.driver")
    def test_clear_database_blocks_on_protected_system_without_force(self, mock_driver_cls):
        """Attempting to clear the 'system' database without force=True raises RuntimeError."""
        mock_driver_cls.return_value = MagicMock()

        client = Neo4jClient(database="system")
        with pytest.raises(RuntimeError) as exc_info:
            client.clear_database()
        assert "Destructive operation blocked" in str(exc_info.value)
        assert "system" in str(exc_info.value)

    @patch("database.neo4j_client.GraphDatabase.driver")
    def test_clear_database_allowed_with_explicit_force_on_default(self, mock_driver_cls, monkeypatch):
        """Deliberate clearing of default database succeeds when force=True is explicitly passed."""
        monkeypatch.delenv("NEO4J_DATABASE", raising=False)
        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_driver.session.return_value.__enter__.return_value = mock_session
        mock_driver_cls.return_value = mock_driver

        client = Neo4jClient()
        client.clear_database(force=True)
        mock_session.run.assert_called_once_with("MATCH (n) DETACH DELETE n")

    @patch("database.neo4j_client.GraphDatabase.driver")
    def test_clear_database_allowed_on_dedicated_test_database(self, mock_driver_cls):
        """Clearing a dedicated test database (e.g. 'testdb') succeeds without requiring force=True."""
        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_driver.session.return_value.__enter__.return_value = mock_session
        mock_driver_cls.return_value = mock_driver

        client = Neo4jClient(database="testdb")
        client.clear_database()
        mock_session.run.assert_called_once_with("MATCH (n) DETACH DELETE n")


class TestLiveTestDatabaseConfigurationFailClosed:
    def test_get_live_test_database_name_default(self, monkeypatch):
        """Default testdb is returned when environment is unset."""
        monkeypatch.delenv("NEO4J_TEST_DATABASE", raising=False)
        assert get_live_test_database_name() == "testdb"

    def test_get_live_test_database_name_custom(self, monkeypatch):
        """Explicit custom test database is returned."""
        monkeypatch.setenv("NEO4J_TEST_DATABASE", "ci_quarantine_db")
        assert get_live_test_database_name() == "ci_quarantine_db"

    def test_get_live_test_database_name_fails_closed_when_empty(self, monkeypatch):
        """Fails closed when NEO4J_TEST_DATABASE is set to empty string."""
        monkeypatch.setenv("NEO4J_TEST_DATABASE", "   ")
        with pytest.raises(RuntimeError) as exc_info:
            get_live_test_database_name()
        assert "FAIL CLOSED" in str(exc_info.value)

    def test_get_live_test_database_name_fails_closed_when_targeting_neo4j(self, monkeypatch):
        """Fails closed when NEO4J_TEST_DATABASE is set to 'neo4j'."""
        monkeypatch.setenv("NEO4J_TEST_DATABASE", "neo4j")
        with pytest.raises(RuntimeError) as exc_info:
            get_live_test_database_name()
        assert "FAIL CLOSED" in str(exc_info.value)
        assert "protected or main" in str(exc_info.value)

    def test_get_live_test_database_name_fails_closed_when_targeting_system(self, monkeypatch):
        """Fails closed when NEO4J_TEST_DATABASE is set to 'system'."""
        monkeypatch.setenv("NEO4J_TEST_DATABASE", "system")
        with pytest.raises(RuntimeError) as exc_info:
            get_live_test_database_name()
        assert "FAIL CLOSED" in str(exc_info.value)


class TestSessionCreationMethodConsistency:
    @patch("maintenance.export.Neo4jClient")
    def test_export_diagram_uses_client_session(self, mock_client_cls):
        """maintenance.export.export_diagram uses client.session() instead of bypassing via client.driver.session()."""
        from maintenance.export import export_diagram

        mock_client = MagicMock()
        mock_session = MagicMock()
        mock_client.session.return_value.__enter__.return_value = mock_session
        mock_session.run.return_value = []
        mock_client_cls.return_value = mock_client

        export_diagram(file_path="architecture.mermaid", fmt="mermaid", method="static")
        mock_client.session.assert_called_once()
        mock_client.driver.session.assert_not_called()

    @patch("maintenance.stats.Neo4jClient")
    def test_stats_uses_client_session(self, mock_client_cls):
        """maintenance.stats.print_performance_stats uses client.session() instead of bypassing."""
        from maintenance.stats import print_performance_stats

        mock_client = MagicMock()
        mock_session = MagicMock()
        mock_client.session.return_value.__enter__.return_value = mock_session
        mock_session.run.return_value.single.return_value = {"c": 0}
        mock_client_cls.return_value = mock_client

        print_performance_stats(start_time=0.0)
        mock_client.session.assert_called_once()
        mock_client.driver.session.assert_not_called()

    @patch("enrichment.clustering.Neo4jClient")
    def test_clustering_uses_client_session(self, mock_client_cls):
        """enrichment.clustering.cluster_graph uses client.session() instead of bypassing."""
        from enrichment.clustering import cluster_graph

        mock_client = MagicMock()
        mock_session = MagicMock()
        mock_client.session.return_value.__enter__.return_value = mock_session
        mock_session.run.return_value = []
        mock_client_cls.return_value = mock_client

        res = cluster_graph()
        assert res == {}
        mock_client.session.assert_called_once()
        mock_client.driver.session.assert_not_called()
