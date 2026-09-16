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
        return db.session.get(User, int(user_id))


def _register_blueprints(app: Flask) -> None:
    from app.blueprints.admin import bp as admin_bp
    from app.blueprints.auth import bp as auth_bp

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
