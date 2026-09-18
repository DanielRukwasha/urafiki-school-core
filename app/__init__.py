"""Application Factory for Urafiki School Core."""

from flask import Flask

from app.config import get_config
from app.extensions import bcrypt, csrf, db, login_manager, migrate


def create_app(config_name: str | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(get_config(config_name))

    _register_extensions(app)
    _register_blueprints(app)
    _register_error_handlers(app)

    from app.security.tenant import init_tenant_resolution

    init_tenant_resolution(app)

    from app.tenant_presentation import install_tenant_presentation

    install_tenant_presentation(app)

    from app.cli import register_cli

    register_cli(app)

    return app


def _register_extensions(app: Flask) -> None:
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    bcrypt.init_app(app)
    csrf.init_app(app)

    from app.models.user import User

    @login_manager.user_loader
    def load_user(user_id: str):
        # Bypasses automatic tenant filtering on purpose: this must find the
        # session's user regardless of the current request's tenant, so the
        # tenant-resolution middleware can compare the two explicitly and
        # audit-log a mismatch instead of it silently looking like "logged
        # out" (see app/security/tenant.py::resolve_tenant).
        return db.session.get(
            User, int(user_id), execution_options={"skip_tenant_filter": True}
        )


def _register_blueprints(app: Flask) -> None:
    from app.blueprints.admin import bp as admin_bp
    from app.blueprints.auth import bp as auth_bp
    from app.blueprints.portal import bp as portal_bp

    app.register_blueprint(portal_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)


def _register_error_handlers(app: Flask) -> None:
    from flask import render_template

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("errors/404.html"), 404
