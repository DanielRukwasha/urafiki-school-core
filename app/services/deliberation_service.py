"""Server-owned consolidation and deliberation for one class/period —
issue #42's backend contract. The frontend (app/ui/consolidation.py,
app/blueprints/portal/routes.py) renders exactly what this module returns
and derives no metric itself.

Automatic decision, in order — each rule is a hard block, not blended
into the average:
1. No grades entered at all for the period -> MANUAL ("à délibérer"):
   nothing to decide automatically, this needs a human to look.
2. Failing (below the year's passing threshold) an eliminatory course
   (TenantConfig.eliminatory_course_codes) -> DEFERRED, regardless of the
   overall average.
3. More failing courses than TenantConfig.max_allowed_failures ->
   DEFERRED, regardless of the overall average.
4. Otherwise, the plain period percentage against
   DeliberationPolicy.passing_threshold_percent (P2's engine,
   unchanged) decides ADMITTED or DEFERRED.

A DeliberationPolicy for the class's (academic_year, section) — or a
year-wide one with no section — must exist; there is no hard-coded
fallback threshold. A missing policy is a configuration error the school
must fix, not a value this module can safely guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from flask import url_for

from app.extensions import db
from app.models.deliberation import DeliberationPolicy
from app.models.deliberation_workflow import (
    NEXT_STATUS,
    TRANSITION_ACTION_FOR_STATUS,
    DeliberationAction,
    DeliberationAuditLog,
    DeliberationOverride,
    PeriodPublication,
    PublicationStatus,
)
from app.models.grading import Grade, GradeAuditAction, GradeAuditLog
from app.models.mixins import utcnow
from app.models.student import Enrollment
from app.models.tenant_config import TenantConfig
from app.services.grade_calculation_engine import (
    CourseGradeInput,
    compute_period_total,
    quantize_percentage,
    rank_students,
)

AUTOMATIC_LABELS = {"ADMITTED": "Admis", "DEFERRED": "Ajourné", "MANUAL": "À délibérer"}
MANUAL_LABELS = {"ADMITTED": "Admis", "DEFERRED": "Ajourné"}
DISTRIBUTION_BUCKETS = ((0, 20), (20, 40), (40, 60), (60, 80), (80, 100.01))


class DeliberationConfigError(ValueError):
    """Raised when the school's configuration is too incomplete to
    deliberate safely — never silently guessed."""


class TransitionError(ValueError):
    """Raised when a consolidate/validate/publish transition is invalid
    from the workflow's current state."""


def _passing_threshold(school_class) -> Decimal:
    policy = (
        DeliberationPolicy.query.filter_by(
            academic_year_id=school_class.academic_year_id,
            section_id=school_class.section_id,
        )
        .filter(DeliberationPolicy.archived_at.is_(None))
        .first()
        or DeliberationPolicy.query.filter_by(
            academic_year_id=school_class.academic_year_id, section_id=None
        )
        .filter(DeliberationPolicy.archived_at.is_(None))
        .first()
    )
    if policy is None:
        raise DeliberationConfigError(
            f"aucune DeliberationPolicy pour l'année {school_class.academic_year_id} "
            f"(ni pour la section {school_class.section_id}, ni au niveau de l'année)"
        )
    return policy.passing_threshold_percent


def _tenant_config() -> TenantConfig | None:
    from app.models.tenant_scope import current_ecole_id

    ecole_id = current_ecole_id()
    if ecole_id is None:
        return None
    return TenantConfig.query.filter_by(ecole_id=ecole_id).first()


def _publication(school_class_id: int, period_id: int) -> PeriodPublication | None:
    return PeriodPublication.query.filter_by(
        school_class_id=school_class_id, period_id=period_id
    ).first()


@dataclass(frozen=True)
class _CourseState:
    course: object
    entered: int
    expected: int

    @property
    def complete(self) -> bool:
        return self.entered >= self.expected


