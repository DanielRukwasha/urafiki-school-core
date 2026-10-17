"""Journal of sensitive READS (invariant 10: "tout est journalisé", reads
included). Writes already have their own trails (GradeAuditLog,
DeliberationAuditLog); super-admin access goes to TenantAccessAuditLog.

Rows are written by `app/services/journal_lectures.py` — a decorator on
the functions that produce sensitive data, never by code duplicated in
each route. Never updated, never deleted.
"""

from __future__ import annotations

import enum

from app.extensions import db
from app.models.mixins import utcnow
from app.models.tenant_scope import TenantScopedModel


class SensitiveReadKind(str, enum.Enum):
    BULLETIN_CONSULTATION = "BULLETIN_CONSULTATION"
    EXPORT_DONNEES = "EXPORT_DONNEES"


class SensitiveReadLog(db.Model, TenantScopedModel):
    __tablename__ = "sensitive_read_logs"

    id = db.Column(db.Integer, primary_key=True)
    # Stored as a plain string (validated against SensitiveReadKind by the
    # service) so adding a kind never requires an enum-type migration.
    kind = db.Column(db.String(40), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    # Who acted when there is no authenticated user (CLI export, job).
    actor_label = db.Column(db.String(100), nullable=True)
    resource = db.Column(db.String(300), nullable=False)
    ip_address = db.Column(db.String(45), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    user = db.relationship("User")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SensitiveReadLog {self.kind} {self.resource}>"


class ImmutableLogError(RuntimeError):
    pass


@db.event.listens_for(SensitiveReadLog, "before_update")
@db.event.listens_for(SensitiveReadLog, "before_delete")
def _forbid_mutation(_mapper, _connection, _target):
    raise ImmutableLogError("Journal des lectures sensibles : entrée immuable.")
