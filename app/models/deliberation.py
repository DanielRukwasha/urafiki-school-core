"""Configurable pass/fail thresholds — never hard-coded in the calc engine.

A policy applies to a whole academic year by default; setting section_id
lets a school override the threshold for a specific section (e.g. a
scientific track requiring a higher average) without touching code.
"""

from app.extensions import db
from app.models.mixins import SoftDeleteMixin, TimestampMixin
from app.models.tenant_scope import TenantScopedModel


class DeliberationPolicy(db.Model, TenantScopedModel, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "deliberation_policies"
    __table_args__ = (
        db.CheckConstraint(
            "passing_threshold_percent >= 0 AND passing_threshold_percent <= 100",
            name="ck_policy_threshold_range",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    academic_year_id = db.Column(
        db.Integer, db.ForeignKey("academic_years.id"), nullable=False, index=True
    )
    section_id = db.Column(
        db.Integer, db.ForeignKey("sections.id"), nullable=True, index=True
    )
    passing_threshold_percent = db.Column(db.Numeric(5, 2), nullable=False)
    label = db.Column(db.String(150), nullable=True)

    academic_year = db.relationship(
        "AcademicYear", back_populates="deliberation_policies"
    )
    section = db.relationship("Section")

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<DeliberationPolicy year={self.academic_year_id} "
            f"section={self.section_id} threshold={self.passing_threshold_percent}>"
        )
