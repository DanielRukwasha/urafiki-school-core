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
