"""Student identity and yearly enrollment records."""

import enum
import uuid

from app.extensions import db
from app.models.mixins import SoftDeleteMixin, TimestampMixin
from app.models.tenant_scope import TenantScopedModel


class SexEnum(str, enum.Enum):
    M = "M"
    F = "F"


class EnrollmentStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"
    REPEATING = "REPEATING"


class Student(db.Model, TenantScopedModel, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "students"
    __table_args__ = (
        db.UniqueConstraint("ecole_id", "matricule", name="uq_student_ecole_matricule"),
    )

    id = db.Column(db.Integer, primary_key=True)
    # Globally unique, distinct from `matricule` (unique per école only).
    # Reserved for Phase 3 inter-school exchanges — never used to resolve a
    # tenant, never exposed in a URL today. See ARCHITECTURE_MULTITENANT.md.
    global_student_uid = db.Column(
        db.String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4())
    )
    matricule = db.Column(db.String(40), nullable=False, index=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    date_of_birth = db.Column(db.Date, nullable=True)
    sex = db.Column(db.Enum(SexEnum), nullable=True)

    enrollments = db.relationship("Enrollment", back_populates="student")

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Student {self.matricule}>"


class Enrollment(db.Model, TenantScopedModel, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "enrollments"
    __table_args__ = (
        db.UniqueConstraint(
            "ecole_id",
            "student_id",
            "academic_year_id",
            name="uq_enrollment_ecole_student_year",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(
        db.Integer, db.ForeignKey("students.id"), nullable=False, index=True
    )
    school_class_id = db.Column(
        db.Integer, db.ForeignKey("school_classes.id"), nullable=False, index=True
    )
    academic_year_id = db.Column(
        db.Integer, db.ForeignKey("academic_years.id"), nullable=False, index=True
    )
    enrollment_date = db.Column(db.Date, nullable=False)
    status = db.Column(
        db.Enum(EnrollmentStatus), nullable=False, default=EnrollmentStatus.ACTIVE
    )

    student = db.relationship("Student", back_populates="enrollments")
    school_class = db.relationship("SchoolClass", back_populates="enrollments")
    grades = db.relationship("Grade", back_populates="enrollment")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Enrollment student={self.student_id} class={self.school_class_id}>"
