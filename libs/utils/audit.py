"""
Audit logging utility for HIPAA compliance.

Writes structured audit entries to the audit_logs table.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

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
        claim_id: uuid.UUID | None = None,
        actor: str | None = None,
        metadata: dict[str, Any] | None = None,
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
                "created_at": datetime.now(UTC),
            },
        )
        self._db.commit()
        logger.info("AUDIT [%s] %s claim=%s", self._service, action, claim_id)


def _to_json(obj: Any) -> str | None:
    if obj is None:
        return None
    import json
    return json.dumps(obj, default=str)
