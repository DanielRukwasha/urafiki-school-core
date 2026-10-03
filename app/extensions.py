"""Flask extension instances, created unbound and wired in create_app()."""

from flask_babel import lazy_gettext as _l
from flask_bcrypt import Bcrypt
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect

from app.security.tenant_session import TenantScopedSession

# Tenant-aware session: see app/security/tenant_session.py.
db = SQLAlchemy(session_options={"class_": TenantScopedSession})
migrate = Migrate()
login_manager = LoginManager()
bcrypt = Bcrypt()
csrf = CSRFProtect()

login_manager.login_view = "auth.login"
login_manager.login_message = _l("Veuillez vous connecter pour accéder à cette page.")
login_manager.login_message_category = "warning"
