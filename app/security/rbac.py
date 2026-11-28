"""Server-side role-based access control.

Every business route must be decorated with @roles_required(...) — RBAC is
never enforced only client-side. Checking current_user.is_authenticated is
handled here too, so a route only needs this one decorator.

Contextual, per-resource authorization (is THIS user allowed on THIS
class/line/period) is never decided here — see
app.services.authorization_service, which this module's two legacy
helpers now delegate to for backward compatibility.
"""

from functools import wraps

from flask import abort
from flask_login import current_user, login_required
from werkzeug.exceptions import NotFound

from app.models.user import RoleEnum


def is_titulaire(user, school_class) -> bool:
    """Deprecated alias for
    `app.services.authorization_service.est_titulaire_effectif` — kept so
    older call sites keep working, but new code should call the
    authorization service directly."""
    from app.services.authorization_service import est_titulaire_effectif

    return est_titulaire_effectif(user, school_class)


def require_direction_or_titulaire(school_class) -> None:
    """Deprecated alias for
    `app.services.authorization_service.require_lecture_classe`."""
    from app.services.authorization_service import require_lecture_classe

    try:
        require_lecture_classe(current_user, school_class)
    except NotFound:
        abort(404)


def roles_required(*allowed_roles: RoleEnum):
    """Restrict a view to authenticated users whose role is in allowed_roles.

    Unauthenticated requests are redirected to the login page (standard
    Flask-Login behaviour via @login_required); an authenticated user whose
    role is never admitted on the view gets a bare 404, exactly like a
    route that does not exist: a role excluded from a resource is out of
    scope, and a 403 would confirm that the resource exists (AGENT_BRIEFING,
    invariant 6).
    """

    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapped_view(*args, **kwargs):
            if current_user.role not in allowed_roles:
                abort(404)
            return view_func(*args, **kwargs)

        return wrapped_view

    return decorator
