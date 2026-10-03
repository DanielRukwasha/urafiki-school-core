import datetime
from dataclasses import dataclass
from decimal import Decimal

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app import create_app
from app.config import TestConfig
from app.extensions import db as _db
from app.models.academic import AcademicYear, EvaluationPeriod, SchoolClass, Section
from app.models.course import Course
from app.models.deliberation import DeliberationPolicy
from app.models.deliberation_workflow import PeriodPublication, PublicationStatus
from app.models.grading import Grade, GradeAuditAction, GradeAuditLog
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
from app.models.teaching import TeacherAssignment
from app.models.tenant_config import TenantConfig
from app.models.user import RoleEnum, User


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
    if type(dbapi_connection).__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        # WAL lets the live server's threads write while the test thread
        # holds a read transaction (file-backed browser databases only;
        # a no-op for :memory:).
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


# ---------------------------------------------------------------------------
# Test tiers. The default `pytest` run (and CI's `test` job) executes every
# test EXCEPT the `browser` and `pdf` tiers, which need system dependencies
# (Chromium, Pango). Those run in CI's `browser-pdf` job via
# `pytest -m "browser or pdf"`. A tier that is selected but whose
# dependencies are missing FAILS the whole run with an explicit message —
# it is never silently skipped, so a green run means the same thing
# locally and in CI. See README.md, "Tests".
# ---------------------------------------------------------------------------

_PDF_TEST_FILES = {"test_portal_pdf.py", "test_report_presentation_pdf.py"}


def pytest_collection_modifyitems(config, items):
    for item in items:
        path = item.path
        if "browser" in path.parts:
            item.add_marker(pytest.mark.browser)
        if path.name in _PDF_TEST_FILES:
            item.add_marker(pytest.mark.pdf)


def _missing_dependencies(tiers: set[str]) -> list[str]:
    missing = []
    if "browser" in tiers:
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as pw:
                pw.chromium.launch().close()
        except Exception as error:  # noqa: BLE001 - reported verbatim below
            missing.append(
                "browser : Playwright/Chromium indisponible "
                f"({type(error).__name__}: {str(error).splitlines()[0]}). "
                "Installer : pip install -r requirements-browser.txt && "
                "python -m playwright install --with-deps chromium"
            )
    if "pdf" in tiers:
        for module, hint in (
            ("weasyprint", "pip install -r requirements-pdf.txt + bibliothèques Pango natives"),
            ("pypdf", "pip install -r requirements-browser.txt"),
            ("PIL", "pip install -r requirements-pdf.txt"),
        ):
            try:
                __import__(module)
            except (ImportError, OSError) as error:
                missing.append(f"pdf : module {module} indisponible ({error}). Installer : {hint}")
    return missing


def pytest_collection_finish(session):
    tiers = {
        marker
        for item in session.items
        for marker in ("browser", "pdf")
        if item.get_closest_marker(marker)
    }
    if not tiers:
        return
    missing = _missing_dependencies(tiers)
    if missing:
        pytest.exit(
            "Dépendances système manquantes pour les tests sélectionnés — "
            "la suite échoue au lieu d'ignorer ces tests (voir README.md, « Tests ») :\n  - "
            + "\n  - ".join(missing),
            returncode=pytest.ExitCode.USAGE_ERROR,
        )


@pytest.fixture()
def app(request, tmp_path):
    overrides = {}
    if (
        request.node.get_closest_marker("browser")
        and TestConfig.SQLALCHEMY_DATABASE_URI == "sqlite:///:memory:"
    ):
        # A live server answers Chromium's parallel requests on several
        # threads; the shared in-memory connection is not thread-safe
        # (see app/config.py::TestConfig). Each thread gets its own
        # connection to a temporary file-backed database instead.
        overrides = {
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{(tmp_path / 'browser.db').as_posix()}",
            "SQLALCHEMY_ENGINE_OPTIONS": {"connect_args": {"timeout": 30}},
        }
    application = create_app("testing", config_overrides=overrides)
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
        _db.engine.dispose()


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


