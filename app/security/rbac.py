"""Server-side role-based access control.

Every business route must be decorated with @roles_required(...) — RBAC is
never enforced only client-side. Checking current_user.is_authenticated is
handled here too, so a route only needs this one decorator.
"""

from functools import wraps

from flask import abort
from flask_login import current_user, login_required

from app.models.user import RoleEnum


def is_titulaire(user, school_class) -> bool:
    """Whether `user` is the homeroom teacher (titulaire) of this class —
    a per-class scope read from `SchoolClass.titulaire_id`, never a role
    carried globally on the account. A teacher can be titulaire of one
    class and a plain course attributaire in another."""
    return school_class.titulaire_id is not None and school_class.titulaire_id == user.id


def require_direction_or_titulaire(school_class) -> None:
    """403s unless the signed-in user is DIRECTION, or the titulaire of
    this specific class. For views a titulaire may read for their own
    class only (class-wide grades, encoding progress) — deliberately not
    a `roles_required` decorator, since titulariat is per-class, not a
    role the decorator's flat allow-list can express."""
    if current_user.role == RoleEnum.DIRECTION:
        return
    if current_user.role == RoleEnum.ENSEIGNANT and is_titulaire(current_user, school_class):
        return
    abort(403)


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
