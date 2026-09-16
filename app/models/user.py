"""User accounts and roles (RBAC).

Roles are intentionally a fixed enum shared by every deployment: the set of
staff roles (Direction, Enseignant, Secrétariat) is structural to the
domain, not a per-school configuration value.
"""

import enum

from flask_login import UserMixin

from app.extensions import bcrypt, db
from app.models.mixins import SoftDeleteMixin, TimestampMixin


class RoleEnum(str, enum.Enum):
    DIRECTION = "DIRECTION"
    ENSEIGNANT = "ENSEIGNANT"
    SECRETARIAT = "SECRETARIAT"


class User(db.Model, UserMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(200), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.Enum(RoleEnum), nullable=False)
    is_active_account = db.Column(db.Boolean, nullable=False, default=True)
    last_login_at = db.Column(db.DateTime(timezone=True), nullable=True)

    teacher_assignments = db.relationship(
        "TeacherAssignment", back_populates="teacher", lazy="dynamic"
    )

    def set_password(self, raw_password: str) -> None:
        self.password_hash = bcrypt.generate_password_hash(raw_password).decode(
            "utf-8"
        )

    def check_password(self, raw_password: str) -> bool:
        return bcrypt.check_password_hash(self.password_hash, raw_password)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    # Flask-Login integration
    @property
    def is_active(self) -> bool:  # type: ignore[override]
        return self.is_active_account and not self.is_archived

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.email} ({self.role})>"
