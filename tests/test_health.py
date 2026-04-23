"""Tests for FastAPI endpoints across services (using TestClient)."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure service packages are importable
for svc in ["ingress", "ocr", "parser", "coding", "predictor", "validator", "workflow", "submission", "chat", "search"]:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / svc))


class TestHealthEndpoints:
    """Verify /health endpoints return correct structure on all services."""

    @pytest.fixture(params=[
        "ingress", "ocr", "parser", "coding", "predictor",
        "validator", "workflow", "submission", "chat", "search",
    ])
    def service_app(self, request):
        """Import and return a FastAPI app for the given service."""
        svc = request.param
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / svc))
        # Patch DB health check to avoid needing real Postgres
        with patch(f"app.db.check_db_health", return_value=True):
            from importlib import import_module, reload
            mod = import_module("app.main")
            reload(mod)  # ensure fresh import
            return mod.app

    def test_health_returns_ok(self, service_app):
        from fastapi.testclient import TestClient
        with patch("app.db.check_db_health", return_value=True):
            client = TestClient(service_app)
            resp = client.get("/health")
            assert resp.status_code == 200
            data = resp.json()
            assert "status" in data
