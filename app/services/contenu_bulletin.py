"""Contenu calculé d'un bulletin de classe/période, et son gel par version
(invariants 3, 8 et 9).

Un bulletin n'est jamais saisi : il est calculé depuis la grille, les
maxima de la période, les cotes et la présentation de l'établissement.
Ce module produit ce calcul sous une forme unique, sérialisable et
autonome — le « contenu » — utilisée dans les deux cas :

- **période non publiée** : le contenu est recalculé à chaque lecture
  depuis les tables vivantes (aperçu, préparation de la délibération) ;
- **période publiée** : le contenu a été figé dans `BulletinVersion` au
  moment de la publication ou de la correction, avec son empreinte
  SHA-256. Toute lecture d'une version publiée relit ce contenu, jamais
  les tables vivantes : modifier ensuite un maximum, un libellé, une cote
  ou l'en-tête de l'établissement ne change pas la version 1.

Le même chemin (`contexte_depuis_contenu`) rend l'aperçu et la version
publiée : ce que la direction a validé est exactement ce qui est figé.

Limite assumée : le logo est figé par son URL, pas par ses octets.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace

from app.models.student import Enrollment, EnrollmentStatus, Student
from app.services.grade_calculation_engine import (
    CourseBreakdown,
    CourseGradeInput,
    PeriodResult,
    compute_period_total,
    quantize_percentage,
    rank_students,
)
from app.services.grille_service import lignes_actives, maximum_pour_periode, resoudre_grille

SCHEMA_CONTENU = 1


class ContenuBulletinError(RuntimeError):
    """Une version publiée dont le contenu est absent ou altéré. Jamais
    remplacée par un recalcul silencieux depuis les tables vivantes."""


@dataclass(frozen=True)
class CourseColumn:
    """A grid line, adapted for the grade grid/report templates — `id` is
    the `GrilleCoursLigne.id` a `Grade` actually references. `max_score`
    is the maximum configured for the period this column was built for
    (None for an appreciation line, which has no numeric maximum).
    `included` combines the line's and its group's
    `entre_dans_total_general` flags, exactly as the consolidation does."""

    id: int
    code: str
    name: str
    coefficient: Decimal
    max_score: Decimal | None
    is_appreciation: bool
    groupe_id: int
    included: bool = True


def colonnes_grille(klass, period=None) -> list[CourseColumn]:
    """Every active column of the class's grid, in display order. Raises
    GrilleConfigError if the class has no grid, or a numeric line has no
    maximum for the period — never silently an empty grid or a default."""
    columns = []
    for ligne in lignes_actives(resoudre_grille(klass)):
        max_score = None
        if not ligne.note_par_appreciation and period is not None:
            max_score = maximum_pour_periode(ligne, period.id)
        columns.append(
            CourseColumn(
                id=ligne.id,
                code=ligne.cours.code,
                name=ligne.cours.name,
                coefficient=ligne.ponderation,
                max_score=max_score,
                is_appreciation=ligne.note_par_appreciation,
                groupe_id=ligne.groupe_cours_id,
                included=ligne.entre_dans_total_general and ligne.groupe.entre_dans_total_general,
            )
        )
    return columns


def inscriptions_actives(klass) -> list[Enrollment]:
    """The class's current, non-withdrawn, non-archived enrollments, by name."""
    return (
        Enrollment.query.join(Student)
        .filter(
            Enrollment.archived_at.is_(None),
            Enrollment.school_class_id == klass.id,
            Enrollment.academic_year_id == klass.academic_year_id,
            Enrollment.status != EnrollmentStatus.WITHDRAWN,
            Student.archived_at.is_(None),
        )
        .order_by(Student.last_name, Student.first_name)
        .all()
    )


