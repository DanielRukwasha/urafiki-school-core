"""Resolution and duplication of a school's course grid — the single
source of truth both the encoding views and the bulletin/consolidation
engine read from. Nothing here ever names a level, section, or subject:
every value comes from the grid rows themselves.

Published signature summary (for the frontend):
    resoudre_grille(school_class, academic_year_id=None) -> GrilleCours
    lignes_actives(grille) -> list[GrilleCoursLigne]
    maximum_pour_periode(ligne, periode_id) -> Decimal
    dupliquer_grille(grille, *, academic_year_id, created_by) -> GrilleCours
"""

from __future__ import annotations

from app.extensions import db
from app.models.grille import (
    GrilleCours,
    GrilleCoursLigne,
    GrilleCoursLigneMaximum,
)


class GrilleConfigError(ValueError):
    """Raised when a school's grid configuration is too incomplete to
    encode or consolidate against safely — never silently guessed or
    defaulted."""


def resoudre_grille(school_class, academic_year_id: int | None = None) -> GrilleCours:
    """Resolve the one GrilleCours for a class's (section, niveau, year).

    Every class sharing that triple shares this same grid — it is never
    looked up or duplicated per class instance.
    """
    academic_year_id = academic_year_id or school_class.academic_year_id
    grille = (
        GrilleCours.query.filter_by(
            section_id=school_class.section_id,
            niveau_id=school_class.niveau_id,
            academic_year_id=academic_year_id,
        )
        .filter(GrilleCours.archived_at.is_(None))
        .first()
    )
    if grille is None:
        raise GrilleConfigError(
            f"Aucune grille de cours configurée pour la section {school_class.section_id}, "
            f"le niveau {school_class.niveau_id}, l'année {academic_year_id}."
        )
    return grille


def lignes_actives(grille: GrilleCours) -> list[GrilleCoursLigne]:
    """Active grid lines, in their configured display order."""
    return [
        ligne
        for ligne in grille.lignes
        if ligne.archived_at is None and ligne.groupe.archived_at is None
    ]


def maximum_pour_periode(ligne: GrilleCoursLigne, periode_id: int):
    """The configured maximum for one grid line, for one evaluation
    period. Raises GrilleConfigError rather than assuming a default —
    a school with a genuinely constant maximum still configures it once
    per period explicitly (see GrilleCoursLigneMaximum's docstring)."""
    maximum = GrilleCoursLigneMaximum.query.filter_by(
        grille_cours_ligne_id=ligne.id, periode_id=periode_id
    ).first()
    if maximum is None:
        raise GrilleConfigError(
            f"Aucun maximum configuré pour la ligne {ligne.id} en période {periode_id}."
        )
    return maximum.maximum


def grille_complete_pour_periode(grille: GrilleCours, periode_id: int) -> bool:
    """Whether every active, numeric line in this grid has a configured
    maximum for the given period — checked before opening encoding for a
    class/period (see app/services/authorization_service.py)."""
    for ligne in lignes_actives(grille):
        if ligne.note_par_appreciation:
            continue
        exists = GrilleCoursLigneMaximum.query.filter_by(
            grille_cours_ligne_id=ligne.id, periode_id=periode_id
        ).first()
        if exists is None:
            return False
    return True


def dupliquer_grille(
    grille: GrilleCours, *, academic_year_id: int, created_by=None
) -> GrilleCours:
    """Copy a grid forward to a new academic year: same sections/niveau,
    same lines (subject, weight, group, display order, grading mode).

    Per-period maxima are intentionally NOT copied — they are tied to
    the *specific* EvaluationPeriod rows of the source year, which have
    no meaning in the new year (a new year has its own period rows,
    configured independently). This also means a past year's grid and
    its bulletins stay reproducible exactly as published even after
    this duplication, since nothing about the source grid or its maxima
    is mutated — a new set of rows is created instead.
    """
    if (
        GrilleCours.query.filter_by(
            section_id=grille.section_id,
            niveau_id=grille.niveau_id,
            academic_year_id=academic_year_id,
        )
        .filter(GrilleCours.archived_at.is_(None))
        .first()
        is not None
    ):
        raise GrilleConfigError(
            f"Une grille existe déjà pour la section {grille.section_id}, "
            f"le niveau {grille.niveau_id}, l'année {academic_year_id}."
        )

    nouvelle_grille = GrilleCours(
        section_id=grille.section_id,
        niveau_id=grille.niveau_id,
        academic_year_id=academic_year_id,
    )
    db.session.add(nouvelle_grille)
    db.session.flush()

    for ligne in lignes_actives(grille):
        db.session.add(
            GrilleCoursLigne(
                grille_cours_id=nouvelle_grille.id,
                cours_id=ligne.cours_id,
                groupe_cours_id=ligne.groupe_cours_id,
                ordre_affichage=ligne.ordre_affichage,
                ponderation=ligne.ponderation,
                entre_dans_total_general=ligne.entre_dans_total_general,
                note_par_appreciation=ligne.note_par_appreciation,
            )
        )
    db.session.commit()
    return nouvelle_grille
