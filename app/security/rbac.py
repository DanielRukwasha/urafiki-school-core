"""Server-side role-based access control.

Every business route must be decorated with @roles_required(...) — RBAC is
never enforced only client-side. Checking current_user.is_authenticated is
handled here too, so a route only needs this one decorator.
"""

from functools import wraps

from flask import abort
from flask_login import current_user, login_required

from app.models.user import RoleEnum


def roles_required(*allowed_roles: RoleEnum):
    """Restrict a view to authenticated users whose role is in allowed_roles.

    Unauthenticated requests are redirected to the login page (standard
    Flask-Login behaviour via @login_required); an authenticated user with
    an insufficient role gets a hard 403.
    """

    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapped_view(*args, **kwargs):
            if current_user.role not in allowed_roles:
                abort(403)
            return view_func(*args, **kwargs)

        return wrapped_view

    return decorator
