"""Class titulariat: a per-class scope, never a global role (business
amendment). A teacher can be titulaire of one class and a plain course
attributaire in another; their permissions are computed per class from
TeacherAssignment + SchoolClass.titulaire_id, never from anything stored
globally on the account."""

import datetime
from decimal import Decimal

import pytest

from app.models.course import Course
from app.models.student import Enrollment, Student
from app.models.user import RoleEnum


def login(client, email, password):
    return client.post("/auth/login", data={"email": email, "password": password})


@pytest.fixture()
def second_course(db, tenant_a, school_class):
    c = Course(
        ecole_id=tenant_a.id,
        school_class_id=school_class.id,
        name="Histoire",
        code="HIST",
        coefficient=Decimal("2"),
        max_score=Decimal("20"),
    )
    db.session.add(c)
    db.session.commit()
    return c


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
    client, make_user, school_class, evaluation_period
):
    outsider, password = make_user(email="outsider@example.com")
    login(client, outsider.email, password)
    base = f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}"
    assert client.get(f"{base}/grid").status_code == 403
    assert client.get(f"{base}/consolidation").status_code == 403


def test_titulaire_sees_every_course_read_only_but_can_edit_only_their_own(
    client,
    db,
    tenant_a,
    make_user,
    school_class,
    evaluation_period,
    course,
    second_course,
    enrollment,
):
    titulaire, password = make_user(email="titulaire@example.com")
    other_teacher, _ = make_user(email="other@example.com")
    from app.models.teaching import TeacherAssignment

    # Titulaire of the class, but only assigned to teach `course` — not
    # `second_course`, which belongs to `other_teacher`.
    school_class.titulaire_id = titulaire.id
    db.session.add(TeacherAssignment(ecole_id=tenant_a.id, teacher_id=titulaire.id, course_id=course.id))
    db.session.add(TeacherAssignment(ecole_id=tenant_a.id, teacher_id=other_teacher.id, course_id=second_course.id))
    db.session.commit()

    login(client, titulaire.email, password)
    grid = client.get(
        f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}/grid"
    ).data
    # Both courses are visible (read access to every course's grades)...
    assert b"Mathematiques" in grid
    assert b"Histoire" in grid

    # ...but writing to the course they don't teach is rejected server-side,
    # regardless of what the grid happened to render.
    sync = client.post(
        f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}/sync",
        data={
            "changes": (
                f'[{{"enrollment": {enrollment.id}, "course": {second_course.id}, '
                f'"value": "12", "base": ""}}]'
            )
        },
    )
    assert sync.status_code == 403

    # Writing to their own assigned course succeeds normally.
    own = client.post(
        f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}/sync",
        data={
            "changes": (
                f'[{{"enrollment": {enrollment.id}, "course": {course.id}, '
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
    client, db, tenant_a, make_user, academic_year, section, evaluation_period, course, enrollment
):
    """The core of the amendment: titulariat is per class, not a global
    role — being titulaire of `school_class` grants nothing in a second,
    unrelated class the same teacher merely has a course assignment in."""
    from app.models.academic import SchoolClass
    from app.models.teaching import TeacherAssignment

    teacher, password = make_user(email="teacher@example.com")
    course.school_class.titulaire_id = teacher.id
    db.session.add(TeacherAssignment(ecole_id=tenant_a.id, teacher_id=teacher.id, course_id=course.id))

    other_class = SchoolClass(
        ecole_id=tenant_a.id,
        academic_year_id=academic_year.id,
        section_id=section.id,
        name="5eme B",
        level_order=5,
    )
    db.session.add(other_class)
    db.session.flush()
    other_course = Course(
        ecole_id=tenant_a.id,
        school_class_id=other_class.id,
        name="Chimie",
        code="CHIM",
        coefficient=Decimal("2"),
        max_score=Decimal("20"),
    )
    db.session.add(other_course)
    db.session.flush()
    db.session.add(TeacherAssignment(ecole_id=tenant_a.id, teacher_id=teacher.id, course_id=other_course.id))
    db.session.commit()

    login(client, teacher.email, password)
    # Consolidation (a titulaire-only read right) works in their own class...
    assert (
        client.get(
            f"/portal/classes/{course.school_class_id}/periods/{evaluation_period.id}/consolidation"
        ).status_code
        != 403
    )
    # ...but is refused in the other class, even though they teach a course
    # there — titulariat does not travel with the account.
    assert (
        client.get(
            f"/portal/classes/{other_class.id}/periods/{evaluation_period.id}/consolidation"
        ).status_code
        == 403
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
        },
    )
    assert response.status_code == 302
    db.session.refresh(school_class)
    assert school_class.titulaire_id == teacher.id
