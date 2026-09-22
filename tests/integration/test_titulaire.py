"""Class titulariat: a per-class scope, never a global role (business
amendment). A teacher can be titulaire of one class and a plain course
attributaire in another; their permissions are computed per class from
TeacherAssignment + the effective titulaire (SchoolClass.titulaire_id,
overridable by an active DelegationTitulariat), never from anything
stored globally on the account. Out-of-scope access is a 404, never a
403 — see app.services.authorization_service's module docstring."""

import datetime
from decimal import Decimal

import pytest

from app.models.course import Course
from app.models.grille import GrilleCoursLigne
from app.models.student import Enrollment, Student
from app.models.user import RoleEnum


def login(client, email, password):
    return client.post("/auth/login", data={"email": email, "password": password})


@pytest.fixture()
def second_grille_ligne(db, tenant_a, grille_cours, groupe_cours, evaluation_period):
    """A second subject on the SAME grid as `grille_ligne` — same class,
    different line, so a teacher can be assigned to one and not the
    other."""
    from app.models.grille import GrilleCoursLigneMaximum

    c = Course(ecole_id=tenant_a.id, name="Histoire", code="HIST")
    db.session.add(c)
    db.session.flush()
    ligne = GrilleCoursLigne(
        ecole_id=tenant_a.id,
        grille_cours_id=grille_cours.id,
        cours_id=c.id,
        groupe_cours_id=groupe_cours.id,
        ordre_affichage=2,
        ponderation=Decimal("2"),
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


@pytest.fixture()
def second_student_enrollment(db, tenant_a, school_class, academic_year):
    student = Student(ecole_id=tenant_a.id, matricule="IMC-0002", first_name="Bob", last_name="Kalala")
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


def test_non_titulaire_non_assigned_teacher_cannot_open_the_class_at_all(
    client, make_user, school_class, evaluation_period, grille_ligne
):
    outsider, password = make_user(email="outsider@example.com")
    login(client, outsider.email, password)
    base = f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}"
    assert client.get(f"{base}/grid").status_code == 404
    assert client.get(f"{base}/consolidation").status_code == 404


def test_titulaire_sees_every_course_read_only_but_can_edit_only_their_own(
    client,
    db,
    tenant_a,
    make_user,
    school_class,
    evaluation_period,
    grille_ligne,
    second_grille_ligne,
    enrollment,
):
    titulaire, password = make_user(email="titulaire@example.com")
    other_teacher, _ = make_user(email="other@example.com")
    from app.models.teaching import TeacherAssignment

    # Titulaire of the class, but only assigned to teach `grille_ligne` —
    # not `second_grille_ligne`, which belongs to `other_teacher`.
    school_class.titulaire_id = titulaire.id
    db.session.add(
        TeacherAssignment(
            ecole_id=tenant_a.id, teacher_id=titulaire.id,
            school_class_id=school_class.id, grille_cours_ligne_id=grille_ligne.id,
        )
    )
    db.session.add(
        TeacherAssignment(
            ecole_id=tenant_a.id, teacher_id=other_teacher.id,
            school_class_id=school_class.id, grille_cours_ligne_id=second_grille_ligne.id,
        )
    )
    db.session.commit()

    login(client, titulaire.email, password)
    grid = client.get(
        f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}/grid"
    ).data
    # Both lines are visible (read access to every course's grades)...
    assert b"Mathematiques" in grid
    assert b"Histoire" in grid

    # ...but writing to the line they don't teach is rejected server-side,
    # regardless of what the grid happened to render. Out-of-scope write
    # access is a 404, not a 403.
    sync = client.post(
        f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}/sync",
        data={
            "changes": (
                f'[{{"enrollment": {enrollment.id}, "course": {second_grille_ligne.id}, '
                f'"value": "12", "base": ""}}]'
            )
        },
    )
    assert sync.status_code == 404

    # Writing to their own assigned line succeeds normally.
    own = client.post(
        f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}/sync",
        data={
            "changes": (
                f'[{{"enrollment": {enrollment.id}, "course": {grille_ligne.id}, '
                f'"value": "14", "base": ""}}]'
            )
        },
    )
    assert own.status_code == 200


def test_titulaire_sees_class_on_dashboard_without_any_course_assignment(
    client, db, make_user, school_class, evaluation_period
):
    titulaire, password = make_user(email="titulaire@example.com")
    school_class.titulaire_id = titulaire.id
    db.session.commit()

    login(client, titulaire.email, password)
    dashboard = client.get("/portal/").data
    assert school_class.name.encode() in dashboard


def test_plain_teacher_without_titulariat_does_not_see_unassigned_class(
    client, make_user, school_class
):
    teacher, password = make_user(email="teacher@example.com")
    login(client, teacher.email, password)
    dashboard = client.get("/portal/").data
    assert school_class.name.encode() not in dashboard


