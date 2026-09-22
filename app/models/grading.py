"""Grade entry and its immutable audit trail.

Grade uniqueness on (enrollment_id, grille_cours_ligne_id, period_id) is
the single source of truth for "one grade per student, per grid line, per
period" and is enforced at the database level, not just in application
code.

A grade is exactly one of: a numeric `score`, a textual `appreciation`
(when `GrilleCoursLigne.note_par_appreciation` is true), or a `statut`
explaining why neither is present (justified absence, exemption) — never
more than one, and for a normal, already-graded row, at least one of
score/appreciation. Enforced in the service layer (which can raise a
clear, tenant-configured message) and backstopped by a database
CHECK constraint.
"""

import enum

from app.extensions import db
from app.models.mixins import SoftDeleteMixin, TimestampMixin, utcnow
from app.models.tenant_scope import TenantScopedModel


class GradeStatut(str, enum.Enum):
    ABSENCE_JUSTIFIEE = "ABSENCE_JUSTIFIEE"
    DISPENSE = "DISPENSE"


class Grade(db.Model, TenantScopedModel, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "grades"
    __table_args__ = (
        db.UniqueConstraint(
            "ecole_id",
            "enrollment_id",
            "grille_cours_ligne_id",
            "period_id",
            name="uq_grade_ecole_enrollment_ligne_period",
        ),
        db.CheckConstraint("score >= 0", name="ck_grade_score_non_negative"),
        db.CheckConstraint(
            "NOT (score IS NOT NULL AND appreciation IS NOT NULL)",
            name="ck_grade_score_xor_appreciation",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    enrollment_id = db.Column(
        db.Integer, db.ForeignKey("enrollments.id"), nullable=False, index=True
    )
    grille_cours_ligne_id = db.Column(
        db.Integer, db.ForeignKey("grille_cours_lignes.id"), nullable=False, index=True
    )
    period_id = db.Column(
        db.Integer, db.ForeignKey("evaluation_periods.id"), nullable=False, index=True
    )
    score = db.Column(db.Numeric(6, 2), nullable=True)
    appreciation = db.Column(db.String(500), nullable=True)
    # Explains an absent score/appreciation without it counting as
    # "not yet encoded" for progress purposes — see
    # app/services/encoding_progress_service.py. NULL for an ordinary
    # graded (or not-yet-graded) row.
    statut = db.Column(db.Enum(GradeStatut), nullable=True)
    entered_by_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    is_validated = db.Column(db.Boolean, nullable=False, default=False)

    enrollment = db.relationship("Enrollment", back_populates="grades")
    grille_ligne = db.relationship("GrilleCoursLigne", back_populates="grades")
    period = db.relationship("EvaluationPeriod", back_populates="grades")
    entered_by = db.relationship("User")
    audit_logs = db.relationship("GradeAuditLog", back_populates="grade")

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Grade enrollment={self.enrollment_id} ligne={self.grille_cours_ligne_id} "
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
    grille_cours_ligne_id = db.Column(db.Integer, nullable=False)
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
