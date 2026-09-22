import datetime
from decimal import Decimal

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app import create_app
from app.extensions import db as _db
from app.models.academic import AcademicYear, EvaluationPeriod, SchoolClass, Section
from app.models.course import Course
from app.models.grille import (
    GrilleCours,
    GrilleCoursLigne,
    GrilleCoursLigneMaximum,
    GroupeCours,
    Niveau,
)
from app.models.institution import Institution
from app.models.platform import CalculationStrategy
from app.models.student import Enrollment, Student
from app.models.tenant_config import TenantConfig
from app.models.user import RoleEnum, User


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
    if type(dbapi_connection).__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


@pytest.fixture()
def app():
    application = create_app("testing")
    with application.app_context():
        # drop_all() before create_all(): against a real, persistent
        # database (CI's Postgres service, reused across the "apply
        # migrations" step and the test run), a stray seed row from an
        # earlier step — e.g. the multi-tenant migration's own STANDARD
        # calculation-strategy row — would otherwise survive create_all()'s
        # checkfirst=True (which only creates missing tables, never
        # touches existing data) and collide with this suite's own
        # fixtures. Always start from a genuinely empty database.
        _db.drop_all()
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def db(app):
    return _db


@pytest.fixture()
def calculation_strategy_standard(db):
    strategy = CalculationStrategy(
        key="STANDARD", description="Moyenne pondérée standard."
    )
    db.session.add(strategy)
    db.session.commit()
    return strategy


@pytest.fixture()
def tenant_a(db, calculation_strategy_standard):
    """Institut Mont Carmel — the platform's first, reference tenant."""
    institution = Institution(
        name="Institut Mont Carmel",
        short_code="IMC",
        domain="montcarmel.testserver",
    )
    db.session.add(institution)
    db.session.commit()

    db.session.add(
        TenantConfig(
            ecole_id=institution.id,
            calculation_strategy_key="STANDARD",
            percentage_decimal_places=2,
            mentions=[{"min_percent": "80", "max_percent": "100", "label": "Excellence"}],
            eliminatory_course_codes=[],
            max_allowed_failures=None,
            report_signatures=[],
            feature_flags={},
        )
    )
    db.session.commit()
    return institution


@pytest.fixture()
def tenant_b(db, calculation_strategy_standard):
    """Lycée Kasa-Vubu — a second tenant with deliberately different
    grading configuration, so isolation/leak tests have something real to
    catch: a different rounding precision, eliminatory courses Mont Carmel
    doesn't have, and a tolerated-failures rule Mont Carmel doesn't use.
    """
    institution = Institution(
        name="Lycée Kasa-Vubu",
        short_code="LKV",
        domain="kasavubu.testserver",
    )
    db.session.add(institution)
    db.session.commit()

    db.session.add(
        TenantConfig(
            ecole_id=institution.id,
            calculation_strategy_key="STANDARD",
            percentage_decimal_places=1,
            mentions=[{"min_percent": "70", "max_percent": "100", "label": "Tableau d'honneur"}],
            eliminatory_course_codes=["EPS"],
            max_allowed_failures=2,
            report_signatures=[],
            feature_flags={"bulletins_bilingues": True},
        )
    )
    db.session.commit()
    return institution


@pytest.fixture()
def client(app, tenant_a):
    app.config["SERVER_NAME"] = tenant_a.domain
    return app.test_client()


