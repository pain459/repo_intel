"""Health endpoint tests."""
import pytest
from fastapi.testclient import TestClient

from repo_intel.api.app import create_app


@pytest.fixture
def app_client():
    """Create a test client for the FastAPI app."""
    app = create_app()
    return TestClient(app)


def test_health_live(app_client):
    resp = app_client.get("/health/live")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


def test_health_ready_responds(app_client):
    """Ready endpoint always returns a structured response (200 or 503)."""
    resp = app_client.get("/health/ready")
    assert resp.status_code in (200, 503)
    data = resp.json()
    assert "database" in data
    assert "ollama" in data
