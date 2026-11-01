import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient
from src.api.main import app
from src.api.demo_router import get_configured_api_key

client = TestClient(app)

def run_all_auth_tests():
    configured_key = get_configured_api_key()
    print(f"Configured key from .env/environment: {configured_key}")
    assert configured_key is not None, "DEMO_API_KEY must be configured in .env"

    # Test 1: Missing key with unknown run ID -> MUST return 401 (NOT 404)
    resp_missing = client.post("/api/demo/runs/test-auth-check/logs", json={"log_chunk": "auth test"})
    print(f"Test 1 [Missing key, unknown run]: status={resp_missing.status_code}, body={resp_missing.json()}")
    assert resp_missing.status_code == 401
    assert "Unauthorized" in resp_missing.json()["detail"]

    # Test 2: Invalid key with unknown run ID -> MUST return 401 (NOT 404)
    resp_invalid = client.post(
        "/api/demo/runs/test-auth-check/logs",
        headers={"X-API-Key": "wrong-token-abc-123"},
        json={"log_chunk": "auth test"}
    )
    print(f"Test 2 [Invalid key, unknown run]: status={resp_invalid.status_code}, body={resp_invalid.json()}")
    assert resp_invalid.status_code == 401
    assert "Unauthorized" in resp_invalid.json()["detail"]

    # Test 3: Valid key with unknown run ID -> MUST return 404 (Auth passed, run not found)
    resp_unknown_run = client.post(
        "/api/demo/runs/test-auth-check/logs",
        headers={"X-API-Key": configured_key},
        json={"log_chunk": "auth test"}
    )
    print(f"Test 3 [Valid key, unknown run]: status={resp_unknown_run.status_code}, body={resp_unknown_run.json()}")
    assert resp_unknown_run.status_code == 404
    assert "not found" in resp_unknown_run.json()["detail"].lower()

    # Test 4: Valid key with existing run ID -> MUST return 200
    create_resp = client.post("/api/demo/runs", json={
        "repo_id": "demo-order-service",
        "changed_files": ["src/validator.py"],
        "auto_advance": False,
    })
    assert create_resp.status_code == 200
    run_id = create_resp.json()["run_id"]

    resp_valid = client.post(
        f"/api/demo/runs/{run_id}/logs",
        headers={"X-API-Key": configured_key},
        json={"log_chunk": "2026-10-27 Step 1 passed", "stage": "build", "depth": 25}
    )
    print(f"Test 4 [Valid key, existing run]: status={resp_valid.status_code}, status_label={resp_valid.json().get('status')}")
    assert resp_valid.status_code == 200
    assert resp_valid.json()["status"] == "running"

    # Test 5: Valid key using Authorization Bearer header -> MUST return 200
    resp_bearer = client.post(
        f"/api/demo/runs/{run_id}/logs",
        headers={"Authorization": f"Bearer {configured_key}"},
        json={"log_chunk": "2026-10-27 Step 2 passed", "stage": "build", "depth": 50}
    )
    print(f"Test 5 [Bearer token, existing run]: status={resp_bearer.status_code}")
    assert resp_bearer.status_code == 200

    print("\n>>> ALL 5 AUTHENTICATION ORDER & LOG INGESTION TESTS PASSED! <<<")

if __name__ == "__main__":
    run_all_auth_tests()
