"""Server-rendered teaching portal and bounded, audited grade synchronization."""

import json
from decimal import Decimal, InvalidOperation

from flask import Blueprint, abort, make_response, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.academic import EvaluationPeriod, SchoolClass
from app.models.course import Course
from app.models.grading import Grade
from app.models.institution import Institution
from app.models.student import Enrollment, EnrollmentStatus, Student
from app.models.teaching import TeacherAssignment
from app.models.user import RoleEnum, User
from app.security.rbac import roles_required
from app.services.audit_service import create_grade, update_grade_score
from app.services.grade_calculation_engine import (
    CourseGradeInput,
    compute_period_total,
    quantize_percentage,
    rank_students,
)

bp = Blueprint("portal", __name__, url_prefix="/portal")
ALL_ROLES = tuple(RoleEnum)
EDIT_ROLES = (RoleEnum.DIRECTION, RoleEnum.ENSEIGNANT)


def active(query, model):
    return query.filter(model.archived_at.is_(None))


def courses_for(class_id=None):
    query = active(Course.query, Course).join(SchoolClass).filter(SchoolClass.archived_at.is_(None))
    if class_id is not None:
        query = query.filter(Course.school_class_id == class_id)
    if current_user.role == RoleEnum.ENSEIGNANT:
        query = query.join(TeacherAssignment).filter(
            TeacherAssignment.teacher_id == current_user.id,
            TeacherAssignment.archived_at.is_(None),
        )
    return [
        course
        for course in query.order_by(Course.name).all()
        if not course.school_class.academic_year.is_archived
    ]


def context(class_id, period_id):
    klass = db.get_or_404(SchoolClass, class_id)
    period = db.get_or_404(EvaluationPeriod, period_id)
    if klass.is_archived or klass.academic_year.is_archived or period.is_archived:
        abort(404)
    if period.academic_year_id != klass.academic_year_id:
        abort(404)
    courses = courses_for(class_id)
    if current_user.role == RoleEnum.ENSEIGNANT and not courses:
        abort(403)
    enrollments = (
        active(Enrollment.query, Enrollment)
        .join(Student)
        .filter(
            Enrollment.school_class_id == class_id,
            Enrollment.academic_year_id == klass.academic_year_id,
            Enrollment.status != EnrollmentStatus.WITHDRAWN,
            Student.archived_at.is_(None),
        )
        .order_by(Student.last_name, Student.first_name)
        .all()
    )
    grades = Grade.query.filter(
        Grade.enrollment_id.in_([e.id for e in enrollments]),
        Grade.course_id.in_([c.id for c in courses]),
        Grade.period_id == period_id,
    ).all()
    return dict(
        klass=klass,
        period=period,
        courses=courses,
        enrollments=enrollments,
        grades={(g.enrollment_id, g.course_id): g for g in grades},
    )


