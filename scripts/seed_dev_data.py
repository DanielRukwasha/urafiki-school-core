"""Seed a demo dataset for local development.

This is sample data for ONE deployment (Institut Mont Carmel) — nothing
here belongs in application code. Run with:

    flask --app wsgi.py shell < scripts/seed_dev_data.py

or import and call seed() from a Python shell.
"""

import datetime
from decimal import Decimal

from app.extensions import db
from app.models.academic import AcademicYear, EvaluationPeriod, SchoolClass, Section
from app.models.course import Course
from app.models.institution import Institution
from app.models.student import Enrollment, Student
from app.models.user import RoleEnum, User


def seed() -> None:
    if Institution.query.first() is not None:
        print("Seed data already present, skipping.")
        return

    institution = Institution(
        name="Institut Mont Carmel",
        short_code="IMC",
        timezone="Africa/Lubumbashi",
        contact_email="direction@imc.example",
    )
    db.session.add(institution)

    direction = User(
        email="direction@imc.example",
        first_name="Marie",
        last_name="Kabongo",
        role=RoleEnum.DIRECTION,
    )
    direction.set_password("ChangeMe123!")

    teacher = User(
        email="prof.math@imc.example",
        first_name="Jean",
        last_name="Mukendi",
        role=RoleEnum.ENSEIGNANT,
    )
    teacher.set_password("ChangeMe123!")

    db.session.add_all([direction, teacher])

    year = AcademicYear(
        label="2025-2026",
        start_date=datetime.date(2025, 9, 1),
        end_date=datetime.date(2026, 6, 30),
        is_current=True,
    )
    db.session.add(year)

    section = Section(name="Scientifique", code="SCI")
    db.session.add(section)
    db.session.flush()

    school_class = SchoolClass(
        academic_year_id=year.id,
        section_id=section.id,
        name="6eme Scientifique A",
        level_order=6,
    )
    db.session.add(school_class)
    db.session.flush()

    period = EvaluationPeriod(
        academic_year_id=year.id,
        name="1er Trimestre",
        sequence_order=1,
        weight_percent=Decimal("33.333"),
        start_date=datetime.date(2025, 9, 1),
        end_date=datetime.date(2025, 12, 15),
    )
    db.session.add(period)

    course = Course(
        school_class_id=school_class.id,
        name="Mathematiques",
        code="MATH",
        coefficient=Decimal("4"),
        max_score=Decimal("20"),
    )
    db.session.add(course)

    student = Student(matricule="IMC-0001", first_name="Alice", last_name="Mwamba")
    db.session.add(student)
    db.session.flush()

    enrollment = Enrollment(
        student_id=student.id,
        school_class_id=school_class.id,
        academic_year_id=year.id,
        enrollment_date=datetime.date(2025, 9, 1),
    )
    db.session.add(enrollment)

    db.session.commit()
    print("Seed data created for Institut Mont Carmel.")


if __name__ == "__main__":
    seed()
