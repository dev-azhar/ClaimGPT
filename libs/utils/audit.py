"""
Audit logging utility for HIPAA compliance.

Writes structured audit entries to the audit_logs table.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session


logger = logging.getLogger("audit")


class AuditLogger:
    """Writes audit events to the audit_logs table."""

    def __init__(self, db: Session, service_name: str):
        self._db = db
        self._service = service_name

    def log(
        self,
        action: str,
        claim_id: Optional[uuid.UUID] = None,
        actor: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Insert an audit log entry."""
        from sqlalchemy import text

        self._db.execute(
            text(
                "INSERT INTO audit_logs (id, claim_id, actor, action, metadata, created_at) "
                "VALUES (:id, :claim_id, :actor, :action, :metadata, :created_at)"
            ),
            {
                "id": str(uuid.uuid4()),
                "claim_id": str(claim_id) if claim_id else None,
                "actor": actor or self._service,
                "action": action,
                "metadata": _to_json(metadata),
                "created_at": datetime.now(timezone.utc),
            },
        )
        self._db.commit()
        logger.info("AUDIT [%s] %s claim=%s", self._service, action, claim_id)


def _to_json(obj: Any) -> Optional[str]:
    if obj is None:
        return None
    import json
    return json.dumps(obj, default=str)