def compute_class_consolidation(school_class, period, courses, enrollments) -> dict:
    """The full consolidation/deliberation payload for one class/period,
    matching `app.ui.consolidation.normalize_consolidation`'s contract
    exactly. `courses`/`enrollments` are passed in (already filtered to
    active, non-archived rows) rather than re-queried here, so the portal
    routes and this service always agree on which students/courses are in
    scope."""
    threshold = _passing_threshold(school_class)
    config = _tenant_config()
    eliminatory_codes = set(config.eliminatory_course_codes) if config else set()
    max_failures = config.max_allowed_failures if config else None

    grades = {
        (g.enrollment_id, g.course_id): g
        for g in Grade.query.filter(
            Grade.enrollment_id.in_([e.id for e in enrollments]),
            Grade.course_id.in_([c.id for c in courses]),
            Grade.period_id == period.id,
            Grade.archived_at.is_(None),
        ).all()
    }
    overrides = {
        o.enrollment_id: o
        for o in DeliberationOverride.query.filter(
            DeliberationOverride.enrollment_id.in_([e.id for e in enrollments]),
            DeliberationOverride.period_id == period.id,
        ).all()
    }

    course_states = [
        _CourseState(
            course=course,
            entered=sum(1 for e in enrollments if (e.id, course.id) in grades),
            expected=len(enrollments),
        )
        for course in courses
    ]
    course_codes = {course.id: course.code for course in courses}

    decision_rows = []
    percentages_for_average = []
    students_without_grade = 0
    for enrollment in enrollments:
        inputs = [
            CourseGradeInput(
                c.id,
                c.coefficient,
                c.max_score,
                grades[(enrollment.id, c.id)].score
                if (enrollment.id, c.id) in grades
                else None,
            )
            for c in courses
        ]
        result = compute_period_total(period.id, inputs)
        if result.percentage is None:
            students_without_grade += 1
        else:
            percentages_for_average.append(result.percentage)

        automatic, reasons = _automatic_decision(
            result, inputs, threshold, eliminatory_codes, max_failures, course_codes
        )
        override = overrides.get(enrollment.id)
        decision_rows.append(
            {
                "enrollment_id": enrollment.id,
                "student_name": enrollment.student.full_name,
                "student_id": enrollment.student.matricule,
                "total": result.weighted_points if result.percentage is not None else None,
                "percentage": quantize_percentage(result.percentage)
                if result.percentage is not None
                else None,
                "automatic_decision": automatic,
                "automatic_label": AUTOMATIC_LABELS[automatic],
                "manual_decision": override.decision.value if override else None,
                "manual_label": MANUAL_LABELS.get(override.decision.value) if override else None,
                "manual_reason": override.reason if override else None,
                "reasons": reasons,
                "override_url": url_for(
                    "portal.override_decision",
                    class_id=school_class.id,
                    period_id=period.id,
                    enrollment_id=enrollment.id,
                ),
            }
        )

    ranks = {
        r.enrollment_id: r.rank
        for r in rank_students(
            [
                (row["enrollment_id"], row["percentage"])
                for row in decision_rows
                if row["percentage"] is not None
            ]
        )
    }
    unranked = len(decision_rows) + 1
    for row in decision_rows:
        row["rank"] = ranks.get(row["enrollment_id"], unranked)
    decision_rows.sort(key=lambda row: row["rank"])

    publication = _publication(school_class.id, period.id)
    blocking_items = [
        {"label": f"{state.course.name} : {state.entered}/{state.expected} cotes saisies"}
        for state in course_states
        if not state.complete
    ]

    return {
        "class_name": school_class.name,
        "period_name": period.name,
        "academic_year": school_class.academic_year.label,
        "encoding_rate": _percent_label(
            sum(s.entered for s in course_states), sum(s.expected for s in course_states)
        ),
        "class_average": quantize_percentage(
            sum(percentages_for_average) / len(percentages_for_average)
        )
        if percentages_for_average
        else None,
        "students_without_grade": students_without_grade,
        "courses": [
            {
                "name": state.course.name,
                "encoding_rate": _percent_label(state.entered, state.expected),
                "entered": state.entered,
                "expected": state.expected,
                "status": "complete" if state.complete else "incomplete",
                "status_label": "Complet" if state.complete else "Incomplet",
            }
            for state in course_states
        ],
        "distribution": _distribution(percentages_for_average),
        "blocking_items": blocking_items,
        "decisions": decision_rows,
        "publication": {
            "status": publication.status.value if publication else PublicationStatus.DRAFT.value,
            "version": publication.version if publication else 0,
            "published": publication.published if publication else False,
        },
        "pagination": {},
    }


def _percent_label(entered: int, expected: int) -> str:
    if expected == 0:
        return "—"
    return f"{quantize_percentage(Decimal(entered) / Decimal(expected) * 100)} %"


