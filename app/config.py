"""Configuration objects for the Urafiki School Core application.

Each deployment (one school instance) supplies its own values via
environment variables (.env) — nothing school-specific is hard-coded here.
"""

import os
from datetime import timedelta


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production")

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///urafiki_dev.db"
    )
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    BCRYPT_LOG_ROUNDS = int(os.environ.get("BCRYPT_LOG_ROUNDS", "12"))

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", False)
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)

    WTF_CSRF_ENABLED = True

    TESTING = False
    DEBUG = False


class DevConfig(Config):
    DEBUG = True


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "TEST_DATABASE_URL", "sqlite:///:memory:"
    )
    BCRYPT_LOG_ROUNDS = 4  # fast hashing in tests
    WTF_CSRF_ENABLED = False

    if SQLALCHEMY_DATABASE_URI == "sqlite:///:memory:":
        # The default in-memory pool (SQLiteImpl's SingletonThreadPool)
        # hands each thread its own PRIVATE :memory: database, not a
        # shared one — invisible in ordinary single-threaded tests, but
        # the browser tests run a real Flask dev server on a background
        # thread (werkzeug threaded=True) that the main test thread also
        # queries directly. Different threads then silently see different,
        # disconnected databases, and concurrent access to whichever
        # connection SQLAlchemy does reuse corrupts cursor state under
        # SQLite's stock (not thread-safe) driver — surfacing as random
        # IntegrityErrors, "bad parameter" InterfaceErrors, or outright
        # crashes, never the same failure twice. StaticPool + a shared,
        # not-thread-affine connection (check_same_thread=False, safe here
        # because SQLAlchemy's pool already serializes access to it) fixes
        # this for good instead of leaving it as a flaky trap.
        from sqlalchemy.pool import StaticPool

        SQLALCHEMY_ENGINE_OPTIONS = {
            "poolclass": StaticPool,
            "connect_args": {"check_same_thread": False},
        }


class ProdConfig(Config):
    SESSION_COOKIE_SECURE = True


CONFIG_BY_NAME = {
    "development": DevConfig,
    "testing": TestConfig,
    "production": ProdConfig,
}


def get_config(env_name: str | None = None):
    env_name = env_name or os.environ.get("FLASK_ENV", "development")
    return CONFIG_BY_NAME.get(env_name, DevConfig)
