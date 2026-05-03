"""Tests for the chat LLM layer."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "chat"))
for _k in [k for k in sys.modules if k == "app" or k.startswith("app.")]:
    del sys.modules[_k]

from app.llm import build_system_prompt, call_llm, scrub_phi
from app import llm as _llm_mod


class TestScrubPHI:
    def test_ssn_scrubbed(self):
        text = "SSN: 123-45-6789"
        result = scrub_phi(text)
        assert "123-45-6789" not in result

    def test_policy_scrubbed(self):
        text = "Policy AB12345678"
        result = scrub_phi(text)
        assert "AB12345678" not in result


class TestBuildSystemPrompt:
    def test_no_context(self):
        prompt = build_system_prompt(None)
        assert "ClaimGPT" in prompt

    def test_with_context(self):
        ctx = {"claim_id": "abc", "status": "UPLOADED"}
        prompt = build_system_prompt(ctx)
        assert "abc" in prompt
        assert "UPLOADED" in prompt


class TestCallLLM:
    @patch.object(_llm_mod, "httpx")
    def test_successful_call(self, mock_httpx):
        mock_client = MagicMock()
        mock_httpx.Client.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_httpx.Client.return_value.__exit__ = MagicMock(return_value=False)
        mock_httpx.Timeout = MagicMock()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "message": {"content": "Here is the claim info."}
        }
        mock_resp.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_resp

        result = call_llm([{"role": "user", "content": "What is this claim?"}])
        assert result == "Here is the claim info."

    @patch.object(_llm_mod, "httpx")
    def test_fallback_on_failure(self, mock_httpx):
        mock_client = MagicMock()
        mock_httpx.Client.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_httpx.Client.return_value.__exit__ = MagicMock(return_value=False)
        mock_httpx.Timeout = MagicMock()
        mock_client.post.side_effect = Exception("Connection refused")

        result = call_llm([{"role": "user", "content": "Hello"}])
        # Fallback is now _local_assistant which gives a conversational response
        assert isinstance(result, str) and len(result) > 0
