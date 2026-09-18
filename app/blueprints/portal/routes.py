"""Server-rendered teaching portal and bounded, audited grade synchronization.

Every contextual permission check here goes through
`app.services.authorization_service` — this module makes no
`current_user.role ==` comparison of its own; `@roles_required` only
gates broad route access (is this role ever allowed on this endpoint at
all), never a specific class, line, or student.
"""

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from flask import Blueprint, abort, make_response, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.academic import EvaluationPeriod, SchoolClass
from app.models.grading import Grade
from app.models.student import Enrollment, EnrollmentStatus, Student
from app.models.teaching import TeacherAssignment
from app.models.user import RoleEnum, User
from app.security.rbac import roles_required
from app.services.audit_service import create_grade, update_grade_content
from app.services.authorization_service import (
    affecter_titulaire,
    est_attributaire,
    est_titulaire_effectif,
    peut_encoder_ligne,
    peut_lire_cotes_classe,
    peut_soumettre_classe,
    require_direction,
    require_lecture_classe,
)
from app.services.grade_calculation_engine import (
    CourseGradeInput,
    compute_period_total,
    quantize_percentage,
    rank_students,
)
from app.services.grille_service import (
    GrilleConfigError,
    lignes_actives,
    maximum_pour_periode,
    resoudre_grille,
)
from app.ui.consolidation import ConsolidationPayloadError, normalize_consolidation

bp = Blueprint("portal", __name__, url_prefix="/portal")
ALL_ROLES = tuple(RoleEnum)
EDIT_ROLES = (RoleEnum.DIRECTION, RoleEnum.ENSEIGNANT)


def active(query, model):
    return query.filter(model.archived_at.is_(None))


@dataclass(frozen=True)
class CourseColumn:
    """A grid line, adapted for the grade grid/report templates — `id` is
    the `GrilleCoursLigne.id` a `Grade` actually references. `max_score`
    is the maximum configured for the period this column was built for
    (None for an appreciation line, which has no numeric maximum)."""

    id: int
    code: str
    name: str
    coefficient: Decimal
    max_score: Decimal | None
    is_appreciation: bool
    groupe_id: int


def _course_columns(klass, period=None) -> list[CourseColumn]:
    """Every active column of the class's grid, in display order. Raises
    GrilleConfigError (surfaced by callers as a 503) if the class has no
    grid configured for its (section, niveau, year) — never silently an
    empty grid."""
    grille = resoudre_grille(klass)
    columns = []
    for ligne in lignes_actives(grille):
        max_score = None
        if not ligne.note_par_appreciation and period is not None:
            max_score = maximum_pour_periode(ligne, period.id)
        columns.append(
            CourseColumn(
                id=ligne.id,
                code=ligne.cours.code,
                name=ligne.cours.name,
                coefficient=ligne.ponderation,
                max_score=max_score,
                is_appreciation=ligne.note_par_appreciation,
                groupe_id=ligne.groupe_cours_id,
            )
        )
    return columns


def display_columns_for(klass, period=None) -> list[CourseColumn]:
    """Columns to SHOW for this class: every column, for Direction/
    Secrétariat or the class's effective titulaire (read-only, class-wide
    visibility); only the columns the caller is personally assigned to,
    for a plain attributaire."""
    columns = _course_columns(klass, period=period)
    if peut_lire_cotes_classe(current_user, klass):
        return columns
    grille = resoudre_grille(klass)
    lignes_by_id = {ligne.id: ligne for ligne in lignes_actives(grille)}
    return [c for c in columns if est_attributaire(current_user, klass, lignes_by_id[c.id])]


def editable_column_ids_for(klass, period) -> set[int]:
    """The subset of the class's grid lines the caller may WRITE grades
    for, for this specific period. Titulariat never widens this: a
    titulaire who isn't assigned to a line still can't touch its
    grades — matching "il ne peut jamais modifier une cote encodée par
    un autre enseignant"."""
    grille = resoudre_grille(klass)
    return {
        ligne.id
        for ligne in lignes_actives(grille)
        if peut_encoder_ligne(current_user, klass, ligne, period)
    }


