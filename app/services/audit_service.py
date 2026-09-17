"""Records an immutable GradeAuditLog entry for every grade mutation.

Kept separate from the calculation engine and from route handlers so that
every code path which creates, updates, or deletes a Grade goes through the
same auditing guarantee.
"""

from __future__ import annotations

from decimal import Decimal

from app.extensions import db
from app.models.grading import Grade, GradeAuditAction, GradeAuditLog


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
        course_id=grade.course_id,
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
    course_id: int,
    period_id: int,
    score: Decimal,
    entered_by_id: int,
    ip_address: str | None,
) -> Grade:
    grade = Grade(
        ecole_id=ecole_id,
        enrollment_id=enrollment_id,
        course_id=course_id,
        period_id=period_id,
        score=score,
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


def update_grade_score(
    *,
    grade: Grade,
    new_score: Decimal,
    user_id: int,
    ip_address: str | None,
) -> Grade:
    old_value = grade.score
    grade.score = new_score
    record_grade_change(
        grade=grade,
        action=GradeAuditAction.UPDATE,
        user_id=user_id,
        ip_address=ip_address,
        old_value=old_value,
        new_value=new_score,
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
