"""Smoke test: the Alembic migration chain must build the full schema from
scratch on a clean database. Runs against a throwaway SQLite file â€” CI runs
the same chain against real PostgreSQL as the authoritative check.
"""

import pathlib

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app import create_app
from app.config import TestConfig
from app.extensions import db

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
EXPECTED_TABLES = {
    "institutions",
    "users",
    "academic_years",
    "sections",
    "school_classes",
    "evaluation_periods",
    "courses",
    "students",
    "enrollments",
    "teacher_assignments",
    "grades",
    "grade_audit_logs",
    "deliberation_policies",
    "bulletin_versions",
    "sensitive_read_logs",
}


def test_alembic_upgrade_head_creates_full_schema(tmp_path, monkeypatch):
    db_path = tmp_path / "migration_smoke.db"
    db_url = f"sqlite:///{db_path.as_posix()}"

    monkeypatch.setattr(TestConfig, "SQLALCHEMY_DATABASE_URI", db_url)
    application = create_app("testing")

    alembic_cfg = Config(str(PROJECT_ROOT / "migrations" / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))

    with application.app_context():
        command.upgrade(alembic_cfg, "head")
        tables = set(inspect(db.engine).get_table_names())

    assert EXPECTED_TABLES.issubset(tables)


def test_conformite_migration_is_reversible(tmp_path, monkeypatch):
    """c3f1a9d27b40 (bulletin versions + sensitive read journal) must
    downgrade cleanly and upgrade again — invariant: Alembic migrations
    are reversible."""
    db_url = f"sqlite:///{(tmp_path / 'reversible.db').as_posix()}"
    monkeypatch.setattr(TestConfig, "SQLALCHEMY_DATABASE_URI", db_url)
    application = create_app("testing")
    alembic_cfg = Config(str(PROJECT_ROOT / "migrations" / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    new_tables = {"bulletin_versions", "sensitive_read_logs"}

    with application.app_context():
        command.upgrade(alembic_cfg, "head")
        assert new_tables <= set(inspect(db.engine).get_table_names())
        command.downgrade(alembic_cfg, "14efd3eb110e")
        assert not new_tables & set(inspect(db.engine).get_table_names())
        command.upgrade(alembic_cfg, "head")
        assert new_tables <= set(inspect(db.engine).get_table_names())


def test_conformite_migration_backfills_versions_from_publish_audit(tmp_path, monkeypatch):
    """Existing publications become bulletin versions with their real
    author and timestamp; a version > 1 that predates motif tracking says
    so explicitly instead of inventing a motif."""
    import datetime
    from decimal import Decimal

    from sqlalchemy import text

    from app.models import (
        AcademicYear,
        DeliberationAction,
        DeliberationAuditLog,
        EvaluationPeriod,
        Institution,
        Niveau,
        PeriodPublication,
        PublicationStatus,
        SchoolClass,
        Section,
        User,
    )
    from app.models.user import RoleEnum

    db_url = f"sqlite:///{(tmp_path / 'backfill.db').as_posix()}"
    monkeypatch.setattr(TestConfig, "SQLALCHEMY_DATABASE_URI", db_url)
    application = create_app("testing")
    alembic_cfg = Config(str(PROJECT_ROOT / "migrations" / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))

    with application.app_context():
        command.upgrade(alembic_cfg, "head")
        school = Institution(name="École Fictive Gamma", short_code="EFG", domain="g.testserver")
        db.session.add(school)
        db.session.flush()
        eid = school.id
        author = User(ecole_id=eid, email="d@g.example", role=RoleEnum.DIRECTION,
                      first_name="D", last_name="G")
        author.set_password("x")
        year = AcademicYear(ecole_id=eid, label="2025-2026", start_date=datetime.date(2025, 9, 1),
                            end_date=datetime.date(2026, 6, 30))
        section = Section(ecole_id=eid, name="S", code="S")
        niveau = Niveau(ecole_id=eid, libelle="N", ordre_affichage=1)
        db.session.add_all([author, year, section, niveau])
        db.session.flush()
        klass = SchoolClass(ecole_id=eid, academic_year_id=year.id, section_id=section.id,
                            niveau_id=niveau.id, name="C")
        period = EvaluationPeriod(ecole_id=eid, academic_year_id=year.id, name="P",
                                  sequence_order=1, weight_percent=Decimal("100"),
                                  start_date=datetime.date(2025, 9, 1),
                                  end_date=datetime.date(2026, 6, 30))
        db.session.add_all([klass, period])
        db.session.flush()
        db.session.add(PeriodPublication(ecole_id=eid, school_class_id=klass.id,
                                         period_id=period.id, status=PublicationStatus.PUBLISHED,
                                         version=2))
        for day in (1, 2):
            db.session.add(DeliberationAuditLog(
                ecole_id=eid, action=DeliberationAction.PUBLISH, period_id=period.id,
                school_class_id=klass.id, old_value="VALIDATED", new_value="PUBLISHED",
                user_id=author.id,
                created_at=datetime.datetime(2026, 1, day, tzinfo=datetime.UTC),
            ))
        db.session.commit()
        author_id = author.id
        db.session.remove()

        command.downgrade(alembic_cfg, "14efd3eb110e")
        command.upgrade(alembic_cfg, "head")

        rows = db.session.execute(text(
            "SELECT numero, motif, auteur_id, corrige_version_id, id "
            "FROM bulletin_versions ORDER BY numero"
        )).all()
    assert [r.numero for r in rows] == [1, 2]
    assert rows[0].motif is None and rows[0].corrige_version_id is None
    assert "reprise de données" in rows[1].motif
    assert rows[1].corrige_version_id == rows[0].id
    assert {r.auteur_id for r in rows} == {author_id}