def _decimal(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def calculer_contenu(klass, period, presentation: dict) -> dict:
    """The class/period bulletin, computed now from the live tables, for
    every active grid line and enrollment. `presentation` is
    `{"branding": ..., "report": ...}` (see
    `app.tenant_presentation.presentation_configuration`). Every Decimal
    is kept as its exact string so the frozen value round-trips bit for
    bit."""
    from app.models.grading import Grade

    columns = colonnes_grille(klass, period)
    enrollments = inscriptions_actives(klass)
    grades = {
        (g.enrollment_id, g.grille_cours_ligne_id): g
        for g in Grade.query.filter(
            Grade.enrollment_id.in_([e.id for e in enrollments]),
            Grade.grille_cours_ligne_id.in_([c.id for c in columns]),
            Grade.period_id == period.id,
            Grade.archived_at.is_(None),
        ).all()
    }

    rows = []
    for enrollment in enrollments:
        inputs = [
            CourseGradeInput(
                ligne_id=c.id,
                groupe_id=c.groupe_id,
                coefficient=c.coefficient,
                max_score=c.max_score,
                score=grades[(enrollment.id, c.id)].score if (enrollment.id, c.id) in grades else None,
                appreciation=grades[(enrollment.id, c.id)].appreciation
                if (enrollment.id, c.id) in grades
                else None,
                included=c.included,
                is_numeric=not c.is_appreciation,
            )
            for c in columns
        ]
        total = compute_period_total(period.id, inputs)
        rows.append((enrollment, inputs, total))

    ranks = {
        r.enrollment_id: r.rank
        for r in rank_students([(e.id, total.percentage) for e, _, total in rows])
    }
    unranked = len(rows) + 1
    rows.sort(key=lambda row: (ranks.get(row[0].id, unranked), row[0].student.last_name))

    return {
        "schema": SCHEMA_CONTENU,
        "classe": {
            "id": klass.id,
            "nom": klass.name,
            "annee": klass.academic_year.label,
        },
        "periode": {"id": period.id, "nom": period.name},
        "colonnes": [
            {
                "id": c.id,
                "code": c.code,
                "nom": c.name,
                "ponderation": _decimal(c.coefficient),
                "maximum": _decimal(c.max_score),
                "appreciation": c.is_appreciation,
                "groupe_id": c.groupe_id,
                "inclus": c.included,
            }
            for c in columns
        ],
        "eleves": [
            {
                "inscription_id": enrollment.id,
                "nom_complet": enrollment.student.full_name,
                "matricule": enrollment.student.matricule,
                "rang": ranks.get(enrollment.id),
                "cotes_saisies": sum(i.score is not None for i in inputs),
                "cotes": {
                    str(i.ligne_id): {"cote": _decimal(i.score), "appreciation": i.appreciation}
                    for i in inputs
                    if i.score is not None or i.appreciation is not None
                },
                "total": {
                    "points": _decimal(total.weighted_points),
                    "possible": _decimal(total.weighted_possible),
                    "pourcentage": _decimal(total.percentage),
                    "pourcentage_affiche": _decimal(
                        quantize_percentage(total.percentage)
                        if total.percentage is not None
                        else None
                    ),
                    "detail": [
                        {
                            "ligne_id": b.ligne_id,
                            "groupe_id": b.groupe_id,
                            "points": _decimal(b.weighted_points),
                            "possible": _decimal(b.weighted_possible),
                            "inclus": b.included,
                        }
                        for b in total.course_breakdown
                    ],
                },
            }
            for enrollment, inputs, total in rows
        ],
        "presentation": presentation,
    }


def serialiser(contenu: dict) -> tuple[str, str]:
    """Canonical JSON text and its SHA-256: the stored bytes are the
    fingerprinted bytes, so the fingerprint proves the stored document."""
    texte = json.dumps(contenu, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return texte, hashlib.sha256(texte.encode("utf-8")).hexdigest()


def contenu_de_version(version) -> dict:
    """The frozen content of a published version, after checking its
    fingerprint. Raises ContenuBulletinError for a version published
    before content freezing (migration d7e2b4c1a9f3) or whose stored
    content no longer matches its fingerprint."""
    if version.contenu is None or version.empreinte is None:
        raise ContenuBulletinError(
            f"La version {version.numero} a été publiée avant le gel du contenu des "
            "bulletins : son contenu d'origine n'est pas conservé. Publier une "
            "correction motivée pour figer un contenu vérifiable."
        )
    if hashlib.sha256(version.contenu.encode("utf-8")).hexdigest() != version.empreinte:
        raise ContenuBulletinError(
            f"Version {version.numero} : le contenu stocké ne correspond plus à son "
            "empreinte. Lecture refusée."
        )
    return json.loads(version.contenu)


def _dec(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def contexte_depuis_contenu(contenu: dict) -> dict:
    """The template context (klass, period, courses, enrollments, grades,
    rows, ranks) rebuilt from a content dict — identical in shape for a
    live preview and a frozen version, so templates cannot tell them
    apart and no value is ever re-read from the live tables."""
    if contenu.get("schema") != SCHEMA_CONTENU:
        raise ContenuBulletinError(f"Schéma de contenu inconnu : {contenu.get('schema')!r}.")
    classe = contenu["classe"]
    klass = SimpleNamespace(
        id=classe["id"], name=classe["nom"], academic_year=SimpleNamespace(label=classe["annee"])
    )
    period = SimpleNamespace(id=contenu["periode"]["id"], name=contenu["periode"]["nom"])
    courses = [
        CourseColumn(
            id=c["id"],
            code=c["code"],
            name=c["nom"],
            coefficient=_dec(c["ponderation"]),
            max_score=_dec(c["maximum"]),
            is_appreciation=c["appreciation"],
            groupe_id=c["groupe_id"],
            included=c["inclus"],
        )
        for c in contenu["colonnes"]
    ]
    enrollments, grades, rows, ranks = [], {}, [], {}
    for eleve in contenu["eleves"]:
        enrollment = SimpleNamespace(
            id=eleve["inscription_id"],
            student=SimpleNamespace(full_name=eleve["nom_complet"], matricule=eleve["matricule"]),
        )
        enrollments.append(enrollment)
        for ligne_id, cote in eleve["cotes"].items():
            grades[(enrollment.id, int(ligne_id))] = SimpleNamespace(
                score=_dec(cote["cote"]), appreciation=cote["appreciation"]
            )
        total = eleve["total"]
        rows.append(
            dict(
                enrollment=enrollment,
                total=PeriodResult(
                    period_id=period.id,
                    weighted_points=_dec(total["points"]),
                    weighted_possible=_dec(total["possible"]),
                    percentage=_dec(total["pourcentage"]),
                    course_breakdown=tuple(
                        CourseBreakdown(
                            ligne_id=b["ligne_id"],
                            groupe_id=b["groupe_id"],
                            weighted_points=_dec(b["points"]),
                            weighted_possible=_dec(b["possible"]),
                            included=b["inclus"],
                        )
                        for b in total["detail"]
                    ),
                ),
                entered=eleve["cotes_saisies"],
                percentage=_dec(total["pourcentage_affiche"]),
            )
        )
        if eleve["rang"] is not None:
            ranks[enrollment.id] = eleve["rang"]
    return dict(
        klass=klass,
        period=period,
        courses=courses,
        enrollments=enrollments,
        grades=grades,
        rows=rows,
        ranks=ranks,
    )
