"""Seed a demo dataset for local development: Institut Mont Carmel, the
first tenant onboarded onto the multi-tenant platform — sample data for ONE
école, nothing here belongs in application code. Run with:

    flask --app wsgi.py shell < scripts/seed_dev_data.py

or import and call seed() from a Python shell.

Provisioning itself goes through `provision_tenant()` — the exact same path
`flask tenant create` uses — so this script never becomes a second,
diverging way to onboard a school.
"""

import datetime
from decimal import Decimal

from app.extensions import db
from app.models.academic import EvaluationPeriod, SchoolClass, Section
from app.models.course import Course
from app.models.grille import (
    GrilleCours,
    GrilleCoursLigne,
    GrilleCoursLigneMaximum,
    GroupeCours,
    Niveau,
)
from app.models.institution import Institution
from app.models.student import Enrollment, Student
from app.models.user import RoleEnum, User
from app.services.tenant_provisioning import provision_tenant


def seed() -> None:
    if Institution.query.first() is not None:
        print("Seed data already present, skipping.")
        return

    result = provision_tenant(
        name="Institut Mont Carmel",
        short_code="IMC",
        domain="montcarmel.urafiki.org",
        direction_email="direction@imc.example",
        direction_first_name="Marie",
        direction_last_name="Kabongo",
        academic_year_label="2025-2026",
        academic_year_start=datetime.date(2025, 9, 1),
        academic_year_end=datetime.date(2026, 6, 30),
        timezone="Africa/Lubumbashi",
        contact_email="direction@imc.example",
    )
    result.direction_user.set_password("ChangeMe123!")
    ecole_id = result.institution.id
    year = result.academic_year

    teacher = User(
        ecole_id=ecole_id,
        email="prof.math@imc.example",
        first_name="Jean",
        last_name="Mukendi",
        role=RoleEnum.ENSEIGNANT,
    )
    teacher.set_password("ChangeMe123!")
    db.session.add(teacher)

    section = Section(ecole_id=ecole_id, name="Scientifique", code="SCI")
    niveau = Niveau(ecole_id=ecole_id, libelle="6eme", ordre_affichage=6)
    db.session.add_all([section, niveau])
    db.session.flush()

    school_class = SchoolClass(
        ecole_id=ecole_id,
        academic_year_id=year.id,
        section_id=section.id,
        niveau_id=niveau.id,
        name="6eme Scientifique A",
        level_order=6,
    )
    db.session.add(school_class)
    db.session.flush()

    period = EvaluationPeriod(
        ecole_id=ecole_id,
        academic_year_id=year.id,
        name="1er Trimestre",
        sequence_order=1,
        weight_percent=Decimal("33.333"),
        start_date=datetime.date(2025, 9, 1),
        end_date=datetime.date(2025, 12, 15),
    )
    db.session.add(period)

    course = Course(ecole_id=ecole_id, name="Mathematiques", code="MATH")
    groupe = GroupeCours(ecole_id=ecole_id, libelle="Sciences", ordre_affichage=1)
    db.session.add_all([course, groupe])
    db.session.flush()

    grille = GrilleCours(
        ecole_id=ecole_id,
        section_id=section.id,
        niveau_id=niveau.id,
        academic_year_id=year.id,
    )
    db.session.add(grille)
    db.session.flush()

    ligne = GrilleCoursLigne(
        ecole_id=ecole_id,
        grille_cours_id=grille.id,
        cours_id=course.id,
        groupe_cours_id=groupe.id,
        ordre_affichage=1,
        ponderation=Decimal("4"),
    )
    db.session.add(ligne)
    db.session.flush()

    db.session.add(
        GrilleCoursLigneMaximum(
            ecole_id=ecole_id,
            grille_cours_ligne_id=ligne.id,
            periode_id=period.id,
            maximum=Decimal("20"),
        )
    )

    student = Student(
        ecole_id=ecole_id, matricule="IMC-0001", first_name="Alice", last_name="Mwamba"
    )
    db.session.add(student)
    db.session.flush()

    enrollment = Enrollment(
        ecole_id=ecole_id,
        student_id=student.id,
        school_class_id=school_class.id,
        academic_year_id=year.id,
        enrollment_date=datetime.date(2025, 9, 1),
    )
    db.session.add(enrollment)

    db.session.commit()
    print(f"Seed data created for Institut Mont Carmel (ecole_id={ecole_id}).")


if __name__ == "__main__":
    seed()
