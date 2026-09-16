"""Shared model mixins: UTC timestamps and soft-delete/archival semantics."""

from datetime import UTC, datetime

from app.extensions import db


def utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )


class SoftDeleteMixin:
    archived_at = db.Column(db.DateTime(timezone=True), nullable=True)

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None

    def archive(self) -> None:
        self.archived_at = utcnow()

    def restore(self) -> None:
        self.archived_at = None
