"""Assignment of a teacher (User with role ENSEIGNANT) to a course."""

from app.extensions import db
from app.models.mixins import SoftDeleteMixin, TimestampMixin
from app.models.tenant_scope import TenantScopedModel


class TeacherAssignment(db.Model, TenantScopedModel, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "teacher_assignments"
    __table_args__ = (
        db.UniqueConstraint(
            "ecole_id",
            "teacher_id",
            "course_id",
            name="uq_assignment_ecole_teacher_course",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    course_id = db.Column(
        db.Integer, db.ForeignKey("courses.id"), nullable=False, index=True
    )

    teacher = db.relationship("User", back_populates="teacher_assignments")
    course = db.relationship("Course", back_populates="teacher_assignments")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TeacherAssignment teacher={self.teacher_id} course={self.course_id}>"
