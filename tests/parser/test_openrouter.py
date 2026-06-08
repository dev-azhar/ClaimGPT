import pytest
import httpx
from unittest.mock import patch, MagicMock
from services.parser_v2.semantic_backends import OpenRouterBackend, SemanticRequest

def _make_dummy_request() -> SemanticRequest:
    return SemanticRequest(
        region_id="reg-123",
        region_type="expense_table",
        page=1,
        document_id="doc-456",
        claim_id="claim-789",
        text="Dummy region text with charges",
        tokens=[],
    )

def test_openrouter_rate_limit_exhaustion_no_unbound_local_error(monkeypatch):
    """Test that when OpenRouter rates limits (429) and exhausts retries, it returns None
    without raising UnboundLocalError."""
    # Ensure concurreny is True/False (we bypass global lock or not)
    backend = OpenRouterBackend(
        url="http://fake-openrouter/api/v1/chat/completions",
        model="test-model",
    )
    backend.api_key = "key1"
    
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 429
    
    # We patch time.sleep to avoid waiting in tests
    with patch("httpx.post", return_value=mock_response) as mock_post, \
         patch("time.sleep", return_value=None) as mock_sleep:
         
        res = backend.analyze(_make_dummy_request())
        
        assert res is None
        # Should attempt 4 times (1 initial + 3 retries)
        assert mock_post.call_count == 4

def test_openrouter_unauthorized_key_falls_back_and_returns_none():
    """Test that when OpenRouter key is unauthorized (401), it skips the key and returns None
    without raising UnboundLocalError."""
    backend = OpenRouterBackend(
        url="http://fake-openrouter/api/v1/chat/completions",
        model="test-model",
    )
    backend.api_key = "key1,key2"
    
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 401
    
    with patch("httpx.post", return_value=mock_response) as mock_post:
        res = backend.analyze(_make_dummy_request())
        
        assert res is None
        # Should attempt 2 times (once per key)
        assert mock_post.call_count == 2

def test_openrouter_first_key_fails_second_key_succeeds():
    """Test that when the first key rate limits, the second key is tried and if it succeeds,
    the response is returned."""
    backend = OpenRouterBackend(
        url="http://fake-openrouter/api/v1/chat/completions",
        model="test-model",
    )
    backend.api_key = "key1,key2"
    
    resp_429 = MagicMock(spec=httpx.Response)
    resp_429.status_code = 429
    
    resp_200 = MagicMock(spec=httpx.Response)
    resp_200.status_code = 200
    resp_200.json.return_value = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": '{"region_type": "expense_table", "table_kind": "expenses", "confidence": 0.9, "fields": [], "tables": []}'
                }
            }
        ]
    }
    
    call_count = 0
    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 4:  # key1 429 attempts (1 initial + 3 retries)
            return resp_429
        return resp_200

    with patch("httpx.post", side_effect=side_effect) as mock_post, \
         patch("time.sleep", return_value=None) as mock_sleep:
         
        res = backend.analyze(_make_dummy_request())
        
        assert res is not None
        assert res["region_type"] == "expense_table"
        assert res["confidence"] == 0.9
        # 4 calls for key1 (exhausted), 1 call for key2 (succeeded) = 5 total calls
        assert mock_post.call_count == 5
