from __future__ import annotations

import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from libs.shared.models import WorkflowState


def upsert_workflow_state(
    db: Session,
    claim_id: str | uuid.UUID,
    current_step: str,
    status: str | None = None,
) -> WorkflowState:
    """Create or update the single workflow_state row for a claim atomically."""
    cid = uuid.UUID(str(claim_id))
    payload = {
        "claim_id": cid,
        "current_step": current_step,
        "status": status or "RUNNING",
    }

    bind = db.get_bind()
    dialect_name = getattr(getattr(bind, "dialect", None), "name", "") if bind else ""

    if dialect_name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = pg_insert(WorkflowState).values(**payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=[WorkflowState.claim_id],
            set_={
                "current_step": stmt.excluded.current_step,
                "status": stmt.excluded.status,
                "updated_at": func.now(),
            },
        )
        db.execute(stmt)
        db.flush()
    elif dialect_name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        stmt = sqlite_insert(WorkflowState).values(**payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=[WorkflowState.claim_id],
            set_={
                "current_step": stmt.excluded.current_step,
                "status": stmt.excluded.status,
                "updated_at": func.now(),
            },
        )
        db.execute(stmt)
        db.flush()
    else:
        state = db.get(WorkflowState, cid)
        if state is None:
            state = WorkflowState(**payload)
            db.add(state)
        else:
            state.current_step = current_step
            state.status = status or state.status or "RUNNING"
        db.flush()

    return (
        db.query(WorkflowState)
        .filter(WorkflowState.claim_id == cid)
        .order_by(WorkflowState.updated_at.desc(), WorkflowState.current_step.desc())
        .first()
    )


def get_latest_workflow_state(db: Session, claim_id: str | uuid.UUID) -> WorkflowState | None:
    """Return the most recently updated workflow row, tolerating legacy duplicates."""
    cid = uuid.UUID(str(claim_id))
    return (
        db.query(WorkflowState)
        .filter(WorkflowState.claim_id == cid)
        .order_by(WorkflowState.updated_at.desc(), WorkflowState.current_step.desc())
        .first()
    )