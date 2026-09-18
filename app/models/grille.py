"""The course grid referential — a school's list of subjects per (section,
level, academic year), with weight, grouping, per-period maxima, and
grading mode (numeric vs. appreciation) all stored as data. The engine
that consumes this (app/services/grade_calculation_engine.py) never knows
what any level or section is actually called; it only reads the
`entre_dans_total_general`/`note_par_appreciation` flags and numeric
values below.

A grid belongs to one academic year and is never edited across a year
boundary in place — `dupliquer_grille` (app/services/grille_service.py)
copies one forward instead, so an already-published bulletin from a past
year stays reproducible exactly as it was, even after this year's grid
changes.
"""

from __future__ import annotations

from app.extensions import db
from app.models.mixins import SoftDeleteMixin, TimestampMixin
from app.models.tenant_scope import TenantScopedModel


class Niveau(db.Model, TenantScopedModel, TimestampMixin, SoftDeleteMixin):
    """A study level (grade/form) — distinct from `Section` (track). Fully
    tenant-configurable: no level name is ever hard-coded anywhere."""

    __tablename__ = "niveaux"
    __table_args__ = (
        db.UniqueConstraint("ecole_id", "libelle", name="uq_niveau_ecole_libelle"),
    )

    id = db.Column(db.Integer, primary_key=True)
    libelle = db.Column(db.String(100), nullable=False)
    ordre_affichage = db.Column(db.Integer, nullable=False, default=0)

    school_classes = db.relationship("SchoolClass", back_populates="niveau")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Niveau {self.libelle}>"


class GroupeCours(db.Model, TenantScopedModel, TimestampMixin, SoftDeleteMixin):
    """A course "branch" (e.g. a subject cluster) — may exist with no
    course lines yet. `entre_dans_total_general` here is combined with the
    same flag on each `GrilleCoursLigne`: a group excluded from the
    general total excludes every one of its lines regardless of how each
    line is individually flagged."""

    __tablename__ = "groupes_cours"
    __table_args__ = (
        db.UniqueConstraint("ecole_id", "libelle", name="uq_groupe_cours_ecole_libelle"),
    )

    id = db.Column(db.Integer, primary_key=True)
    libelle = db.Column(db.String(150), nullable=False)
    ordre_affichage = db.Column(db.Integer, nullable=False, default=0)
    affiche_sous_total = db.Column(db.Boolean, nullable=False, default=True)
    entre_dans_total_general = db.Column(db.Boolean, nullable=False, default=True)

    lignes = db.relationship("GrilleCoursLigne", back_populates="groupe")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<GroupeCours {self.libelle}>"


class GrilleCours(db.Model, TenantScopedModel, TimestampMixin, SoftDeleteMixin):
    """One school's course grid for one (section, level, academic year).
    Shared by every `SchoolClass` with that same (section, niveau,
    academic_year) — a grid is never duplicated per class instance, so
    the encoding grid and the bulletin can never diverge (see the module
    docstring's "single source of truth" rule)."""

    __tablename__ = "grilles_cours"
    __table_args__ = (
        db.UniqueConstraint(
            "ecole_id",
            "section_id",
            "niveau_id",
            "academic_year_id",
            name="uq_grille_ecole_section_niveau_annee",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    section_id = db.Column(db.Integer, db.ForeignKey("sections.id"), nullable=False, index=True)
    niveau_id = db.Column(db.Integer, db.ForeignKey("niveaux.id"), nullable=False, index=True)
    academic_year_id = db.Column(
        db.Integer, db.ForeignKey("academic_years.id"), nullable=False, index=True
    )

    section = db.relationship("Section")
    niveau = db.relationship("Niveau")
    academic_year = db.relationship("AcademicYear")
    lignes = db.relationship(
        "GrilleCoursLigne", back_populates="grille", order_by="GrilleCoursLigne.ordre_affichage"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<GrilleCours section={self.section_id} niveau={self.niveau_id} annee={self.academic_year_id}>"


class GrilleCoursLigne(db.Model, TenantScopedModel, TimestampMixin, SoftDeleteMixin):
    """One subject's place in a grid: its weight, group, display order,
    and whether it's graded numerically or by appreciation. Carries what
    `Course.coefficient` used to carry — since the same subject can weigh
    differently in different grids, the weight cannot live on `Course`
    itself anymore."""

    __tablename__ = "grille_cours_lignes"
    __table_args__ = (
        db.UniqueConstraint(
            "ecole_id", "grille_cours_id", "cours_id", name="uq_ligne_ecole_grille_cours"
        ),
        db.CheckConstraint("ponderation > 0", name="ck_ligne_ponderation_positive"),
    )

    id = db.Column(db.Integer, primary_key=True)
    grille_cours_id = db.Column(
        db.Integer, db.ForeignKey("grilles_cours.id"), nullable=False, index=True
    )
    cours_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False, index=True)
    groupe_cours_id = db.Column(
        db.Integer, db.ForeignKey("groupes_cours.id"), nullable=False, index=True
    )
    ordre_affichage = db.Column(db.Integer, nullable=False, default=0)
    ponderation = db.Column(db.Numeric(6, 3), nullable=False)
    entre_dans_total_general = db.Column(db.Boolean, nullable=False, default=True)
    note_par_appreciation = db.Column(db.Boolean, nullable=False, default=False)

    grille = db.relationship("GrilleCours", back_populates="lignes")
    cours = db.relationship("Course", back_populates="grille_lignes")
    groupe = db.relationship("GroupeCours", back_populates="lignes")
    maxima = db.relationship(
        "GrilleCoursLigneMaximum", back_populates="ligne", cascade="all, delete-orphan"
    )
    teacher_assignments = db.relationship("TeacherAssignment", back_populates="grille_ligne")
    grades = db.relationship("Grade", back_populates="grille_ligne")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<GrilleCoursLigne grille={self.grille_cours_id} cours={self.cours_id}>"


class GrilleCoursLigneMaximum(db.Model, TenantScopedModel, TimestampMixin):
    """The maximum score for one grid line, for one evaluation period —
    never a single maximum per course. A school with a constant maximum
    simply repeats the same value per period; the reverse (starting with
    one constant maximum, then needing it to vary) would be unrecoverable
    later without migrating every already-entered grade and consolidated
    bulletin, so this is modeled correctly from the start."""

    __tablename__ = "grille_cours_ligne_maxima"
    __table_args__ = (
        db.UniqueConstraint(
            "ecole_id",
            "grille_cours_ligne_id",
            "periode_id",
            name="uq_maximum_ecole_ligne_periode",
        ),
        db.CheckConstraint("maximum > 0", name="ck_maximum_positive"),
    )

    id = db.Column(db.Integer, primary_key=True)
    grille_cours_ligne_id = db.Column(
        db.Integer, db.ForeignKey("grille_cours_lignes.id"), nullable=False, index=True
    )
    periode_id = db.Column(
        db.Integer, db.ForeignKey("evaluation_periods.id"), nullable=False, index=True
    )
    maximum = db.Column(db.Numeric(6, 2), nullable=False)

    ligne = db.relationship("GrilleCoursLigne", back_populates="maxima")
    periode = db.relationship("EvaluationPeriod")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<GrilleCoursLigneMaximum ligne={self.grille_cours_ligne_id} periode={self.periode_id}>"
