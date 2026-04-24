"""Tests for the workflow pipeline logic."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "workflow"))

from app.pipeline import PIPELINE_STEPS, PipelineResult, run_pipeline


class TestPipelineSteps:
    def test_pipeline_has_five_steps(self):
        assert len(PIPELINE_STEPS) == 5
        step_names = [s[0] for s in PIPELINE_STEPS]
        assert step_names == ["ocr", "parse", "code_suggest", "predict", "validate"]

    @patch("app.pipeline.httpx.Client")
    def test_all_steps_succeed(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client.request.return_value = mock_resp

        result = run_pipeline("test-claim-id")
        assert result.success is True
        assert len(result.steps) == 5
        assert all(s.status == "DONE" for s in result.steps)

    @patch("app.pipeline.httpx.Client")
    def test_step_failure_stops_pipeline(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        # First step OK, second fails
        ok_resp = MagicMock()
        ok_resp.status_code = 200
        fail_resp = MagicMock()
        fail_resp.status_code = 422
        fail_resp.text = "Validation error"
        mock_client.request.side_effect = [ok_resp, fail_resp]

        result = run_pipeline("test-claim-id")
        assert result.success is False
        assert result.failed_step == "parse"
        assert len(result.steps) == 2

    @patch("app.pipeline.httpx.Client")
    def test_409_skips_step(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        skip_resp = MagicMock()
        skip_resp.status_code = 409
        skip_resp.text = "Precondition not met"
        ok_resp = MagicMock()
        ok_resp.status_code = 200

        mock_client.request.side_effect = [ok_resp, skip_resp, ok_resp, ok_resp, ok_resp]

        result = run_pipeline("test-claim-id")
        assert result.success is True
        skipped = [s for s in result.steps if s.status == "SKIPPED"]
        assert len(skipped) == 1


class TestPipelineResult:
    def test_dataclass_defaults(self):
        r = PipelineResult(success=True)
        assert r.steps == []
        assert r.failed_step is None
