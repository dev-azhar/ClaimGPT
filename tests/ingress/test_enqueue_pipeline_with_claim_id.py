from unittest.mock import MagicMock, patch
import pytest

def test_enqueue_pipeline_with_string_claim_id_celery():
    # Mock _should_run_inline to return False (Celery mode)
    with patch("services.ingress.app.main._should_run_inline", return_value=False), \
         patch("services.ingress.app.main.chain") as mock_chain, \
         patch("services.ingress.app.main.ocr_task") as mock_ocr, \
         patch("services.ingress.app.main.parser_task") as mock_parser, \
         patch("services.ingress.app.main.coding_task") as mock_coding, \
         patch("services.ingress.app.main.risk_task") as mock_risk, \
         patch("services.ingress.app.main.validator_task") as mock_validator, \
         patch("services.ingress.app.main.finalize_claim_task") as mock_finalize:
        
        from services.ingress.app.main import _enqueue_pipeline

        # Set up celery task signature mocks
        mock_chain_instance = MagicMock()
        mock_chain.return_value = mock_chain_instance
        mock_result = MagicMock()
        mock_result.id = "mock-task-id-123"
        mock_chain_instance.apply_async.return_value = mock_result

        claim_id_str = "cde6b866-3b50-4892-b2c9-4573bd9943f8"
        result_task_id = _enqueue_pipeline(claim_id_str)

        # Assert correct task ID is returned
        assert result_task_id == "mock-task-id-123"

        # Assert that intake_task was NOT included in the chain
        # and that the chain started with ocr_task.s(claim_id_str)
        mock_ocr.s.assert_called_once_with(claim_id_str)
        mock_parser.s.assert_called_once()
        mock_coding.s.assert_called_once()
        mock_risk.s.assert_called_once()
        mock_validator.s.assert_called_once()
        mock_finalize.s.assert_called_once()

        # Check chain structure
        mock_chain.assert_called_once_with(
            mock_ocr.s(claim_id_str),
            mock_parser.s(),
            mock_coding.s(),
            mock_risk.s(),
            mock_validator.s(),
            mock_finalize.s(),
        )


def test_enqueue_pipeline_with_string_claim_id_inline():
    # Mock _should_run_inline to return True (Inline mode)
    with patch("services.ingress.app.main._should_run_inline", return_value=True), \
         patch("services.ingress.app.main.run_pipeline_inline") as mock_run_inline, \
         patch("threading.Thread") as mock_thread_class:
        
        from services.ingress.app.main import _enqueue_pipeline

        mock_thread_instance = MagicMock()
        mock_thread_class.return_value = mock_thread_instance

        claim_id_str = "cde6b866-3b50-4892-b2c9-4573bd9943f8"
        result = _enqueue_pipeline(claim_id_str)

        # Assert correct result in inline mode
        assert result == "inline:queued"
        
        # Verify thread was configured and started
        mock_thread_class.assert_called_once()
        kwargs = mock_thread_class.call_args[1]
        assert kwargs["name"] == "inline-pipeline"
        assert kwargs["daemon"] is True
        
        # Start should be called on the thread
        mock_thread_instance.start.assert_called_once()
