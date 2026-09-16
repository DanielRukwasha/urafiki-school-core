import datetime
from decimal import Decimal

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app import create_app
from app.extensions import db as _db
from app.models.academic import AcademicYear, EvaluationPeriod, SchoolClass, Section
from app.models.course import Course
from app.models.student import Enrollment, Student
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
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def db(app):
    return _db


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def make_user(db):
    def _make_user(
        email="user@example.com",
        role=RoleEnum.ENSEIGNANT,
        password="Password123!",
        first_name="Jean",
        last_name="Dupont",
    ):
        user = User(
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
def academic_year(db):
    year = AcademicYear(
        label="2025-2026",
        start_date=datetime.date(2025, 9, 1),
        end_date=datetime.date(2026, 6, 30),
        is_current=True,
    )
    db.session.add(year)
    db.session.commit()
    return year


@pytest.fixture()
def section(db):
    sec = Section(name="Scientifique", code="SCI")
    db.session.add(sec)
    db.session.commit()
    return sec


@pytest.fixture()
def school_class(db, academic_year, section):
    klass = SchoolClass(
        academic_year_id=academic_year.id,
        section_id=section.id,
        name="6eme A",
        level_order=6,
    )
    db.session.add(klass)
    db.session.commit()
    return klass


@pytest.fixture()
def evaluation_period(db, academic_year):
    period = EvaluationPeriod(
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
def course(db, school_class):
    c = Course(
        school_class_id=school_class.id,
        name="Mathematiques",
        code="MATH",
        coefficient=Decimal("4"),
        max_score=Decimal("20"),
    )
    db.session.add(c)
    db.session.commit()
    return c


@pytest.fixture()
def student(db):
    s = Student(matricule="IMC-0001", first_name="Alice", last_name="Mwamba")
    db.session.add(s)
    db.session.commit()
    return s


@pytest.fixture()
def enrollment(db, student, school_class, academic_year):
    e = Enrollment(
        student_id=student.id,
        school_class_id=school_class.id,
        academic_year_id=academic_year.id,
        enrollment_date=datetime.date(2025, 9, 1),
    )
    db.session.add(e)
    db.session.commit()
    return e
