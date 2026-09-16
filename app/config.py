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