@pytest.fixture()
def make_user(db, tenant_a):
    def _make_user(
        email="user@example.com",
        role=RoleEnum.ENSEIGNANT,
        password="Password123!",
        first_name="Jean",
        last_name="Dupont",
        ecole_id=None,
    ):
        user = User(
            ecole_id=ecole_id if ecole_id is not None else tenant_a.id,
            email=email,
            role=role,
            first_name=first_name,
            last_name=last_name,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user, password

    return _make_user


@pytest.fixture()
def academic_year(db, tenant_a):
    year = AcademicYear(
        ecole_id=tenant_a.id,
        label="2025-2026",
        start_date=datetime.date(2025, 9, 1),
        end_date=datetime.date(2026, 6, 30),
        is_current=True,
    )
    db.session.add(year)
    db.session.commit()
    return year


@pytest.fixture()
def section(db, tenant_a):
    sec = Section(ecole_id=tenant_a.id, name="Scientifique", code="SCI")
    db.session.add(sec)
    db.session.commit()
    return sec


@pytest.fixture()
def niveau(db, tenant_a):
    n = Niveau(ecole_id=tenant_a.id, libelle="6eme", ordre_affichage=6)
    db.session.add(n)
    db.session.commit()
    return n


@pytest.fixture()
def school_class(db, tenant_a, academic_year, section, niveau):
    klass = SchoolClass(
        ecole_id=tenant_a.id,
        academic_year_id=academic_year.id,
        section_id=section.id,
        niveau_id=niveau.id,
        name="6eme A",
        level_order=6,
    )
    db.session.add(klass)
    db.session.commit()
    return klass


@pytest.fixture()
def second_school_class(db, tenant_a, academic_year, section, niveau):
    """A second class sharing the same (section, niveau, year) grid as
    `school_class` — for scenarios needing two classes on one grid
    (titulaire/attributaire scope tests, grid-sharing proofs)."""
    klass = SchoolClass(
        ecole_id=tenant_a.id,
        academic_year_id=academic_year.id,
        section_id=section.id,
        niveau_id=niveau.id,
        name="6eme B",
        level_order=6,
    )
    db.session.add(klass)
    db.session.commit()
    return klass


@pytest.fixture()
def evaluation_period(db, tenant_a, academic_year):
    period = EvaluationPeriod(
        ecole_id=tenant_a.id,
        academic_year_id=academic_year.id,
        name="1er Trimestre",
        sequence_order=1,
        weight_percent=Decimal("33.333"),
        start_date=datetime.date(2025, 9, 1),
        end_date=datetime.date(2025, 12, 15),
    )
    db.session.add(period)
    db.session.commit()
    return period


@pytest.fixture()
def groupe_cours(db, tenant_a):
    g = GroupeCours(ecole_id=tenant_a.id, libelle="Cours", ordre_affichage=1)
    db.session.add(g)
    db.session.commit()
    return g


@pytest.fixture()
def grille_cours(db, tenant_a, section, niveau, academic_year):
    g = GrilleCours(
        ecole_id=tenant_a.id,
        section_id=section.id,
        niveau_id=niveau.id,
        academic_year_id=academic_year.id,
    )
    db.session.add(g)
    db.session.commit()
    return g


@pytest.fixture()
def course(db, tenant_a):
    """The tenant-wide catalog entry — carries no weight/maximum of its
    own; see `grille_ligne` for the grid line a Grade/TeacherAssignment
    actually references."""
    c = Course(ecole_id=tenant_a.id, name="Mathematiques", code="MATH")
    db.session.add(c)
    db.session.commit()
    return c


@pytest.fixture()
def grille_ligne(db, tenant_a, grille_cours, course, groupe_cours, evaluation_period):
    ligne = GrilleCoursLigne(
        ecole_id=tenant_a.id,
        grille_cours_id=grille_cours.id,
        cours_id=course.id,
        groupe_cours_id=groupe_cours.id,
        ordre_affichage=1,
        ponderation=Decimal("4"),
    )
    db.session.add(ligne)
    db.session.commit()
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
def student(db, tenant_a):
    s = Student(ecole_id=tenant_a.id, matricule="IMC-0001", first_name="Alice", last_name="Mwamba")
    db.session.add(s)
    db.session.commit()
    return s


@pytest.fixture()
def enrollment(db, tenant_a, student, school_class, academic_year):
    e = Enrollment(
        ecole_id=tenant_a.id,
        student_id=student.id,
        school_class_id=school_class.id,
        academic_year_id=academic_year.id,
        enrollment_date=datetime.date(2025, 9, 1),
    )
    db.session.add(e)
    db.session.commit()
    return e
