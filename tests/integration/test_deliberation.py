"""Server-owned consolidation, deliberation, override and publication
workflow — issue #42's backend contract, consumed by the portal views
built in PR #44 (app/ui/consolidation.py, portal/consolidation.html,
portal/deliberation.html, portal/override_decision.html)."""

import datetime
from decimal import Decimal

import pytest

from app.models.deliberation import DeliberationPolicy
from app.models.deliberation_workflow import (
    DeliberationAuditLog,
    DeliberationOverride,
    PeriodPublication,
)
from app.models.grading import Grade
from app.models.student import Enrollment, Student
from app.models.user import RoleEnum


def login(client, email, password):
    return client.post("/auth/login", data={"email": email, "password": password})


@pytest.fixture()
def deliberation_policy(db, tenant_a, academic_year):
    policy = DeliberationPolicy(
        ecole_id=tenant_a.id, academic_year_id=academic_year.id, passing_threshold_percent=Decimal("50")
    )
    db.session.add(policy)
    db.session.commit()
    return policy


@pytest.fixture()
def second_course(db, tenant_a, school_class):
    from app.models.course import Course

    c = Course(
        ecole_id=tenant_a.id,
        school_class_id=school_class.id,
        name="Éducation physique",
        code="EPS",
        coefficient=Decimal("1"),
        max_score=Decimal("20"),
    )
    db.session.add(c)
    db.session.commit()
    return c


def _extra_student(db, tenant_a, school_class, academic_year, n):
    student = Student(
        ecole_id=tenant_a.id, matricule=f"IMC-{n:04}", first_name=f"Eleve{n}", last_name="Test"
    )
    db.session.add(student)
    db.session.flush()
    enrollment = Enrollment(
        ecole_id=tenant_a.id,
        student_id=student.id,
        school_class_id=school_class.id,
        academic_year_id=academic_year.id,
        enrollment_date=datetime.date(2025, 9, 1),
    )
    db.session.add(enrollment)
    db.session.commit()
    return enrollment


def _grade(db, enrollment, course, period, score, user):
    db.session.add(
        Grade(
            ecole_id=enrollment.ecole_id,
            enrollment_id=enrollment.id,
            course_id=course.id,
            period_id=period.id,
            score=Decimal(str(score)),
            entered_by_id=user.id,
        )
    )
    db.session.commit()


def test_consolidation_requires_a_deliberation_policy(
    client, db, make_user, school_class, evaluation_period
):
    user, password = make_user(role=RoleEnum.DIRECTION)
    login(client, user.email, password)
    response = client.get(
        f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}/consolidation"
    )
    assert response.status_code == 503


def test_consolidation_flags_incomplete_course_as_blocking(
    client, db, make_user, deliberation_policy, school_class, evaluation_period, course, enrollment
):
    user, password = make_user(role=RoleEnum.DIRECTION)
    login(client, user.email, password)
    response = client.get(
        f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}/consolidation"
    )
    assert response.status_code == 200
    assert b"Consolidation bloqu\xc3\xa9e" in response.data
    assert b"0 / 1" in response.data


def test_automatic_decision_admitted_above_threshold(
    client, db, make_user, deliberation_policy, school_class, evaluation_period, course, enrollment
):
    user, password = make_user(role=RoleEnum.DIRECTION)
    _grade(db, enrollment, course, evaluation_period, "16", user)
    login(client, user.email, password)
    response = client.get(
        f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}/deliberation"
    )
    assert response.status_code == 200
    assert b"decision-ADMITTED" in response.data


def test_automatic_decision_deferred_below_threshold(
    client, db, make_user, deliberation_policy, school_class, evaluation_period, course, enrollment
):
    user, password = make_user(role=RoleEnum.DIRECTION)
    _grade(db, enrollment, course, evaluation_period, "5", user)
    login(client, user.email, password)
    response = client.get(
        f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}/deliberation"
    )
    assert b"decision-DEFERRED" in response.data
    assert "inférieure au seuil".encode() in response.data


def test_automatic_decision_manual_when_no_grades_entered(
    client, db, make_user, deliberation_policy, school_class, evaluation_period, course, enrollment
):
    user, password = make_user(role=RoleEnum.DIRECTION)
    login(client, user.email, password)
    response = client.get(
        f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}/deliberation"
    )
    assert b"decision-MANUAL" in response.data


def test_eliminatory_course_failure_defers_despite_passing_average(
    client,
    db,
    tenant_a,
    make_user,
    deliberation_policy,
    school_class,
    evaluation_period,
    course,
    second_course,
    enrollment,
):
    from app.models.tenant_config import TenantConfig

    TenantConfig.query.execution_options(skip_tenant_filter=True).filter_by(ecole_id=tenant_a.id).first().eliminatory_course_codes = ["EPS"]
    db.session.commit()

    user, password = make_user(role=RoleEnum.DIRECTION)
    _grade(db, enrollment, course, evaluation_period, "18", user)  # strong in MATH
    _grade(db, enrollment, second_course, evaluation_period, "2", user)  # fails EPS, eliminatory

    login(client, user.email, password)
    response = client.get(
        f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}/deliberation"
    )
    assert b"decision-DEFERRED" in response.data
    assert "Cours éliminatoire en échec".encode() in response.data


def test_override_requires_a_real_reason(
    client, db, make_user, deliberation_policy, school_class, evaluation_period, course, enrollment
):
    user, password = make_user(role=RoleEnum.DIRECTION)
    _grade(db, enrollment, course, evaluation_period, "5", user)
    login(client, user.email, password)
    response = client.post(
        f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}"
        f"/deliberation/{enrollment.id}/override",
        data={"manual_decision": "ADMITTED", "manual_reason": "court"},
    )
    assert response.status_code == 422
    assert DeliberationOverride.query.execution_options(skip_tenant_filter=True).count() == 0


