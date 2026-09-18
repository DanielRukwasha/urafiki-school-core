"""Grade entry and its immutable audit trail.

Grade uniqueness on (enrollment_id, course_id, period_id) is the single
source of truth for "one score per student, per course, per period" and is
enforced at the database level, not just in application code.
"""

import enum

from app.extensions import db
from app.models.mixins import SoftDeleteMixin, TimestampMixin, utcnow
from app.models.tenant_scope import TenantScopedModel


class Grade(db.Model, TenantScopedModel, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "grades"
    __table_args__ = (
        db.UniqueConstraint(
            "ecole_id",
            "enrollment_id",
            "course_id",
            "period_id",
            name="uq_grade_ecole_enrollment_course_period",
        ),
        db.CheckConstraint("score >= 0", name="ck_grade_score_non_negative"),
    )

    id = db.Column(db.Integer, primary_key=True)
    enrollment_id = db.Column(
        db.Integer, db.ForeignKey("enrollments.id"), nullable=False, index=True
    )
    course_id = db.Column(
        db.Integer, db.ForeignKey("courses.id"), nullable=False, index=True
    )
    period_id = db.Column(
        db.Integer, db.ForeignKey("evaluation_periods.id"), nullable=False, index=True
    )
    score = db.Column(db.Numeric(6, 2), nullable=False)
    entered_by_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    is_validated = db.Column(db.Boolean, nullable=False, default=False)

    enrollment = db.relationship("Enrollment", back_populates="grades")
    course = db.relationship("Course", back_populates="grades")
    period = db.relationship("EvaluationPeriod", back_populates="grades")
    entered_by = db.relationship("User")
    audit_logs = db.relationship("GradeAuditLog", back_populates="grade")

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Grade enrollment={self.enrollment_id} course={self.course_id} "
            f"period={self.period_id} score={self.score}>"
        )


class GradeAuditAction(str, enum.Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"


class GradeAuditLog(db.Model, TenantScopedModel):
    """Immutable audit record. Never updated after insert."""

    __tablename__ = "grade_audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    grade_id = db.Column(
        db.Integer,
        db.ForeignKey("grades.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Snapshot columns so the audit trail survives grade deletion.
    enrollment_id = db.Column(db.Integer, nullable=False)
    course_id = db.Column(db.Integer, nullable=False)
    period_id = db.Column(db.Integer, nullable=False)

    action = db.Column(db.Enum(GradeAuditAction), nullable=False)
    old_value = db.Column(db.Numeric(6, 2), nullable=True)
    new_value = db.Column(db.Numeric(6, 2), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    ip_address = db.Column(db.String(45), nullable=True)  # IPv4 or IPv6
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    grade = db.relationship("Grade", back_populates="audit_logs")
    user = db.relationship("User")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<GradeAuditLog {self.action} grade={self.grade_id}>"
