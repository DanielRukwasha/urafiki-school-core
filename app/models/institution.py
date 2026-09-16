"""Institution: per-deployment identity/config — the school running this instance.

Deliberately generic: no school-specific data lives in code, only here in
a single configuration row seeded at deployment time.
"""

from app.extensions import db
from app.models.mixins import TimestampMixin


class Institution(db.Model, TimestampMixin):
    __tablename__ = "institutions"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    short_code = db.Column(db.String(20), nullable=False, unique=True)
    address = db.Column(db.String(300), nullable=True)
    timezone = db.Column(db.String(64), nullable=False, default="UTC")
    contact_email = db.Column(db.String(200), nullable=True)
    contact_phone = db.Column(db.String(50), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Institution {self.short_code}>"
