"""Assignment of a teacher (User with role ENSEIGNANT) to one grid line,
in one specific class.

`school_class_id` is explicit and required: a `GrilleCoursLigne` is
shared by every class of the same (section, niveau, academic_year), so
"this teacher teaches this subject" is ambiguous on its own — the
assignment must say in *which* class, since a different teacher may teach
the same subject in a sibling class of the same level.
"""

from app.extensions import db
from app.models.mixins import SoftDeleteMixin, TimestampMixin
from app.models.tenant_scope import TenantScopedModel


class TeacherAssignment(db.Model, TenantScopedModel, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "teacher_assignments"
    __table_args__ = (
        db.UniqueConstraint(
            "ecole_id",
            "teacher_id",
            "school_class_id",
            "grille_cours_ligne_id",
            name="uq_assignment_ecole_teacher_class_ligne",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    school_class_id = db.Column(
        db.Integer, db.ForeignKey("school_classes.id"), nullable=False, index=True
    )
    grille_cours_ligne_id = db.Column(
        db.Integer, db.ForeignKey("grille_cours_lignes.id"), nullable=False, index=True
    )

    teacher = db.relationship("User", back_populates="teacher_assignments")
    school_class = db.relationship("SchoolClass")
    grille_ligne = db.relationship("GrilleCoursLigne", back_populates="teacher_assignments")

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<TeacherAssignment teacher={self.teacher_id} class={self.school_class_id} "
            f"ligne={self.grille_cours_ligne_id}>"
        )
