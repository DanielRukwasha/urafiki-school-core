"""Student identity and yearly enrollment records."""

import enum

from app.extensions import db
from app.models.mixins import SoftDeleteMixin, TimestampMixin


class SexEnum(str, enum.Enum):
    M = "M"
    F = "F"


class EnrollmentStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"
    REPEATING = "REPEATING"


class Student(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "students"

    id = db.Column(db.Integer, primary_key=True)
    matricule = db.Column(db.String(40), nullable=False, unique=True, index=True)
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


class Enrollment(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "enrollments"
    __table_args__ = (
        db.UniqueConstraint(
            "student_id", "academic_year_id", name="uq_enrollment_student_year"
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
