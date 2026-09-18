"""Course: a subject taught within one school class, with its own coefficient
and maximum score — both configuration, never hard-coded.
"""

from app.extensions import db
from app.models.mixins import SoftDeleteMixin, TimestampMixin
from app.models.tenant_scope import TenantScopedModel


class Course(db.Model, TenantScopedModel, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "courses"
    __table_args__ = (
        db.UniqueConstraint(
            "ecole_id", "school_class_id", "code", name="uq_course_ecole_class_code"
        ),
        db.CheckConstraint("max_score > 0", name="ck_course_max_score_positive"),
        db.CheckConstraint("coefficient > 0", name="ck_course_coefficient_positive"),
    )

    id = db.Column(db.Integer, primary_key=True)
    school_class_id = db.Column(
        db.Integer, db.ForeignKey("school_classes.id"), nullable=False, index=True
    )
    name = db.Column(db.String(150), nullable=False)
    code = db.Column(db.String(30), nullable=False)
    coefficient = db.Column(db.Numeric(6, 3), nullable=False)
    max_score = db.Column(db.Numeric(6, 2), nullable=False)

    school_class = db.relationship("SchoolClass", back_populates="courses")
    teacher_assignments = db.relationship(
        "TeacherAssignment", back_populates="course"
    )
    grades = db.relationship("Grade", back_populates="course")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Course {self.code} ({self.school_class_id})>"
