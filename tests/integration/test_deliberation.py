"""Server-owned consolidation, deliberation, override and publication
workflow — issue #42's backend contract, consumed by the portal views
built in PR #44 (app/ui/consolidation.py, portal/consolidation.html,
portal/deliberation.html, portal/override_decision.html).

Out-of-scope contextual access (wrong class, not the titulaire, not
Direction where Direction is required) is a 404, never a 403 — see
app.services.authorization_service's module docstring. A 403 only comes
from @roles_required's coarse "this role is never allowed on this
endpoint at all" gate."""

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
def second_grille_ligne(db, tenant_a, grille_cours, groupe_cours, evaluation_period):
    """A second subject on the SAME grid as `grille_ligne`."""
    from app.models.course import Course
    from app.models.grille import GrilleCoursLigne, GrilleCoursLigneMaximum

    c = Course(ecole_id=tenant_a.id, name="Éducation physique", code="EPS")
    db.session.add(c)
    db.session.flush()
    ligne = GrilleCoursLigne(
        ecole_id=tenant_a.id,
        grille_cours_id=grille_cours.id,
        cours_id=c.id,
        groupe_cours_id=groupe_cours.id,
        ordre_affichage=2,
        ponderation=Decimal("1"),
    )
    db.session.add(ligne)
    db.session.flush()
    db.session.add(
        GrilleCoursLigneMaximum(
            ecole_id=tenant_a.id,
            grille_cours_ligne_id=ligne.id,
            periode_id=evaluation_period.id,
            maximum=Decimal("20"),
        )
    )
    db.session.commit()
    return ligne


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


def _grade(db, enrollment, ligne, period, score, user):
    db.session.add(
        Grade(
            ecole_id=enrollment.ecole_id,
            enrollment_id=enrollment.id,
            grille_cours_ligne_id=ligne.id,
            period_id=period.id,
            score=Decimal(str(score)),
            entered_by_id=user.id,
        )
    )
    db.session.commit()


def test_consolidation_requires_a_deliberation_policy(
    client, db, make_user, school_class, evaluation_period, grille_ligne
):
    user, password = make_user(role=RoleEnum.DIRECTION)
    login(client, user.email, password)
    response = client.get(
        f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}/consolidation"
    )
    assert response.status_code == 503


def test_consolidation_flags_incomplete_course_as_blocking(
    client, db, make_user, deliberation_policy, school_class, evaluation_period, grille_ligne, enrollment
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
    client, db, make_user, deliberation_policy, school_class, evaluation_period, grille_ligne, enrollment
):
    user, password = make_user(role=RoleEnum.DIRECTION)
    _grade(db, enrollment, grille_ligne, evaluation_period, "16", user)
    login(client, user.email, password)
    response = client.get(
        f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}/deliberation"
    )
    assert response.status_code == 200
    assert b"decision-ADMITTED" in response.data


def test_automatic_decision_deferred_below_threshold(
    client, db, make_user, deliberation_policy, school_class, evaluation_period, grille_ligne, enrollment
):
    user, password = make_user(role=RoleEnum.DIRECTION)
    _grade(db, enrollment, grille_ligne, evaluation_period, "5", user)
    login(client, user.email, password)
    response = client.get(
        f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}/deliberation"
    )
    assert b"decision-DEFERRED" in response.data
    assert "inférieure au seuil".encode() in response.data


def test_automatic_decision_manual_when_no_grades_entered(
    client, db, make_user, deliberation_policy, school_class, evaluation_period, grille_ligne, enrollment
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
    grille_ligne,
    second_grille_ligne,
    enrollment,
):
    from app.models.tenant_config import TenantConfig

    TenantConfig.query.execution_options(skip_tenant_filter=True).filter_by(ecole_id=tenant_a.id).first().eliminatory_course_codes = ["EPS"]
    db.session.commit()

    user, password = make_user(role=RoleEnum.DIRECTION)
    _grade(db, enrollment, grille_ligne, evaluation_period, "18", user)  # strong in MATH
    _grade(db, enrollment, second_grille_ligne, evaluation_period, "2", user)  # fails EPS, eliminatory

    login(client, user.email, password)
    response = client.get(
        f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}/deliberation"
    )
    assert b"decision-DEFERRED" in response.data
    assert "Cours éliminatoire en échec".encode() in response.data


def test_override_requires_a_real_reason(
    client, db, make_user, deliberation_policy, school_class, evaluation_period, grille_ligne, enrollment
):
    user, password = make_user(role=RoleEnum.DIRECTION)
    _grade(db, enrollment, grille_ligne, evaluation_period, "5", user)
    login(client, user.email, password)
    response = client.post(
        f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}"
        f"/deliberation/{enrollment.id}/override",
        data={"manual_decision": "ADMITTED", "manual_reason": "court"},
    )
    assert response.status_code == 422
    assert DeliberationOverride.query.execution_options(skip_tenant_filter=True).count() == 0