def context(class_id, period_id):
    klass = db.get_or_404(SchoolClass, class_id)
    period = db.get_or_404(EvaluationPeriod, period_id)
    if klass.is_archived or klass.academic_year.is_archived or period.is_archived:
        abort(404)
    if period.academic_year_id != klass.academic_year_id:
        abort(404)
    try:
        courses = display_columns_for(klass, period=period)
        editable_course_ids = editable_column_ids_for(klass, period)
    except GrilleConfigError as error:
        abort(503, description=str(error))
    if current_user.role == RoleEnum.ENSEIGNANT and not courses:
        abort(404)
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
        Grade.grille_cours_ligne_id.in_([c.id for c in courses]),
        Grade.period_id == period_id,
    ).all()
    return dict(
        klass=klass,
        period=period,
        courses=courses,
        editable_course_ids=editable_course_ids,
        enrollments=enrollments,
        grades={(g.enrollment_id, g.grille_cours_ligne_id): g for g in grades},
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
    classes = active(SchoolClass.query, SchoolClass).order_by(SchoolClass.name).all()
    classes = [c for c in classes if not c.academic_year.is_archived]
    if current_user.role == RoleEnum.ENSEIGNANT:
        # Server-derived, never filtered client-side: a course assignment
        # grants access to that course's class, and effective titulariat
        # grants access to that class even without a course assignment
        # there.
        assigned_class_ids = {
            a.school_class_id
            for a in active(TeacherAssignment.query, TeacherAssignment).filter_by(
                teacher_id=current_user.id
            )
        }
        classes = [
            c
            for c in classes
            if c.id in assigned_class_ids or est_titulaire_effectif(current_user, c)
        ]
    courses = []
    for klass in classes:
        try:
            courses.extend(display_columns_for(klass))
        except GrilleConfigError:
            continue
    return render_template("portal/dashboard.html", classes=classes, courses=courses)


@bp.route("/assignments", methods=["GET", "POST"])
@roles_required(RoleEnum.DIRECTION)
def assignments():
    error = None
    classes = active(SchoolClass.query, SchoolClass).order_by(SchoolClass.name).all()
    line_choices = []  # (class, CourseColumn) pairs across every configured grid
    for klass in classes:
        try:
            for column in _course_columns(klass):
                line_choices.append((klass, column))
        except GrilleConfigError:
            continue

    if request.method == "POST" and request.form.get("kind") == "titulaire":
        klass = db.session.get(SchoolClass, request.form.get("class_id", type=int))
        teacher = db.session.get(User, request.form.get("titulaire_teacher_id", type=int))
        motif = request.form.get("motif", "").strip()
        if (
            not klass
            or klass.is_archived
            or klass.academic_year.is_archived
            or not teacher
            or not teacher.is_active
            or teacher.role != RoleEnum.ENSEIGNANT
            or not motif
        ):
            error = "Sélectionnez une classe, un enseignant actif et un motif valides."
        else:
            affecter_titulaire(klass, teacher, motif=motif, actor=current_user)
            return redirect(url_for("portal.assignments"))
    elif request.method == "POST":
        teacher = db.session.get(User, request.form.get("teacher_id", type=int))
        klass = db.session.get(SchoolClass, request.form.get("class_id", type=int))
        ligne_id = request.form.get("grille_cours_ligne_id", type=int)
        valid_pair = klass is not None and ligne_id in {
            c.id for k, c in line_choices if k.id == (klass.id if klass else None)
        }
        if (
            not teacher
            or not teacher.is_active
            or teacher.role != RoleEnum.ENSEIGNANT
            or not klass
            or klass.is_archived
            or klass.academic_year.is_archived
            or not valid_pair
        ):
            error = "Sélectionnez un enseignant actif et une ligne de grille valide."
        else:
            item = TeacherAssignment.query.filter_by(
                teacher_id=teacher.id, school_class_id=klass.id, grille_cours_ligne_id=ligne_id
            ).first()
            if item:
                item.archived_at = None
            else:
                db.session.add(
                    TeacherAssignment(
                        teacher_id=teacher.id,
                        school_class_id=klass.id,
                        grille_cours_ligne_id=ligne_id,
                    )
                )
            try:
                db.session.commit()
                return redirect(url_for("portal.assignments"))
            except IntegrityError:
                db.session.rollback()
                error = "Cette attribution existe déjà. Rechargez la page."

    return render_template(
        "portal/assignments.html",
        error=error,
        line_choices=line_choices,
        classes=classes,
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
    editable_course_ids = ctx["editable_course_ids"]
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
            or cid not in editable_course_ids
        ):
            # A titulaire may SEE every line's grades in this class
            # (ctx["courses"]) but writes are still bounded to their own
            # TeacherAssignment scope — a line they can see but not edit
            # lands here, same as any other unauthorized cell. Out-of-scope
            # access is a 404, not a 403 — see authorization_service's
            # module docstring.
            abort(404)
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
        column = courses[cid]
        result = dict(
            key=f"{eid}-{cid}",
            value=change["value"],
            state="saved",
            message="Enregistré",
            base=change["base"],
        )
        if column.is_appreciation:
            result.update(state="error", message="Colonne à appréciation : saisie non prise en charge ici.")
            results.append(result)
            continue
        try:
            score = Decimal(change["value"].replace(",", "."))
            if (
                not score.is_finite()
                or score < 0
                or score > column.max_score
                or score != score.quantize(Decimal("0.01"))
            ):
                raise ValueError
        except (InvalidOperation, ValueError):
            result.update(
                state="error",
                message=f"Saisir une cote entre 0 et {column.max_score}, avec 2 décimales maximum.",
            )
            results.append(result)
            continue
        try:
            with db.session.begin_nested():
                grade = (
                    Grade.query.filter_by(
                        enrollment_id=eid, grille_cours_ligne_id=cid, period_id=period_id
                    )
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
                            grille_cours_ligne_id=cid,
                            period_id=period_id,
                            score=score,
                            entered_by_id=current_user.id,
                            ip_address=request.remote_addr,
                        )
                    elif grade.score != score:
                        update_grade_content(
                            grade=grade,
                            score=score,
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
                ligne_id=c.id,
                groupe_id=c.groupe_id,
                coefficient=c.coefficient,
                max_score=c.max_score,
                score=ctx["grades"][(enrollment.id, c.id)].score
                if (enrollment.id, c.id) in ctx["grades"]
                else None,
                is_numeric=not c.is_appreciation,
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
    ctx.update(rows=rows, ranks=ranks)
    return ctx


@bp.get("/classes/<int:class_id>/periods/<int:period_id>/results")
@roles_required(RoleEnum.DIRECTION, RoleEnum.SECRETARIAT)
def results(class_id, period_id):
    return render_template("portal/results.html", **result_context(class_id, period_id))


def _server_consolidation_payload(class_id, period_id):
    """The real consolidation/deliberation payload, computed server-side —
    see app/services/deliberation_service.py. Shaped exactly as
    `normalize_consolidation` expects, so it also acts as a contract
    check: a bug in the service that produces a malformed payload shows
    up as a 502 here, not as a template crash."""
    klass = db.get_or_404(SchoolClass, class_id)
    period = db.get_or_404(EvaluationPeriod, period_id)
    try:
        grille = resoudre_grille(klass)
        grille_lignes = lignes_actives(grille)
    except GrilleConfigError as error:
        abort(503, description=str(error))
    enrollments = (
        active(Enrollment.query, Enrollment)
        .join(Student)
        .filter(
            Enrollment.school_class_id == class_id,
            Enrollment.academic_year_id == klass.academic_year_id,
            Enrollment.status != EnrollmentStatus.WITHDRAWN,
            Student.archived_at.is_(None),
        )
        .all()
    )
    try:
        from app.services.deliberation_service import (
            DeliberationConfigError,
            compute_class_consolidation,
        )

        payload = compute_class_consolidation(klass, period, grille_lignes, enrollments)
    except DeliberationConfigError as error:
        abort(503, description=str(error))
    try:
        return normalize_consolidation(payload)
    except ConsolidationPayloadError:
        abort(502, description="Réponse de consolidation invalide.")


@bp.get("/classes/<int:class_id>/periods/<int:period_id>/consolidation")
@roles_required(*ALL_ROLES)
def consolidation(class_id, period_id):
    klass = db.get_or_404(SchoolClass, class_id)
    require_lecture_classe(current_user, klass)
    payload = _server_consolidation_payload(class_id, period_id)
    return render_template(
        "portal/consolidation.html",
        consolidation=payload,
        deliberation_url=url_for("portal.deliberation", class_id=class_id, period_id=period_id),
        preview_url=url_for(
            "portal.print_report", class_id=class_id, period_id=period_id, kind="bulletins"
        ),
        transitions=_available_transitions(class_id, period_id, payload, klass),
    )


def _available_transitions(class_id, period_id, payload, klass):
    from app.ui.consolidation import TRANSITIONS

    status = payload["publication"]["status"]
    next_action = _next_action_for(status)
    period = db.session.get(EvaluationPeriod, period_id)
    can_act = current_user.role == RoleEnum.DIRECTION or (
        next_action == "submit" and peut_soumettre_classe(current_user, klass, period)
    )
    if not can_act:
        return []
    return [
        {
            "action": t.action,
            "label": t.label,
            "consequence": t.consequence,
            "irreversible": t.irreversible,
            "url": url_for(
                "portal.transition", class_id=class_id, period_id=period_id, action=t.action
            ),
        }
        for t in TRANSITIONS
        if next_action == t.action
    ]


def _next_action_for(status):
    from app.models.deliberation_workflow import (
        NEXT_STATUS,
        TRANSITION_ACTION_FOR_STATUS,
        PublicationStatus,
    )

    next_status = NEXT_STATUS.get(PublicationStatus(status))
    return TRANSITION_ACTION_FOR_STATUS[next_status] if next_status else None


@bp.post("/classes/<int:class_id>/periods/<int:period_id>/consolidation/<action>")
@roles_required(*ALL_ROLES)
def transition(class_id, period_id, action):
    from app.services.deliberation_service import TransitionError, apply_transition

    klass = db.get_or_404(SchoolClass, class_id)
    period = db.get_or_404(EvaluationPeriod, period_id)
    if action == "submit":
        if not peut_soumettre_classe(current_user, klass, period):
            require_direction(current_user)
    else:
        require_direction(current_user)

    if action == "submit":
        payload = _server_consolidation_payload(class_id, period_id)
        if payload["blocking_items"]:
            return (
                render_template(
                    "portal/preview_error.html",
                    error="Soumission bloquée : des cours n'ont pas toutes leurs cotes saisies.",
                ),
                409,
            )
    try:
        apply_transition(
            school_class_id=class_id, period_id=period_id, action=action, user=current_user
        )
    except TransitionError as error:
        return render_template("portal/preview_error.html", error=str(error)), 409
    return redirect(url_for("portal.consolidation", class_id=class_id, period_id=period_id))


@bp.get("/classes/<int:class_id>/periods/<int:period_id>/deliberation")
@roles_required(RoleEnum.DIRECTION)
def deliberation(class_id, period_id):
    payload = _server_consolidation_payload(class_id, period_id)
    decision = request.args.get("decision", "")
    sort = request.args.get("sort", "rank")
    rows = payload["decisions"]
    if decision:
        rows = [row for row in rows if row["automatic_decision"] == decision]
    sort_keys = {
        "student": lambda row: row["student_name"],
        "rank": lambda row: row["rank"],
        "percentage": lambda row: (
            row["percentage"] is None,
            -(row["percentage"] or 0),
        ),
    }
    rows = sorted(rows, key=sort_keys.get(sort, sort_keys["rank"]))
    payload = {**payload, "decisions": rows}
    return render_template(
        "portal/deliberation.html",
        consolidation=payload,
        consolidation_url=url_for("portal.consolidation", class_id=class_id, period_id=period_id),
        deliberation_url=url_for("portal.deliberation", class_id=class_id, period_id=period_id),
        decision_filters=(
            ("ADMITTED", "Admis"),
            ("DEFERRED", "Ajourné"),
            ("MANUAL", "À délibérer"),
        ),
        active_decision=decision,
        pagination_controls="",
    )


@bp.route(
    "/classes/<int:class_id>/periods/<int:period_id>/deliberation/<int:enrollment_id>/override",
    methods=["GET", "POST"],
)
@roles_required(RoleEnum.DIRECTION)
def override_decision(class_id, period_id, enrollment_id):
    from app.models.deliberation_workflow import ManualDecision
    from app.models.student import Enrollment
    from app.services.deliberation_service import (
        DeliberationConfigError,
        TransitionError,
        apply_override,
    )

    db.get_or_404(SchoolClass, class_id)
    db.get_or_404(EvaluationPeriod, period_id)
    enrollment = db.session.get(Enrollment, enrollment_id)
    if enrollment is None or enrollment.school_class_id != class_id:
        abort(404)

    if request.method == "POST":
        raw_decision = request.form.get("manual_decision", "")
        reason = request.form.get("manual_reason", "")
        try:
            decision = ManualDecision(raw_decision)
        except ValueError:
            return render_template("portal/preview_error.html", error="Décision invalide."), 422
        try:
            apply_override(
                enrollment_id=enrollment_id,
                period_id=period_id,
                school_class_id=class_id,
                decision=decision,
                reason=reason,
                user=current_user,
            )
        except (DeliberationConfigError, TransitionError) as error:
            return render_template("portal/preview_error.html", error=str(error)), 422
        return redirect(
            url_for("portal.deliberation", class_id=class_id, period_id=period_id)
        )

    return render_template(
        "portal/override_decision.html",
        student_name=enrollment.student.full_name,
        decision_options=(("ADMITTED", "Admis"), ("DEFERRED", "Ajourné")),
    )


@bp.get("/audit")
@roles_required(RoleEnum.DIRECTION)
def audit_log():
    from app.services.deliberation_service import query_audit_log

    filters = {
        key: request.args.get(key, "") for key in ("user", "student", "action", "from", "to")
    }
    page = request.args.get("page", 1, type=int) or 1
    entries, pagination = query_audit_log(
        user=filters["user"] or None,
        student=filters["student"] or None,
        action=filters["action"] or None,
        from_date=filters["from"] or None,
        to_date=filters["to"] or None,
        page=page,
    )
    return render_template(
        "portal/audit_log.html",
        entries=entries,
        pagination=pagination,
        pagination_controls="",
        filters={
            "user": filters["user"],
            "student": filters["student"],
            "action": filters["action"],
            "from_date": filters["from"],
            "to_date": filters["to"],
        },
        action_filters=(
            ("CREATE", "Création"),
            ("UPDATE", "Modification"),
            ("DELETE", "Suppression"),
            ("MANUAL_OVERRIDE", "Décision manuelle"),
            ("CONSOLIDATE", "Consolidation"),
            ("VALIDATE", "Validation"),
            ("PUBLISH", "Publication"),
        ),
    )


@bp.get("/classes/<int:class_id>/periods/<int:period_id>/print/<kind>")
@roles_required(RoleEnum.DIRECTION, RoleEnum.SECRETARIAT)
def print_report(class_id, period_id, kind):
    if kind not in ("bulletins", "palmares"):
        abort(404)
    from app.ui.report_assets import inline_report_logo

    theme, layout = _report_presentation()
    pdf = request.args.get("format") == "pdf"
    html = render_template(
        "portal/print.html",
        kind=kind,
        pdf=pdf,
        preview=False,
        ui_theme=theme,
        report_layout=layout,
        report_logo_url=inline_report_logo(theme.logo_url) if pdf else theme.logo_url,
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


def _report_presentation():
    from app.tenant_presentation import resolve_presentation

    return resolve_presentation()


def _editor_context(class_id, period_id):
    from app.ui.reports import COLUMN_LABELS, LABELS

    ctx = result_context(class_id, period_id)
    _, layout = _report_presentation()
    ctx.update(
        report_layout=layout,
        column_options={key: layout.labels[label] for key, label in COLUMN_LABELS.items()},
        default_labels=LABELS[layout.locale],
        custom_labels={
            key: value
            for key, value in layout.labels.items()
            if value != LABELS[layout.locale][key]
        },
    )
    return ctx


@bp.get("/classes/<int:class_id>/periods/<int:period_id>/report-template")
@roles_required(RoleEnum.DIRECTION)
def report_editor(class_id, period_id):
    return render_template("portal/report_editor.html", **_editor_context(class_id, period_id))


@bp.route("/classes/<int:class_id>/periods/<int:period_id>/report-preview", methods=["GET", "POST"])
@roles_required(RoleEnum.DIRECTION)
def report_preview(class_id, period_id):
    from app.ui.reports import ReportConfigError, build_report_layout

    ctx = result_context(class_id, period_id)
    theme, layout = _report_presentation()
    if request.method == "POST":
        try:
            configuration = {
                "locale": request.form.get("locale"),
                "orientation": request.form.get("orientation"),
                "header_alignment": request.form.get("header_alignment"),
                "font_size": int(request.form.get("font_size", "10")),
                "show_logo": "show_logo" in request.form,
                "header_lines": request.form.get("header_lines", "").splitlines(),
                "legal_text": request.form.get("legal_text", ""),
                "signatures": request.form.get("signatures", "").splitlines(),
                "columns": [value for value in request.form.getlist("column") if value],
                "labels": {
                    key[6:]: value
                    for key, value in request.form.items()
                    if key.startswith("label_") and value.strip()
                },
            }
            layout = build_report_layout(configuration)
        except (ReportConfigError, ValueError) as error:
            return render_template("portal/preview_error.html", error=str(error)), 422
    return render_template(
        "portal/print.html",
        kind="bulletins",
        preview=True,
        pdf=False,
        report_layout=layout,
        ui_theme=theme,
        report_logo_url=theme.logo_url,
        **ctx,
    )