# ---------------------------------------------------------------------------
# Two FICTITIOUS tenants, deliberately divergent. Neither is modeled on a
# real client: a suite that mirrors the first client cannot prove the code
# is school-agnostic. Every structural dimension differs:
#
#                         tenant_a (Alpha)        tenant_b (Beta)
#   periods / year        3 trimesters            2 semesters
#   period weights        33.333 % each           40 % / 60 %
#   scale (maximum)       /20                     /10
#   rounding (decimals)   2                       1
#   passing threshold     50 %                    60 %
#   eliminatory courses   none                    EPS
#   tolerated failures    unlimited (None)        2
#   mentions              1 band (80+)            2 bands (60+, 75+)
#
# tenant_a's first period, maximum and grid come from the ordinary
# fixtures below (evaluation_period, grille_ligne, ...);
# `tenant_a_structure` adds its remaining trimesters and its policy, and
# `tenant_b_world` builds tenant_b's complete, independent structure.
# tests/integration/test_tenant_fixtures.py asserts the divergence holds.
# ---------------------------------------------------------------------------

TENANT_A_SPEC = {
    "periods": 3,
    "weights": ("33.333", "33.333", "33.334"),
    "maximum": Decimal("20"),
    "decimals": 2,
    "threshold": Decimal("50"),
}
TENANT_B_SPEC = {
    "periods": 2,
    "weights": ("40", "60"),
    "maximum": Decimal("10"),
    "decimals": 1,
    "threshold": Decimal("60"),
}


