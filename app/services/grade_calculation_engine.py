"""Deterministic grade calculation engine.

Pure, framework-agnostic, Decimal-only arithmetic. This module has no
dependency on Flask, SQLAlchemy sessions, or HTTP — it takes plain input
data and returns plain result data, so every business rule here is
unit-testable without a database.

Pipeline:
    raw course grades
      -> compute_period_total       (weighted total for one evaluation period)
      -> compute_annual_total       (weighted aggregation across periods)
      -> rank_students               (class ranking, ties handled explicitly)
      -> decide_promotion            (pass/fail against a configurable threshold)

Business rules encoded here (confirmed with the product owner):
    - A missing grade for an expected course is EXCLUDED from both the
      numerator and the denominator of the weighted total — a student is
      graded only on the work actually submitted, until proven otherwise.
    - Ties are broken with standard competition ranking (1-2-2-4): tied
      students share a rank, and the next distinct rank skips accordingly.
    - A student with zero graded data in a period/year cannot be ranked or
      have a promotion decision made — the engine returns None / UNDETERMINED
      rather than guessing.
    - All rounding happens once, at the end, at 2 decimal places using
      ROUND_HALF_UP. Intermediate arithmetic keeps full Decimal precision to
      avoid compounding rounding error.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

PERCENT_QUANTUM = Decimal("0.01")


class InvalidGradeError(ValueError):
    """Raised when a grade input violates a structural invariant."""


class PromotionDecision(str, enum.Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNDETERMINED = "UNDETERMINED"


def quantize_percentage(value: Decimal, decimal_places: int = 2) -> Decimal:
    """Round a percentage to ``decimal_places`` using ROUND_HALF_UP.

    ``decimal_places`` is a per-tenant presentation setting (see
    ``TenantConfig.percentage_decimal_places`` /
    ``app/services/tenant_calculation.py``) — it defaults to 2 to match the
    platform-wide historical behaviour, never silently to something else.
    This must only be applied to a final, presentation-facing value —
    never to an intermediate sum used in further arithmetic.
    """
    if decimal_places == 2:
        quantum = PERCENT_QUANTUM
    else:
        quantum = Decimal(1).scaleb(-decimal_places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class CourseGradeInput:
    """One grid line's contribution to a period, for a single student.

    ``score`` is ``None`` when the grade has not been entered yet — this is
    the "missing grade" case, explicitly distinct from a score of 0.

    ``included`` is resolved by the caller from the grid (combining
    ``GrilleCoursLigne.entre_dans_total_general`` with the same flag on its
    ``GroupeCours`` — a group excluded from the general total excludes every
    line in it regardless of that line's own flag; see
    app/services/grille_service.py). This module has no knowledge of grids,
    groups, or levels — it only reacts to the booleans it's handed.

    ``is_numeric`` mirrors ``GrilleCoursLigne.note_par_appreciation`` (its
    negation): an appreciation-only line never contributes to a weighted
    numeric total, however ``included`` is set.
    """

    ligne_id: int
    groupe_id: int
    coefficient: Decimal
    max_score: Decimal | None
    score: Decimal | None
    appreciation: str | None = None
    included: bool = True
    is_numeric: bool = True


@dataclass(frozen=True)
class CourseBreakdown:
    ligne_id: int
    groupe_id: int
    weighted_points: Decimal
    weighted_possible: Decimal
    included: bool


@dataclass(frozen=True)
class GroupSubtotal:
    groupe_id: int
    weighted_points: Decimal
    weighted_possible: Decimal
    percentage: Decimal | None


@dataclass(frozen=True)
class PeriodResult:
    period_id: int
    weighted_points: Decimal
    weighted_possible: Decimal
    percentage: Decimal | None  # None => no graded course in this period
    course_breakdown: tuple[CourseBreakdown, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PeriodContribution:
    """A period's result paired with its configured weight for annual
    aggregation (weight comes from EvaluationPeriod.weight_percent — never
    hard-coded)."""

    period_result: PeriodResult
    weight_percent: Decimal


@dataclass(frozen=True)
class AnnualResult:
    enrollment_id: int
    total_weighted_points: Decimal
    total_weighted_possible: Decimal
    percentage: Decimal | None  # None => no graded period in the year
    period_percentages: tuple[Decimal | None, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class RankedEntry:
    enrollment_id: int
    percentage: Decimal
    rank: int | None  # None if excluded from ranking (should not happen post-sort)


def validate_course_grade(grade_input: CourseGradeInput) -> None:
    """Validate structural invariants of a single grid line's grade.

    An appreciation-only line (``is_numeric`` False) is never validated
    numerically — it has no ``max_score`` to be bound by. Raises
    InvalidGradeError for a non-positive max_score on a numeric line (a
    data integrity problem, never a valid state) or for a score outside
    [0, max_score]. A ``score`` of ``None`` (missing grade) is always
    valid — it simply means "not graded yet".
    """
    if not grade_input.is_numeric:
        return
    if grade_input.max_score is None or grade_input.max_score <= 0:
        raise InvalidGradeError(
            f"ligne {grade_input.ligne_id}: max_score must be > 0, "
            f"got {grade_input.max_score}"
        )
    if grade_input.coefficient <= 0:
        raise InvalidGradeError(
            f"ligne {grade_input.ligne_id}: coefficient must be > 0, "
            f"got {grade_input.coefficient}"
        )
    if grade_input.score is None:
        return
    if grade_input.score < 0 or grade_input.score > grade_input.max_score:
        raise InvalidGradeError(
            f"ligne {grade_input.ligne_id}: score {grade_input.score} out of "
            f"range [0, {grade_input.max_score}]"
        )


def compute_period_total(
    period_id: int, course_grades: list[CourseGradeInput]
) -> PeriodResult:
    """Aggregate one period's courses into a weighted total.

    Missing grades (score is None) are excluded from both numerator and
    denominator. Courses are still validated defensively even though
    validate_course_grade should already have run at entry time.
    """
    weighted_points = Decimal(0)
    weighted_possible = Decimal(0)
    breakdown: list[CourseBreakdown] = []

    for course_grade in course_grades:
        validate_course_grade(course_grade)

        contributes = (
            course_grade.included
            and course_grade.is_numeric
            and course_grade.score is not None
        )
        if not contributes:
            breakdown.append(
                CourseBreakdown(
                    ligne_id=course_grade.ligne_id,
                    groupe_id=course_grade.groupe_id,
                    weighted_points=Decimal(0),
                    weighted_possible=Decimal(0),
                    included=False,
                )
            )
            continue

        course_weighted_points = course_grade.score * course_grade.coefficient
        course_weighted_possible = course_grade.max_score * course_grade.coefficient

        weighted_points += course_weighted_points
        weighted_possible += course_weighted_possible
        breakdown.append(
            CourseBreakdown(
                ligne_id=course_grade.ligne_id,
                groupe_id=course_grade.groupe_id,
                weighted_points=course_weighted_points,
                weighted_possible=course_weighted_possible,
                included=True,
            )
        )

    percentage = None
    if weighted_possible > 0:
        percentage = (weighted_points / weighted_possible) * Decimal(100)

    return PeriodResult(
        period_id=period_id,
        weighted_points=weighted_points,
        weighted_possible=weighted_possible,
        percentage=percentage,
        course_breakdown=tuple(breakdown),
    )


def compute_group_subtotals(
    course_breakdown: tuple[CourseBreakdown, ...],
) -> tuple[GroupSubtotal, ...]:
    """Roll a period's line-level breakdown up into per-group subtotals,
    preserving first-seen group order. A line excluded from the general
    total (``included`` False on its ``CourseBreakdown``) never
    contributes to its group's subtotal either — exclusion at the line or
    group level in the grid propagates identically here.
    """
    totals: dict[int, tuple[Decimal, Decimal]] = {}
    order: list[int] = []
    for entry in course_breakdown:
        if not entry.included:
            continue
        if entry.groupe_id not in totals:
            totals[entry.groupe_id] = (Decimal(0), Decimal(0))
            order.append(entry.groupe_id)
        points, possible = totals[entry.groupe_id]
        totals[entry.groupe_id] = (
            points + entry.weighted_points,
            possible + entry.weighted_possible,
        )

    subtotals = []
    for groupe_id in order:
        points, possible = totals[groupe_id]
        percentage = (points / possible) * Decimal(100) if possible > 0 else None
        subtotals.append(
            GroupSubtotal(
                groupe_id=groupe_id,
                weighted_points=points,
                weighted_possible=possible,
                percentage=percentage,
            )
        )
    return tuple(subtotals)


def compute_annual_total(
    enrollment_id: int, contributions: list[PeriodContribution]
) -> AnnualResult:
    """Aggregate periods into an annual result, weighted by each period's
    configured weight_percent, renormalized over periods that have data.

    A period with no graded courses (percentage is None) is excluded from
    both the weighted sum and the renormalization denominator — consistent
    with the "judge only on available work" policy applied within a period.
    """
    weighted_sum = Decimal(0)
    weight_total = Decimal(0)
    period_percentages: list[Decimal | None] = []

    for contribution in contributions:
        period_percentages.append(contribution.period_result.percentage)
        if contribution.period_result.percentage is None:
            continue
        weighted_sum += contribution.period_result.percentage * contribution.weight_percent
        weight_total += contribution.weight_percent

    percentage = None
    if weight_total > 0:
        percentage = weighted_sum / weight_total

    return AnnualResult(
        enrollment_id=enrollment_id,
        total_weighted_points=weighted_sum,
        total_weighted_possible=weight_total,
        percentage=percentage,
        period_percentages=tuple(period_percentages),
    )


def rank_students(entries: list[tuple[int, Decimal | None]]) -> list[RankedEntry]:
    """Rank students by percentage, descending, using standard competition
    ranking (1-2-2-4): tied students share a rank, and the following rank
    skips to reflect how many students are ahead.

    ``entries`` is a list of (enrollment_id, percentage_or_None). Students
    with percentage None (no graded data at all) are excluded from the
    returned ranking entirely — they cannot be meaningfully ranked.
    """
    rankable = [(eid, pct) for eid, pct in entries if pct is not None]
    rankable.sort(key=lambda item: item[1], reverse=True)

    ranked: list[RankedEntry] = []
    previous_percentage: Decimal | None = None
    previous_rank = 0
    for index, (enrollment_id, percentage) in enumerate(rankable, start=1):
        if previous_percentage is not None and percentage == previous_percentage:
            rank = previous_rank
        else:
            rank = index
        ranked.append(
            RankedEntry(enrollment_id=enrollment_id, percentage=percentage, rank=rank)
        )
        previous_percentage = percentage
        previous_rank = rank

    return ranked


def decide_promotion(
    annual_result: AnnualResult, threshold_percent: Decimal
) -> PromotionDecision:
    """Compare the annual percentage to a configurable pass threshold.

    Returns UNDETERMINED — never a silent PASS or FAIL — when there is not
    enough graded data to compute a percentage.
    """
    if annual_result.percentage is None:
        return PromotionDecision.UNDETERMINED
    if annual_result.percentage >= threshold_percent:
        return PromotionDecision.PASS
    return PromotionDecision.FAIL
