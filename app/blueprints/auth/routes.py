from datetime import UTC, datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.blueprints.auth.forms import LoginForm
from app.extensions import db
from app.models.user import User

bp = Blueprint("auth", __name__, url_prefix="/auth")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("admin.dashboard"))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower().strip()).first()
        if user is not None and user.is_active and user.check_password(form.password.data):
            login_user(user, remember=form.remember_me.data)
            user.last_login_at = datetime.now(UTC)
            db.session.commit()
            next_page = request.args.get("next")
            return redirect(next_page or url_for("admin.dashboard"))
        flash("Email ou mot de passe invalide.", "danger")

    return render_template("auth/login.html", form=form)


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