def test_override_persists_and_is_audited(
    client, db, make_user, deliberation_policy, school_class, evaluation_period, grille_ligne, enrollment
):
    user, password = make_user(role=RoleEnum.DIRECTION)
    _grade(db, enrollment, grille_ligne, evaluation_period, "5", user)
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


def test_submit_blocked_while_encoding_incomplete(
    client, db, make_user, deliberation_policy, school_class, evaluation_period, grille_ligne, enrollment
):
    user, password = make_user(role=RoleEnum.DIRECTION)
    login(client, user.email, password)
    response = client.post(
        f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}/consolidation/submit"
    )
    assert response.status_code == 409
    assert PeriodPublication.query.execution_options(skip_tenant_filter=True).count() == 0


def test_only_the_titulaire_or_direction_may_submit(
    client, db, make_user, deliberation_policy, school_class, evaluation_period, grille_ligne, enrollment
):
    teacher, password = make_user(email="teacher@example.com")
    login(client, teacher.email, password)
    base = f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}/consolidation"
    # Not the titulaire, not Direction -> require_direction's contextual
    # refusal, surfaced as 404 (never 403 — see module docstring).
    assert client.post(f"{base}/submit").status_code == 404


def test_full_transition_sequence_increments_version_only_on_publish(
    client, db, make_user, deliberation_policy, school_class, evaluation_period, grille_ligne, enrollment
):
    user, password = make_user(role=RoleEnum.DIRECTION)
    _grade(db, enrollment, grille_ligne, evaluation_period, "15", user)
    login(client, user.email, password)
    base = f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}/consolidation"

    assert client.post(f"{base}/submit").status_code == 302
    publication = PeriodPublication.query.execution_options(skip_tenant_filter=True).one()
    assert publication.status.value == "SUBMITTED"
    assert publication.submitted_at is not None

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


def test_titulaire_can_submit_but_not_consolidate(
    client, db, make_user, deliberation_policy, school_class, evaluation_period, grille_ligne, enrollment
):
    teacher, password = make_user(email="titulaire@example.com")
    school_class.titulaire_id = teacher.id
    db.session.commit()
    director, _ = make_user(email="direction@example.com", role=RoleEnum.DIRECTION)
    _grade(db, enrollment, grille_ligne, evaluation_period, "15", director)

    login(client, teacher.email, password)
    base = f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}/consolidation"
    assert client.post(f"{base}/submit").status_code == 302
    assert (
        PeriodPublication.query.execution_options(skip_tenant_filter=True).one().status.value
        == "SUBMITTED"
    )
    # The titulaire's rights stop at "submit" — consolidate/validate/publish
    # stay DIRECTION-only, even for the class's own titulaire. Refused as
    # a 404 (require_direction), not 403.
    assert client.post(f"{base}/consolidate").status_code == 404


def test_transition_out_of_order_is_rejected(
    client, db, make_user, deliberation_policy, school_class, evaluation_period, grille_ligne, enrollment
):
    user, password = make_user(role=RoleEnum.DIRECTION)
    _grade(db, enrollment, grille_ligne, evaluation_period, "15", user)
    login(client, user.email, password)
    base = f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}/consolidation"
    response = client.post(f"{base}/publish")
    assert response.status_code == 409
    assert PeriodPublication.query.execution_options(skip_tenant_filter=True).count() == 0


def test_override_rejected_once_period_is_published(
    client, db, make_user, deliberation_policy, school_class, evaluation_period, grille_ligne, enrollment
):
    user, password = make_user(role=RoleEnum.DIRECTION)
    _grade(db, enrollment, grille_ligne, evaluation_period, "15", user)
    login(client, user.email, password)
    base = f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}"
    client.post(f"{base}/consolidation/submit")
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
    client, make_user, school_class, evaluation_period, grille_ligne
):
    user, password = make_user(role=RoleEnum.ENSEIGNANT)
    login(client, user.email, password)
    base = f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}"
    # Neither titulaire nor attributaire of this class -> contextual 404.
    assert client.get(f"{base}/consolidation").status_code == 404
    # /deliberation is Direction-only at the coarse @roles_required gate.
    assert client.get(f"{base}/deliberation").status_code == 403
    # Any transition but "submit" requires Direction via require_direction
    # -> contextual 404, not the coarse role gate.
    assert client.post(f"{base}/consolidation/consolidate").status_code == 404
    # /audit is Direction-only at the coarse @roles_required gate.
    assert client.get("/portal/audit").status_code == 403


def test_audit_log_merges_grade_and_deliberation_events_with_filters(
    client, db, make_user, deliberation_policy, school_class, evaluation_period, grille_ligne, enrollment
):
    from app.services.audit_service import create_grade

    user, password = make_user(role=RoleEnum.DIRECTION)
    create_grade(
        ecole_id=enrollment.ecole_id,
        enrollment_id=enrollment.id,
        grille_cours_ligne_id=grille_ligne.id,
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
