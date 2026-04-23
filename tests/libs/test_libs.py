"""Tests for shared libs — PHI scrubbing, schemas, auth models."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "libs"))


class TestPHIScrubbing:
    def test_ssn_redaction(self):
        from utils.phi import scrub_phi
        text = "Patient SSN is 123-45-6789 in records"
        result = scrub_phi(text)
        assert "123-45-6789" not in result
        assert "[SSN_REDACTED]" in result

    def test_email_redaction(self):
        from utils.phi import scrub_phi
        text = "Contact patient at john@example.com"
        result = scrub_phi(text)
        assert "john@example.com" not in result
        assert "[EMAIL_REDACTED]" in result

    def test_phone_redaction(self):
        from utils.phi import scrub_phi
        text = "Phone: (555) 123-4567"
        result = scrub_phi(text)
        assert "123-4567" not in result

    def test_no_phi_unchanged(self):
        from utils.phi import scrub_phi
        text = "This is a normal medical claim document"
        assert scrub_phi(text) == text

    def test_multiple_phi_types(self):
        from utils.phi import scrub_phi
        text = "SSN: 123-45-6789, Email: a@b.com, Phone: 555-123-4567"
        result = scrub_phi(text)
        assert "123-45-6789" not in result
        assert "a@b.com" not in result

    def test_custom_patterns(self):
        from utils.phi import scrub_phi
        text = "MRN is ABC123"
        result = scrub_phi(text, extra_patterns={r"ABC\d+": "[CUSTOM]"})
        assert "ABC123" not in result
        assert "[CUSTOM]" in result


class TestClaimStatus:
    def test_status_values(self):
        from schemas.claim import ClaimStatus
        assert ClaimStatus.UPLOADED == "UPLOADED"
        assert ClaimStatus.SUBMITTED == "SUBMITTED"
        assert ClaimStatus.REJECTED == "REJECTED"


class TestEventSchemas:
    def test_claim_ingested_event(self):
        import uuid

        from schemas.events import ClaimIngestedEvent
        event = ClaimIngestedEvent(
            claim_id=uuid.uuid4(),
            policy_id="POL-123",
        )
        assert event.event_type == "claim.ingested"

    def test_event_envelope(self):
        from schemas.events import EventEnvelope
        env = EventEnvelope(
            event_type="test.event",
            source_service="test",
        )
        assert env.event_id is not None
        assert env.timestamp is not None


class TestAuthModels:
    def test_token_payload_roles(self):
        from auth.models import TokenPayload
        token = TokenPayload(
            sub="user-1",
            realm_access={"roles": ["admin", "reviewer"]},
        )
        assert token.has_role("admin")
        assert not token.has_role("submitter")
        assert "admin" in token.roles

    def test_user_role_enum(self):
        from auth.models import UserRole
        assert UserRole.ADMIN.value == "admin"
        assert UserRole.SERVICE.value == "service"
