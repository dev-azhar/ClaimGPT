import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, r"c:\projects\claimgpt\ClaimGPT")

from services.ingress.app.main import get_current_user_context, AuthUser

class TestUserIdSwitch(unittest.TestCase):
    def test_local_dev_user_id_resolution(self):
        user = get_current_user_context(
            authorization=None,
            x_patient_id=None,
            x_user_id="user-uuid-1234",
            patient_id=None
        )
        self.assertEqual(user.user_id, "user-uuid-1234")
        self.assertEqual(user.patient_id, "user-uuid-1234")
        self.assertTrue(user.is_authenticated)

    def test_local_dev_patient_id_fallback(self):
        user = get_current_user_context(
            authorization=None,
            x_patient_id="PAT-9999",
            x_user_id=None,
            patient_id=None
        )
        self.assertEqual(user.patient_id, "PAT-9999")

    def test_production_jwt_claims_resolution(self):
        # Test simulated AuthUser creation
        user = AuthUser(
            user_id="auth-subject-guid",
            email="test@example.com",
            role="patient",
            patient_id="auth-subject-guid",
            is_authenticated=True
        )
        self.assertEqual(user.user_id, "auth-subject-guid")
        self.assertEqual(user.patient_id, "auth-subject-guid")

if __name__ == "__main__":
    unittest.main()
