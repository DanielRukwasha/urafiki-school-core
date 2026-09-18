"""Records an immutable GradeAuditLog entry for every grade mutation.

Kept separate from the calculation engine and from route handlers so that
every code path which creates, updates, or deletes a Grade goes through the
same auditing guarantee.
"""

from __future__ import annotations

from decimal import Decimal

from app.extensions import db
from app.models.grading import Grade, GradeAuditAction, GradeAuditLog, GradeStatut


class InvalidGradeContentError(ValueError):
    """Raised when a grade's score/appreciation/statut combination violates
    the "exactly one of score or appreciation, or a statut instead of
    either" rule — checked here in service so a clear message can be
    raised before the database's CHECK constraint would (that constraint
    is a safety net, not the primary validation path)."""


def _validate_content(
    score: Decimal | None, appreciation: str | None, statut: GradeStatut | None
) -> None:
    if statut is not None:
        if score is not None or appreciation is not None:
            raise InvalidGradeContentError(
                "Une cote avec un statut (absence justifiée, dispense) ne peut "
                "porter ni note ni appréciation."
            )
        return
    if score is not None and appreciation is not None:
        raise InvalidGradeContentError(
            "Une cote ne peut être à la fois une note chiffrée et une appréciation."
        )


def record_grade_change(
    *,
    grade: Grade,
    action: GradeAuditAction,
    user_id: int,
    ip_address: str | None,
    old_value: Decimal | None,
    new_value: Decimal | None,
) -> GradeAuditLog:
    entry = GradeAuditLog(
        ecole_id=grade.ecole_id,
        grade_id=grade.id,
        enrollment_id=grade.enrollment_id,
        grille_cours_ligne_id=grade.grille_cours_ligne_id,
        period_id=grade.period_id,
        action=action,
        old_value=old_value,
        new_value=new_value,
        user_id=user_id,
        ip_address=ip_address,
    )
    db.session.add(entry)
    return entry


def create_grade(
    *,
    ecole_id: int,
    enrollment_id: int,
    grille_cours_ligne_id: int,
    period_id: int,
    entered_by_id: int,
    ip_address: str | None,
    score: Decimal | None = None,
    appreciation: str | None = None,
    statut: GradeStatut | None = None,
) -> Grade:
    _validate_content(score, appreciation, statut)
    grade = Grade(
        ecole_id=ecole_id,
        enrollment_id=enrollment_id,
        grille_cours_ligne_id=grille_cours_ligne_id,
        period_id=period_id,
        score=score,
        appreciation=appreciation,
        statut=statut,
        entered_by_id=entered_by_id,
    )
    db.session.add(grade)
    db.session.flush()  # assign grade.id before the audit row references it
    record_grade_change(
        grade=grade,
        action=GradeAuditAction.CREATE,
        user_id=entered_by_id,
        ip_address=ip_address,
        old_value=None,
        new_value=score,
    )
    return grade


def update_grade_content(
    *,
    grade: Grade,
    user_id: int,
    ip_address: str | None,
    score: Decimal | None = None,
    appreciation: str | None = None,
    statut: GradeStatut | None = None,
) -> Grade:
    _validate_content(score, appreciation, statut)
    old_value = grade.score
    grade.score = score
    grade.appreciation = appreciation
    grade.statut = statut
    record_grade_change(
        grade=grade,
        action=GradeAuditAction.UPDATE,
        user_id=user_id,
        ip_address=ip_address,
        old_value=old_value,
        new_value=score,
    )
    return grade


def delete_grade(*, grade: Grade, user_id: int, ip_address: str | None) -> None:
    record_grade_change(
        grade=grade,
        action=GradeAuditAction.DELETE,
        user_id=user_id,
        ip_address=ip_address,
        old_value=grade.score,
        new_value=None,
    )
    db.session.flush()
    db.session.delete(grade)
