"""Course: a subject in the school's catalog — e.g. "Mathématiques".

No longer tied to a single class, and carries no weight or maximum of its
own: the same subject can appear in several grids (different levels) with
a different weight, grouping, and per-period maximum in each — all of
that lives on `GrilleCoursLigne`/`GrilleCoursLigneMaximum` instead. A
subject exists once per school regardless of how many grids reference it.
"""

from app.extensions import db
from app.models.mixins import SoftDeleteMixin, TimestampMixin
from app.models.tenant_scope import TenantScopedModel


class Course(db.Model, TenantScopedModel, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "courses"
    __table_args__ = (
        db.UniqueConstraint("ecole_id", "code", name="uq_course_ecole_code"),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    code = db.Column(db.String(30), nullable=False)

    grille_lignes = db.relationship("GrilleCoursLigne", back_populates="cours")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Course {self.code}>"
