from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.grading import Grade, GradeAuditAction, GradeAuditLog
from app.services import audit_service


def test_duplicate_grade_for_same_course_and_period_is_rejected(
    db, enrollment, course, evaluation_period, make_user
):
    user, _ = make_user(email="teacher@example.com")
    audit_service.create_grade(
        enrollment_id=enrollment.id,
        course_id=course.id,
        period_id=evaluation_period.id,
        score=Decimal("15"),
        entered_by_id=user.id,
        ip_address="127.0.0.1",
    )
    db.session.commit()

    with pytest.raises(IntegrityError):
        audit_service.create_grade(
            enrollment_id=enrollment.id,
            course_id=course.id,
            period_id=evaluation_period.id,
            score=Decimal("12"),
            entered_by_id=user.id,
            ip_address="127.0.0.1",
        )
    db.session.rollback()


def test_negative_score_violates_check_constraint(
    db, enrollment, course, evaluation_period, make_user
):
    user, _ = make_user(email="teacher@example.com")
    grade = Grade(
        enrollment_id=enrollment.id,
        course_id=course.id,
        period_id=evaluation_period.id,
        score=Decimal("-5"),
        entered_by_id=user.id,
    )
    db.session.add(grade)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_create_grade_writes_audit_log(db, enrollment, course, evaluation_period, make_user):
    user, _ = make_user(email="teacher@example.com")
    grade = audit_service.create_grade(
        enrollment_id=enrollment.id,
        course_id=course.id,
        period_id=evaluation_period.id,
        score=Decimal("14"),
        entered_by_id=user.id,
        ip_address="10.0.0.5",
    )
    db.session.commit()

    logs = GradeAuditLog.query.filter_by(grade_id=grade.id).all()
    assert len(logs) == 1
    assert logs[0].action == GradeAuditAction.CREATE
    assert logs[0].old_value is None
    assert logs[0].new_value == Decimal("14")
    assert logs[0].ip_address == "10.0.0.5"


def test_update_grade_writes_audit_log_with_old_and_new_value(
    db, enrollment, course, evaluation_period, make_user
):
    user, _ = make_user(email="teacher@example.com")
    grade = audit_service.create_grade(
        enrollment_id=enrollment.id,
        course_id=course.id,
        period_id=evaluation_period.id,
        score=Decimal("10"),
        entered_by_id=user.id,
        ip_address="10.0.0.5",
    )
    db.session.commit()

    audit_service.update_grade_score(
        grade=grade, new_score=Decimal("17"), user_id=user.id, ip_address="10.0.0.6"
    )
    db.session.commit()

    logs = (
        GradeAuditLog.query.filter_by(grade_id=grade.id)
        .order_by(GradeAuditLog.id)
        .all()
    )
    assert len(logs) == 2
    update_log = logs[1]
    assert update_log.action == GradeAuditAction.UPDATE
    assert update_log.old_value == Decimal("10")
    assert update_log.new_value == Decimal("17")


def test_delete_grade_keeps_audit_log_with_snapshot(
    db, enrollment, course, evaluation_period, make_user
):
    user, _ = make_user(email="teacher@example.com")
    grade = audit_service.create_grade(
        enrollment_id=enrollment.id,
        course_id=course.id,
        period_id=evaluation_period.id,
        score=Decimal("8"),
        entered_by_id=user.id,
        ip_address="10.0.0.5",
    )
    db.session.commit()
    grade_id = grade.id

    audit_service.delete_grade(grade=grade, user_id=user.id, ip_address="10.0.0.7")
    db.session.commit()

    assert db.session.get(Grade, grade_id) is None
    logs = GradeAuditLog.query.filter_by(
        enrollment_id=enrollment.id, course_id=course.id, period_id=evaluation_period.id
    ).all()
    assert any(log.action == GradeAuditAction.DELETE for log in logs)
    delete_log = next(log for log in logs if log.action == GradeAuditAction.DELETE)
    assert delete_log.grade_id is None
    assert delete_log.old_value == Decimal("8")
