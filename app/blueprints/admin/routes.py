"""Minimal RBAC-protected routes.

These exist to prove the security socle end-to-end (login + roles_required
+ CSRF) with real integration tests. Full business CRUD (grade entry,
class management, ...) is deliberately out of scope for this sprint and is
tracked as future issues.
"""

from flask import Blueprint, render_template
from flask_login import current_user

from app.models.academic import AcademicYear
from app.models.user import RoleEnum, User
from app.security.rbac import roles_required

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.route("/")
@roles_required(RoleEnum.DIRECTION, RoleEnum.ENSEIGNANT, RoleEnum.SECRETARIAT)
def dashboard():
    return render_template("admin/dashboard.html", user=current_user)


@bp.route("/users")
@roles_required(RoleEnum.DIRECTION)
def list_users():
    users = User.query.order_by(User.last_name).all()
    return render_template("admin/users.html", users=users)


@bp.route("/academic-years")
@roles_required(RoleEnum.DIRECTION, RoleEnum.SECRETARIAT)
def list_academic_years():
    years = AcademicYear.query.order_by(AcademicYear.start_date.desc()).all()
    return render_template("admin/academic_years.html", years=years)
