from uuid import UUID

from sqlalchemy.orm import Session

from app.models import ImportBatch


def delete_import_batch(session: Session, *, batch_id: UUID) -> bool:
    """Atomically delete one visible import batch and its database-owned dependents."""
    batch = session.get(ImportBatch, batch_id)
    if batch is None:
        return False

    try:
        session.delete(batch)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return True