def test_titulaire_of_one_class_is_a_plain_teacher_in_another(
    client, db, tenant_a, make_user, academic_year, section, niveau, evaluation_period,
    school_class, grille_ligne, enrollment,
):
    """The core of the amendment: titulariat is per class, not a global
    role — being titulaire of `school_class` grants nothing in a second,
    unrelated class the same teacher merely has a course assignment in."""
    from app.models.academic import SchoolClass
    from app.models.grille import GrilleCoursLigneMaximum, Niveau
    from app.models.teaching import TeacherAssignment

    teacher, password = make_user(email="teacher@example.com")
    school_class.titulaire_id = teacher.id
    db.session.add(
        TeacherAssignment(
            ecole_id=tenant_a.id, teacher_id=teacher.id,
            school_class_id=school_class.id, grille_cours_ligne_id=grille_ligne.id,
        )
    )

    other_niveau = Niveau(ecole_id=tenant_a.id, libelle="5eme", ordre_affichage=5)
    db.session.add(other_niveau)
    db.session.flush()
    other_niveau_class = SchoolClass(
        ecole_id=tenant_a.id,
        academic_year_id=academic_year.id,
        section_id=section.id,
        niveau_id=other_niveau.id,
        name="5eme B",
        level_order=5,
    )
    db.session.add(other_niveau_class)
    db.session.flush()

    from app.models.grille import GrilleCours, GrilleCoursLigne
    other_course = Course(ecole_id=tenant_a.id, name="Chimie", code="CHIM")
    db.session.add(other_course)
    db.session.flush()
    other_grille = GrilleCours(
        ecole_id=tenant_a.id,
        section_id=section.id,
        niveau_id=other_niveau.id,
        academic_year_id=academic_year.id,
    )
    db.session.add(other_grille)
    db.session.flush()
    other_ligne = GrilleCoursLigne(
        ecole_id=tenant_a.id,
        grille_cours_id=other_grille.id,
        cours_id=other_course.id,
        groupe_cours_id=grille_ligne.groupe_cours_id,
        ordre_affichage=1,
        ponderation=Decimal("2"),
    )
    db.session.add(other_ligne)
    db.session.flush()
    db.session.add(
        GrilleCoursLigneMaximum(
            ecole_id=tenant_a.id,
            grille_cours_ligne_id=other_ligne.id,
            periode_id=evaluation_period.id,
            maximum=Decimal("20"),
        )
    )
    db.session.add(
        TeacherAssignment(
            ecole_id=tenant_a.id, teacher_id=teacher.id,
            school_class_id=other_niveau_class.id, grille_cours_ligne_id=other_ligne.id,
        )
    )
    db.session.commit()

    login(client, teacher.email, password)
    # Consolidation (a titulaire-only read right) works in their own class...
    assert (
        client.get(
            f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}/consolidation"
        ).status_code
        != 404
    )
    # ...but is refused in the other class, even though they teach a course
    # there — titulariat does not travel with the account.
    assert (
        client.get(
            f"/portal/classes/{other_niveau_class.id}/periods/{evaluation_period.id}/consolidation"
        ).status_code
        == 404
    )


def test_direction_sets_titulaire_from_the_assignments_page(
    client, db, make_user, school_class
):
    director, password = make_user(role=RoleEnum.DIRECTION)
    teacher, _ = make_user(email="teacher@example.com")
    login(client, director.email, password)
    response = client.post(
        "/portal/assignments",
        data={
            "kind": "titulaire",
            "class_id": school_class.id,
            "titulaire_teacher_id": teacher.id,
            "motif": "Nomination initiale",
        },
    )
    assert response.status_code == 302
    db.session.refresh(school_class)
    assert school_class.titulaire_id == teacher.id


def test_titulaire_assignment_is_journalized_in_history(client, db, make_user, school_class):
    from app.models.titulariat import TitulaireHistorique

    director, password = make_user(role=RoleEnum.DIRECTION)
    teacher, _ = make_user(email="teacher@example.com")
    login(client, director.email, password)
    client.post(
        "/portal/assignments",
        data={
            "kind": "titulaire",
            "class_id": school_class.id,
            "titulaire_teacher_id": teacher.id,
            "motif": "Nomination initiale",
        },
    )
    history = (
        TitulaireHistorique.query.execution_options(skip_tenant_filter=True)
        .filter_by(school_class_id=school_class.id)
        .all()
    )
    assert len(history) == 1
    assert history[0].teacher_id == teacher.id
    assert history[0].date_fin is None


def test_delegation_grants_temporary_titulaire_rights(
    client, db, tenant_a, make_user, school_class, evaluation_period, grille_ligne
):
    """A delegation grants the delegataire the titulaire's consolidation
    read-right for the window it covers, without changing the class's
    recorded titulaire. Exercised over HTTP (not a direct service call)
    so tenant resolution happens the same way it does in production —
    see the TenantScopedModel bare-query gotcha noted throughout this
    codebase's tests."""
    from app.models.mixins import utcnow
    from app.models.titulariat import DelegationTitulariat, StatutDelegation

    titulaire, _ = make_user(email="titulaire@example.com")
    substitute, password = make_user(email="substitute@example.com")
    school_class.titulaire_id = titulaire.id
    now = utcnow()
    db.session.add(
        DelegationTitulariat(
            ecole_id=tenant_a.id,
            school_class_id=school_class.id,
            delegant_id=titulaire.id,
            delegataire_id=substitute.id,
            date_debut=now - datetime.timedelta(days=1),
            date_fin=now + datetime.timedelta(days=7),
            motif="Conge maladie",
            statut=StatutDelegation.ACTIVE,
        )
    )
    db.session.commit()

    login(client, substitute.email, password)
    assert (
        client.get(
            f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}/consolidation"
        ).status_code
        != 404
    )