def _distribution(percentages: list[Decimal]) -> list[dict]:
    total = len(percentages)
    buckets = []
    for low, high in DISTRIBUTION_BUCKETS:
        count = sum(1 for p in percentages if low <= p < high)
        label = f"{low:g}–{min(high, 100):g} %"
        buckets.append(
            {
                "label": label,
                "count": count,
                "percent": _percent_label(count, total) if total else "—",
            }
        )
    return buckets


def _automatic_decision(result, inputs, threshold, eliminatory_codes, max_failures, course_codes):
    if result.percentage is None:
        return "MANUAL", ["Aucune cote saisie pour cette période."]

    failing = [
        item
        for item in inputs
        if item.score is not None and (item.score / item.max_score * 100) < threshold
    ]
    eliminatory_failures = [
        item for item in failing if course_codes.get(item.course_id) in eliminatory_codes
    ]

    reasons = []
    hard_block = False
    if eliminatory_failures:
        hard_block = True
        for item in eliminatory_failures:
            reasons.append(f"Cours éliminatoire en échec : {course_codes[item.course_id]}.")
    if max_failures is not None and len(failing) > max_failures:
        hard_block = True
        reasons.append(
            f"Échecs ({len(failing)}) supérieurs au maximum toléré ({max_failures})."
        )

    if hard_block:
        return "DEFERRED", reasons
    if result.percentage >= threshold:
        return "ADMITTED", reasons
    reasons.append(
        f"Moyenne ({quantize_percentage(result.percentage)} %) inférieure au seuil ({threshold} %)."
    )
    return "DEFERRED", reasons


def apply_override(*, enrollment_id, period_id, school_class_id, decision, reason, user):
    """Record (or replace) DIRECTION's manual decision for one student.

    Refused once the period is published — a published bulletin is the
    one families already have; a later override there would silently
    contradict a document that already went out. Every prior value stays
    recoverable in DeliberationAuditLog even when replaced.
    """
    if len(reason.strip()) < 10:
        raise DeliberationConfigError("Le motif doit contenir au moins 10 caractères.")

    publication = _publication(school_class_id, period_id)
    if publication is not None and publication.published:
        raise TransitionError("Version publiée : décision manuelle impossible.")

    existing = DeliberationOverride.query.filter_by(
        enrollment_id=enrollment_id, period_id=period_id
    ).first()
    old_value = f"{existing.decision.value}: {existing.reason}" if existing else None
    new_value = f"{decision.value}: {reason}"

    if existing is not None:
        existing.decision = decision
        existing.reason = reason
        existing.decided_by_id = user.id
    else:
        db.session.add(
            DeliberationOverride(
                enrollment_id=enrollment_id,
                period_id=period_id,
                decision=decision,
                reason=reason,
                decided_by_id=user.id,
            )
        )

    db.session.add(
        DeliberationAuditLog(
            action=DeliberationAction.MANUAL_OVERRIDE,
            enrollment_id=enrollment_id,
            period_id=period_id,
            school_class_id=school_class_id,
            old_value=old_value,
            new_value=new_value,
            user_id=user.id,
        )
    )
    db.session.commit()


def apply_transition(*, school_class_id, period_id, action, user) -> PeriodPublication:
    """Advance the class/period one step: draft -> submitted ->
    consolidated -> validated -> published, strictly in order. `action` is
    one of "submit", "consolidate", "validate", "publish"; any other
    value, or a jump that skips a step, raises TransitionError rather
    than silently doing nothing or guessing what was meant. Actor
    authorization (titulaire-only for "submit", DIRECTION for the rest)
    is the route layer's job — it has the request's user and the class,
    this function only knows the workflow's own rules."""
    publication = _publication(school_class_id, period_id)
    current_status = publication.status if publication is not None else PublicationStatus.DRAFT
    expected_next = NEXT_STATUS.get(current_status)
    if expected_next is None or TRANSITION_ACTION_FOR_STATUS[expected_next] != action:
        raise TransitionError(
            f"Transition « {action} » invalide depuis l'état {current_status.value}."
        )

    if publication is None:
        publication = PeriodPublication(
            school_class_id=school_class_id,
            period_id=period_id,
            status=PublicationStatus.DRAFT,
            version=0,
        )
        db.session.add(publication)
        db.session.flush()

    old_status = publication.status
    now = utcnow()
    publication.status = expected_next
    if expected_next == PublicationStatus.SUBMITTED:
        publication.submitted_at = now
    elif expected_next == PublicationStatus.CONSOLIDATED:
        publication.consolidated_at = now
    elif expected_next == PublicationStatus.VALIDATED:
        publication.validated_at = now
    elif expected_next == PublicationStatus.PUBLISHED:
        publication.published_at = now
        publication.version += 1

    db.session.add(
        DeliberationAuditLog(
            action=DeliberationAction[action.upper()],
            period_id=period_id,
            school_class_id=school_class_id,
            old_value=old_status.value,
            new_value=expected_next.value,
            user_id=user.id,
        )
    )
    db.session.commit()
    return publication