def test_override_persists_and_is_audited(
    client, db, make_user, deliberation_policy, school_class, evaluation_period, course, enrollment
):
    user, password = make_user(role=RoleEnum.DIRECTION)
    _grade(db, enrollment, course, evaluation_period, "5", user)
    login(client, user.email, password)
    response = client.post(
        f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}"
        f"/deliberation/{enrollment.id}/override",
        data={
            "manual_decision": "ADMITTED",
            "manual_reason": "Effort exceptionnel reconnu par le conseil de classe.",
        },
    )
    assert response.status_code == 302
    override = DeliberationOverride.query.execution_options(skip_tenant_filter=True).one()
    assert override.decision.value == "ADMITTED"
    assert DeliberationAuditLog.query.execution_options(skip_tenant_filter=True).filter_by(action="MANUAL_OVERRIDE").count() == 1

    page = client.get(
        f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}/deliberation"
    ).data
    assert b"decision-manual" in page


def test_consolidate_blocked_while_encoding_incomplete(
    client, db, make_user, deliberation_policy, school_class, evaluation_period, course, enrollment
):
    user, password = make_user(role=RoleEnum.DIRECTION)
    login(client, user.email, password)
    response = client.post(
        f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}/consolidation/consolidate"
    )
    assert response.status_code == 409
    assert PeriodPublication.query.execution_options(skip_tenant_filter=True).count() == 0


def test_full_transition_sequence_increments_version_only_on_publish(
    client, db, make_user, deliberation_policy, school_class, evaluation_period, course, enrollment
):
    user, password = make_user(role=RoleEnum.DIRECTION)
    _grade(db, enrollment, course, evaluation_period, "15", user)
    login(client, user.email, password)
    base = f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}/consolidation"

    assert client.post(f"{base}/consolidate").status_code == 302
    publication = PeriodPublication.query.execution_options(skip_tenant_filter=True).one()
    assert publication.status.value == "CONSOLIDATED"
    assert publication.version == 0

    assert client.post(f"{base}/validate").status_code == 302
    assert PeriodPublication.query.execution_options(skip_tenant_filter=True).one().status.value == "VALIDATED"

    assert client.post(f"{base}/publish").status_code == 302
    published = PeriodPublication.query.execution_options(skip_tenant_filter=True).one()
    assert published.status.value == "PUBLISHED"
    assert published.version == 1


def test_transition_out_of_order_is_rejected(
    client, db, make_user, deliberation_policy, school_class, evaluation_period, course, enrollment
):
    user, password = make_user(role=RoleEnum.DIRECTION)
    _grade(db, enrollment, course, evaluation_period, "15", user)
    login(client, user.email, password)
    base = f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}/consolidation"
    response = client.post(f"{base}/publish")
    assert response.status_code == 409
    assert PeriodPublication.query.execution_options(skip_tenant_filter=True).count() == 0


def test_override_rejected_once_period_is_published(
    client, db, make_user, deliberation_policy, school_class, evaluation_period, course, enrollment
):
    user, password = make_user(role=RoleEnum.DIRECTION)
    _grade(db, enrollment, course, evaluation_period, "15", user)
    login(client, user.email, password)
    base = f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}"
    client.post(f"{base}/consolidation/consolidate")
    client.post(f"{base}/consolidation/validate")
    client.post(f"{base}/consolidation/publish")

    response = client.post(
        f"{base}/deliberation/{enrollment.id}/override",
        data={"manual_decision": "ADMITTED", "manual_reason": "Décision tardive après publication."},
    )
    assert response.status_code == 422
    assert DeliberationOverride.query.execution_options(skip_tenant_filter=True).count() == 0


def test_teacher_cannot_reach_consolidation_or_deliberation_or_audit(
    client, make_user, school_class, evaluation_period
):
    user, password = make_user(role=RoleEnum.ENSEIGNANT)
    login(client, user.email, password)
    base = f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}"
    assert client.get(f"{base}/consolidation").status_code == 403
    assert client.get(f"{base}/deliberation").status_code == 403
    assert client.post(f"{base}/consolidation/consolidate").status_code == 403
    assert client.get("/portal/audit").status_code == 403


def test_audit_log_merges_grade_and_deliberation_events_with_filters(
    client, db, make_user, deliberation_policy, school_class, evaluation_period, course, enrollment
):
    from app.services.audit_service import create_grade

    user, password = make_user(role=RoleEnum.DIRECTION)
    create_grade(
        ecole_id=enrollment.ecole_id,
        enrollment_id=enrollment.id,
        course_id=course.id,
        period_id=evaluation_period.id,
        score=Decimal("15"),
        entered_by_id=user.id,
        ip_address="127.0.0.1",
    )
    db.session.commit()
    login(client, user.email, password)
    base = f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}"
    client.post(
        f"{base}/deliberation/{enrollment.id}/override",
        data={"manual_decision": "ADMITTED", "manual_reason": "Motif suffisamment détaillé ici."},
    )

    # The action-filter dropdown always lists every label ("Création",
    # "Décision manuelle", ...) regardless of results, so assertions below
    # check the results table via the caption's row count, not a blanket
    # substring search over the whole page.
    all_entries = client.get("/portal/audit").data
    assert "2 événements".encode() in all_entries

    only_overrides = client.get("/portal/audit?action=MANUAL_OVERRIDE").data
    assert "1 événements".encode() in only_overrides
    assert b"D\xc3\xa9cision manuelle" in only_overrides

    no_such_student = client.get("/portal/audit?student=Personne-Inexistante").data
    assert "0 événements".encode() in no_such_student