@pytest.fixture()
def tenant_a(db, calculation_strategy_standard):
    """École Fictive Alpha — fictitious tenant, see the table above."""
    institution = Institution(
        name="École Fictive Alpha",
        short_code="EFA",
        domain="alpha.testserver",
    )
    db.session.add(institution)
    db.session.commit()

    db.session.add(
        TenantConfig(
            ecole_id=institution.id,
            calculation_strategy_key="STANDARD",
            percentage_decimal_places=TENANT_A_SPEC["decimals"],
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
    """École Fictive Beta — fictitious tenant whose configuration diverges
    from tenant_a on every axis (see the table above), so isolation and
    leak tests have something real to catch."""
    institution = Institution(
        name="École Fictive Beta",
        short_code="EFB",
        domain="beta.testserver",
    )
    db.session.add(institution)
    db.session.commit()

    db.session.add(
        TenantConfig(
            ecole_id=institution.id,
            calculation_strategy_key="STANDARD",
            percentage_decimal_places=TENANT_B_SPEC["decimals"],
            mentions=[
                {"min_percent": "60", "max_percent": "75", "label": "Satisfaction"},
                {"min_percent": "75", "max_percent": "100", "label": "Distinction"},
            ],
            eliminatory_course_codes=["EPS"],
            max_allowed_failures=2,
            report_signatures=[],
            feature_flags={"bulletins_bilingues": True},
        )
    )
    db.session.commit()
    return institution


@pytest.fixture()
def tenant_a_structure(db, tenant_a, academic_year, evaluation_period):
    """Completes tenant_a's structure: its 2nd and 3rd trimesters and its
    deliberation policy. Returns every period, in order."""
    periods = [evaluation_period]
    for order, (name, weight, start, end) in enumerate(
        (
            ("2e Trimestre", TENANT_A_SPEC["weights"][1], (2026, 1, 5), (2026, 3, 27)),
            ("3e Trimestre", TENANT_A_SPEC["weights"][2], (2026, 4, 13), (2026, 6, 30)),
        ),
        start=2,
    ):
        period = EvaluationPeriod(
            ecole_id=tenant_a.id,
            academic_year_id=academic_year.id,
            name=name,
            sequence_order=order,
            weight_percent=Decimal(weight),
            start_date=datetime.date(*start),
            end_date=datetime.date(*end),
        )
        db.session.add(period)
        periods.append(period)
    db.session.add(
        DeliberationPolicy(
            ecole_id=tenant_a.id,
            academic_year_id=academic_year.id,
            passing_threshold_percent=TENANT_A_SPEC["threshold"],
        )
    )
    db.session.commit()
    return periods


@dataclass
class TenantWorld:
    """Every entity of one tenant that the isolation battery targets."""

    institution: Institution
    direction: User
    teacher: User
    academic_year: AcademicYear
    school_class: SchoolClass
    periods: list
    course: Course
    ligne: GrilleCoursLigne
    student: Student
    enrollment: Enrollment
    grade: Grade
    publication: PeriodPublication


@pytest.fixture()
def tenant_b_world(db, tenant_b):
    """tenant_b's complete, independent structure (2 semesters, /10 scale,
    60 % threshold) with one graded, published student — the target every
    cross-tenant injection test tries, and must fail, to reach."""
    eid = tenant_b.id

    def add(obj):
        db.session.add(obj)
        db.session.flush()
        return obj

    direction = User(
        ecole_id=eid, email="direction@beta.example", role=RoleEnum.DIRECTION,
        first_name="Bea", last_name="Direction",
    )
    direction.set_password("Password123!")
    teacher = User(
        ecole_id=eid, email="prof@beta.example", role=RoleEnum.ENSEIGNANT,
        first_name="Ben", last_name="Enseignant",
    )
    teacher.set_password("Password123!")
    add(direction)
    add(teacher)
    year = add(AcademicYear(
        ecole_id=eid, label="2025-2026", start_date=datetime.date(2025, 9, 1),
        end_date=datetime.date(2026, 6, 30), is_current=True,
    ))
    section = add(Section(ecole_id=eid, name="Générale", code="GEN"))
    niveau = add(Niveau(ecole_id=eid, libelle="Seconde", ordre_affichage=10))
    klass = add(SchoolClass(
        ecole_id=eid, academic_year_id=year.id, section_id=section.id,
        niveau_id=niveau.id, name="Seconde 1", level_order=10,
    ))
    periods = [
        add(EvaluationPeriod(
            ecole_id=eid, academic_year_id=year.id, name=name, sequence_order=order,
            weight_percent=Decimal(weight), start_date=datetime.date(*start),
            end_date=datetime.date(*end),
        ))
        for order, (name, weight, start, end) in enumerate(
            (
                ("Semestre 1", TENANT_B_SPEC["weights"][0], (2025, 9, 1), (2026, 1, 31)),
                ("Semestre 2", TENANT_B_SPEC["weights"][1], (2026, 2, 1), (2026, 6, 30)),
            ),
            start=1,
        )
    ]
    add(DeliberationPolicy(
        ecole_id=eid, academic_year_id=year.id,
        passing_threshold_percent=TENANT_B_SPEC["threshold"],
    ))
    groupe = add(GroupeCours(ecole_id=eid, libelle="Tronc commun", ordre_affichage=1))
    grille = add(GrilleCours(
        ecole_id=eid, section_id=section.id, niveau_id=niveau.id, academic_year_id=year.id,
    ))
    course = add(Course(ecole_id=eid, name="Physique", code="PHY"))
    ligne = add(GrilleCoursLigne(
        ecole_id=eid, grille_cours_id=grille.id, cours_id=course.id,
        groupe_cours_id=groupe.id, ordre_affichage=1, ponderation=Decimal("3"),
    ))
    for period in periods:
        add(GrilleCoursLigneMaximum(
            ecole_id=eid, grille_cours_ligne_id=ligne.id, periode_id=period.id,
            maximum=TENANT_B_SPEC["maximum"],
        ))
    add(TeacherAssignment(
        ecole_id=eid, teacher_id=teacher.id, school_class_id=klass.id,
        grille_cours_ligne_id=ligne.id,
    ))
    student = add(Student(
        ecole_id=eid, matricule="EFB-0001", first_name="Bintou", last_name="Secretbeta",
    ))
    enrollment = add(Enrollment(
        ecole_id=eid, student_id=student.id, school_class_id=klass.id,
        academic_year_id=year.id, enrollment_date=datetime.date(2025, 9, 1),
    ))
    grade = add(Grade(
        ecole_id=eid, enrollment_id=enrollment.id, grille_cours_ligne_id=ligne.id,
        period_id=periods[0].id, score=Decimal("7.50"), entered_by_id=teacher.id,
    ))
    add(GradeAuditLog(
        ecole_id=eid, grade_id=grade.id, enrollment_id=enrollment.id,
        grille_cours_ligne_id=ligne.id, period_id=periods[0].id,
        action=GradeAuditAction.CREATE, new_value=grade.score, user_id=teacher.id,
    ))
    publication = add(PeriodPublication(
        ecole_id=eid, school_class_id=klass.id, period_id=periods[0].id,
        status=PublicationStatus.PUBLISHED, version=1,
    ))
    db.session.commit()
    return TenantWorld(
        institution=tenant_b, direction=direction, teacher=teacher, academic_year=year,
        school_class=klass, periods=periods, course=course, ligne=ligne, student=student,
        enrollment=enrollment, grade=grade, publication=publication,
    )


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
    s = Student(ecole_id=tenant_a.id, matricule="EFA-0001", first_name="Alice", last_name="Mwamba")
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