@bp.after_request
def private_response(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.before_request
def session_check():
    if request.method == "POST" and (
        not current_user.is_authenticated or not current_user.is_active
    ):
        return "Session expirée. Reconnectez-vous avant de synchroniser.", 401
    if current_user.is_authenticated and not current_user.is_active:
        abort(403)


@bp.get("/")
@roles_required(*ALL_ROLES)
def dashboard():
    courses = courses_for()
    ids = {c.school_class_id for c in courses}
    classes = active(SchoolClass.query, SchoolClass).order_by(SchoolClass.name).all()
    if current_user.role == RoleEnum.ENSEIGNANT:
        classes = [c for c in classes if c.id in ids]
    classes = [c for c in classes if not c.academic_year.is_archived]
    return render_template("portal/dashboard.html", classes=classes, courses=courses)


@bp.route("/assignments", methods=["GET", "POST"])
@roles_required(RoleEnum.DIRECTION)
def assignments():
    error = None
    if request.method == "POST":
        teacher = db.session.get(User, request.form.get("teacher_id", type=int))
        course = db.session.get(Course, request.form.get("course_id", type=int))
        if (
            not teacher
            or not teacher.is_active
            or teacher.role != RoleEnum.ENSEIGNANT
            or not course
            or course.is_archived
            or course.school_class.is_archived
            or course.school_class.academic_year.is_archived
        ):
            error = "Sélectionnez un enseignant actif et un cours valide."
        else:
            item = TeacherAssignment.query.filter_by(
                teacher_id=teacher.id, course_id=course.id
            ).first()
            if item:
                item.archived_at = None
            else:
                db.session.add(TeacherAssignment(teacher_id=teacher.id, course_id=course.id))
            try:
                db.session.commit()
                return redirect(url_for("portal.assignments"))
            except IntegrityError:
                db.session.rollback()
                error = "Cette attribution existe déjà. Rechargez la page."
    return render_template(
        "portal/assignments.html",
        error=error,
        courses=courses_for(),
        teachers=active(User.query, User)
        .filter_by(role=RoleEnum.ENSEIGNANT, is_active_account=True)
        .all(),
        assignments=active(TeacherAssignment.query, TeacherAssignment).all(),
    ), 422 if error else 200


@bp.get("/classes/<int:class_id>/periods/<int:period_id>/grid")
@roles_required(*EDIT_ROLES)
def grid(class_id, period_id):
    return render_template("portal/grid.html", **context(class_id, period_id))


@bp.post("/classes/<int:class_id>/periods/<int:period_id>/sync")
@roles_required(*EDIT_ROLES)
def sync(class_id, period_id):
    ctx = context(class_id, period_id)
    ecole_id = ctx["klass"].ecole_id
    try:
        changes = json.loads(request.form.get("changes", "[]"))
        if not isinstance(changes, list) or not 1 <= len(changes) <= 30:
            raise ValueError
    except (ValueError, TypeError):
        return "Lot invalide (1 à 30 cellules).", 400
    courses = {c.id: c for c in ctx["courses"]}
    enrollment_ids = {e.id for e in ctx["enrollments"]}
    results = []
    seen = set()
    for change in changes:
        if not isinstance(change, dict):
            return "Cellule invalide.", 400
        eid, cid = change.get("enrollment"), change.get("course")
        if (
            type(eid) is not int
            or type(cid) is not int
            or eid not in enrollment_ids
            or cid not in courses
        ):
            abort(403)
        if (eid, cid) in seen:
            return "Cellule répétée dans le lot.", 400
        seen.add((eid, cid))
        if (
            not isinstance(change.get("value"), str)
            or not isinstance(change.get("base"), str)
            or len(change["value"]) > 32
            or len(change["base"]) > 32
        ):
            return "Valeur invalide.", 400
    for change in changes:
        eid, cid = change["enrollment"], change["course"]
        result = dict(
            key=f"{eid}-{cid}",
            value=change["value"],
            state="saved",
            message="Enregistré",
            base=change["base"],
        )
        try:
            score = Decimal(change["value"].replace(",", "."))
            if (
                not score.is_finite()
                or score < 0
                or score > courses[cid].max_score
                or score != score.quantize(Decimal("0.01"))
            ):
                raise ValueError
        except (InvalidOperation, ValueError):
            result.update(
                state="error",
                message=f"Saisir une cote entre 0 et {courses[cid].max_score}, avec 2 décimales maximum.",
            )
            results.append(result)
            continue
        try:
            with db.session.begin_nested():
                grade = (
                    Grade.query.filter_by(enrollment_id=eid, course_id=cid, period_id=period_id)
                    .with_for_update()
                    .populate_existing()
                    .first()
                )
                base = str(grade.score) if grade else ""
                if grade and (grade.is_archived or grade.is_validated):
                    result.update(
                        state="error", message="Cote verrouillée. Contactez la direction."
                    )
                elif base != change["base"] and (not grade or grade.score != score):
                    result.update(
                        state="error",
                        message="Conflit : une autre saisie existe. Rechargez pour comparer.",
                    )
                else:
                    if grade is None:
                        grade = create_grade(
                            ecole_id=ecole_id,
                            enrollment_id=eid,
                            course_id=cid,
                            period_id=period_id,
                            score=score,
                            entered_by_id=current_user.id,
                            ip_address=request.remote_addr,
                        )
                    elif grade.score != score:
                        update_grade_score(
                            grade=grade,
                            new_score=score,
                            user_id=current_user.id,
                            ip_address=request.remote_addr,
                        )
                    result["base"] = format(score, ".2f")
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            result.update(
                state="error", message="Modification concurrente. Rechargez pour comparer."
            )
        results.append(result)
    response = make_response(
        render_template("portal/_sync.html", results=results),
        422 if any(r["state"] == "error" for r in results) else 200,
    )
    response.headers["X-Grade-Sync"] = "1"
    return response


def result_context(class_id, period_id):
    ctx = context(class_id, period_id)
    ctx["grades"] = {key: grade for key, grade in ctx["grades"].items() if not grade.is_archived}
    rows = []
    for enrollment in ctx["enrollments"]:
        inputs = [
            CourseGradeInput(
                c.id,
                c.coefficient,
                c.max_score,
                ctx["grades"][(enrollment.id, c.id)].score
                if (enrollment.id, c.id) in ctx["grades"]
                else None,
            )
            for c in ctx["courses"]
        ]
        total = compute_period_total(period_id, inputs)
        rows.append(
            dict(
                enrollment=enrollment,
                total=total,
                entered=sum(i.score is not None for i in inputs),
                percentage=quantize_percentage(total.percentage)
                if total.percentage is not None
                else None,
            )
        )
    ranks = {
        r.enrollment_id: r.rank
        for r in rank_students([(r["enrollment"].id, r["total"].percentage) for r in rows])
    }
    unranked = len(rows) + 1
    rows.sort(
        key=lambda row: (
            ranks.get(row["enrollment"].id, unranked),
            row["enrollment"].student.last_name,
        )
    )
    ctx.update(
        rows=rows,
        ranks=ranks,
        institution=db.session.get(Institution, ctx["klass"].ecole_id),
    )
    return ctx


@bp.get("/classes/<int:class_id>/periods/<int:period_id>/results")
@roles_required(RoleEnum.DIRECTION, RoleEnum.SECRETARIAT)
def results(class_id, period_id):
    return render_template("portal/results.html", **result_context(class_id, period_id))


@bp.get("/classes/<int:class_id>/periods/<int:period_id>/print/<kind>")
@roles_required(RoleEnum.DIRECTION, RoleEnum.SECRETARIAT)
def print_report(class_id, period_id, kind):
    if kind not in ("bulletins", "palmares"):
        abort(404)
    html = render_template(
        "portal/print.html",
        kind=kind,
        pdf=request.args.get("format") == "pdf",
        **result_context(class_id, period_id),
    )
    if request.args.get("format") != "pdf":
        return html
    try:
        from weasyprint import HTML
    except (ImportError, OSError):
        return render_template("portal/pdf_unavailable.html"), 503
    response = make_response(HTML(string=html).write_pdf())
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = (
        f'attachment; filename="{kind}-{class_id}-{period_id}.pdf"'
    )
    return response