GRADE_ACTION_LABELS = {"CREATE": "Création", "UPDATE": "Modification", "DELETE": "Suppression"}
DELIBERATION_ACTION_LABELS = {
    "MANUAL_OVERRIDE": "Décision manuelle",
    "CONSOLIDATE": "Consolidation",
    "VALIDATE": "Validation",
    "PUBLISH": "Publication",
}


def query_audit_log(*, user=None, student=None, action=None, from_date=None, to_date=None, page=1, per_page=25):
    """Merges GradeAuditLog (grade CRUD, from P2) and DeliberationAuditLog
    (overrides and publication transitions) into one time-sorted,
    filtered, paginated view — the two tables have different shapes, so
    this filters and normalizes each independently in Python rather than
    forcing a SQL UNION across them for what is, per school, a bounded
    volume of rows."""
    from datetime import datetime, time, timedelta

    entries = []

    if isinstance(from_date, str):
        from_date = datetime.combine(datetime.fromisoformat(from_date).date(), time.min)
    if isinstance(to_date, str):
        # inclusive of the whole end day, since the form only collects a date
        to_date = datetime.combine(datetime.fromisoformat(to_date).date(), time.min) + timedelta(
            days=1
        )

    action_upper = action.upper() if action else None
    if action_upper is None or action_upper in GradeAuditAction.__members__:
        grade_q = GradeAuditLog.query
        if action_upper:
            grade_q = grade_q.filter(GradeAuditLog.action == GradeAuditAction[action_upper])
        if from_date:
            grade_q = grade_q.filter(GradeAuditLog.created_at >= from_date)
        if to_date:
            grade_q = grade_q.filter(GradeAuditLog.created_at < to_date)
        for entry in grade_q.all():
            enrollment = db.session.get(Enrollment, entry.enrollment_id)
            student_name = enrollment.student.full_name if enrollment else "—"
            user_name = entry.user.full_name if entry.user else "—"
            if student and student.lower() not in student_name.lower():
                continue
            if user and user.lower() not in user_name.lower():
                continue
            entries.append(
                {
                    "created_at": entry.created_at,
                    "user_name": user_name,
                    "student_name": student_name,
                    "action_label": GRADE_ACTION_LABELS[entry.action.value],
                    "old_value": entry.old_value,
                    "new_value": entry.new_value,
                }
            )

    if action_upper is None or action_upper in DeliberationAction.__members__:
        delib_q = DeliberationAuditLog.query
        if action_upper:
            delib_q = delib_q.filter(DeliberationAuditLog.action == DeliberationAction[action_upper])
        if from_date:
            delib_q = delib_q.filter(DeliberationAuditLog.created_at >= from_date)
        if to_date:
            delib_q = delib_q.filter(DeliberationAuditLog.created_at < to_date)
        for entry in delib_q.all():
            student_name = entry.enrollment.student.full_name if entry.enrollment else "—"
            user_name = entry.user.full_name if entry.user else "—"
            if student and student.lower() not in student_name.lower():
                continue
            if user and user.lower() not in user_name.lower():
                continue
            entries.append(
                {
                    "created_at": entry.created_at,
                    "user_name": user_name,
                    "student_name": student_name,
                    "action_label": DELIBERATION_ACTION_LABELS[entry.action.value],
                    "old_value": entry.old_value,
                    "new_value": entry.new_value,
                }
            )

    entries.sort(key=lambda row: row["created_at"], reverse=True)
    total = len(entries)
    start = (page - 1) * per_page
    return entries[start : start + per_page], {
        "total": total,
        "page": page,
        "per_page": per_page,
        "has_next": start + per_page < total,
        "has_prev": page > 1,
    }
