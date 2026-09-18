"""Academic structure: years, sections, classes and evaluation periods.

Weights and calendars are configuration, stored in these rows — never
hard-coded — so each period's contribution to the annual total can differ
per deployment and per year.
"""

from app.extensions import db
from app.models.mixins import SoftDeleteMixin, TimestampMixin
from app.models.tenant_scope import TenantScopedModel


class AcademicYear(db.Model, TenantScopedModel, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "academic_years"
    __table_args__ = (
        db.UniqueConstraint("ecole_id", "label", name="uq_academic_year_ecole_label"),
    )

    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.String(20), nullable=False)  # e.g. "2025-2026"
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    is_current = db.Column(db.Boolean, nullable=False, default=False)

    school_classes = db.relationship("SchoolClass", back_populates="academic_year")
    evaluation_periods = db.relationship(
        "EvaluationPeriod",
        back_populates="academic_year",
        order_by="EvaluationPeriod.sequence_order",
    )
    deliberation_policies = db.relationship(
        "DeliberationPolicy", back_populates="academic_year"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AcademicYear {self.label}>"


class Section(db.Model, TenantScopedModel, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "sections"
    __table_args__ = (
        db.UniqueConstraint("ecole_id", "code", name="uq_section_ecole_code"),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(20), nullable=False)
    description = db.Column(db.String(300), nullable=True)

    school_classes = db.relationship("SchoolClass", back_populates="section")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Section {self.code}>"


class SchoolClass(db.Model, TenantScopedModel, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "school_classes"
    __table_args__ = (
        db.UniqueConstraint(
            "ecole_id", "academic_year_id", "name", name="uq_class_ecole_year_name"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    academic_year_id = db.Column(
        db.Integer, db.ForeignKey("academic_years.id"), nullable=False, index=True
    )
    section_id = db.Column(
        db.Integer, db.ForeignKey("sections.id"), nullable=False, index=True
    )
    name = db.Column(db.String(100), nullable=False)  # e.g. "6ème A"
    level_order = db.Column(db.Integer, nullable=False, default=0)

    academic_year = db.relationship("AcademicYear", back_populates="school_classes")
    section = db.relationship("Section", back_populates="school_classes")
    courses = db.relationship("Course", back_populates="school_class")
    enrollments = db.relationship("Enrollment", back_populates="school_class")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SchoolClass {self.name}>"


class EvaluationPeriod(db.Model, TenantScopedModel, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "evaluation_periods"
    __table_args__ = (
        db.UniqueConstraint(
            "ecole_id",
            "academic_year_id",
            "sequence_order",
            name="uq_period_ecole_year_sequence",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    academic_year_id = db.Column(
        db.Integer, db.ForeignKey("academic_years.id"), nullable=False, index=True
    )
    name = db.Column(db.String(100), nullable=False)  # e.g. "1er Trimestre"
    sequence_order = db.Column(db.Integer, nullable=False)
    weight_percent = db.Column(db.Numeric(6, 3), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)

    academic_year = db.relationship(
        "AcademicYear", back_populates="evaluation_periods"
    )
    grades = db.relationship("Grade", back_populates="period")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<EvaluationPeriod {self.name}>"
