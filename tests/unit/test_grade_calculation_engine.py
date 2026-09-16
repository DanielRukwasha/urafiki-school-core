from decimal import Decimal

import pytest

from app.services.grade_calculation_engine import (
    CourseGradeInput,
    InvalidGradeError,
    PeriodContribution,
    PromotionDecision,
    compute_annual_total,
    compute_period_total,
    decide_promotion,
    quantize_percentage,
    rank_students,
    validate_course_grade,
)


def cg(course_id, coefficient="1", max_score="20", score="10"):
    return CourseGradeInput(
        course_id=course_id,
        coefficient=Decimal(coefficient),
        max_score=Decimal(max_score),
        score=Decimal(score) if score is not None else None,
    )


class TestValidateCourseGrade:
    def test_valid_grade_passes(self):
        validate_course_grade(cg(1, score="15"))

    def test_missing_score_is_valid(self):
        validate_course_grade(cg(1, score=None))

    def test_negative_score_rejected(self):
        with pytest.raises(InvalidGradeError):
            validate_course_grade(cg(1, score="-1"))

    def test_score_above_max_rejected(self):
        with pytest.raises(InvalidGradeError):
            validate_course_grade(cg(1, max_score="20", score="20.5"))

    def test_zero_max_score_rejected(self):
        with pytest.raises(InvalidGradeError):
            validate_course_grade(cg(1, max_score="0", score=None))

    def test_zero_coefficient_rejected(self):
        with pytest.raises(InvalidGradeError):
            validate_course_grade(cg(1, coefficient="0", score="10"))


class TestComputePeriodTotal:
    def test_single_course_full_marks(self):
        result = compute_period_total(1, [cg(1, coefficient="2", max_score="20", score="20")])
        assert result.weighted_points == Decimal("40")
        assert result.weighted_possible == Decimal("40")
        assert result.percentage == Decimal("100")

    def test_missing_grade_excluded_from_both_sides(self):
        grades = [
            cg(1, coefficient="4", max_score="20", score="10"),  # 40/80
            cg(2, coefficient="2", max_score="20", score=None),  # excluded entirely
        ]
        result = compute_period_total(1, grades)
        assert result.weighted_points == Decimal("40")
        assert result.weighted_possible == Decimal("80")
        assert result.percentage == Decimal("50")
        included = {b.course_id: b.included for b in result.course_breakdown}
        assert included == {1: True, 2: False}

    def test_all_grades_missing_returns_none_percentage(self):
        grades = [cg(1, score=None), cg(2, score=None)]
        result = compute_period_total(1, grades)
        assert result.weighted_possible == Decimal("0")
        assert result.percentage is None

    def test_no_courses_at_all_returns_none(self):
        result = compute_period_total(1, [])
        assert result.percentage is None

    def test_weighted_average_across_multiple_courses(self):
        grades = [
            cg(1, coefficient="4", max_score="20", score="16"),  # 64/80
            cg(2, coefficient="2", max_score="10", score="5"),  # 10/20
        ]
        result = compute_period_total(1, grades)
        # (64+10) / (80+20) = 74/100 = 74%
        assert result.percentage == Decimal("74")


class TestComputeAnnualTotal:
    def test_two_periods_equal_weight(self):
        p1 = compute_period_total(1, [cg(1, score="20")])  # 100%
        p2 = compute_period_total(2, [cg(1, score="10")])  # 50%
        result = compute_annual_total(
            enrollment_id=99,
            contributions=[
                PeriodContribution(p1, Decimal("50")),
                PeriodContribution(p2, Decimal("50")),
            ],
        )
        assert result.percentage == Decimal("75")

    def test_period_with_no_data_excluded_and_renormalized(self):
        p1 = compute_period_total(1, [cg(1, score="20")])  # 100%
        p2 = compute_period_total(2, [])  # None
        result = compute_annual_total(
            enrollment_id=1,
            contributions=[
                PeriodContribution(p1, Decimal("50")),
                PeriodContribution(p2, Decimal("50")),
            ],
        )
        # p2 excluded -> renormalized entirely on p1 -> 100%
        assert result.percentage == Decimal("100")

    def test_no_period_has_data_returns_none(self):
        p1 = compute_period_total(1, [])
        result = compute_annual_total(
            enrollment_id=1, contributions=[PeriodContribution(p1, Decimal("100"))]
        )
        assert result.percentage is None


class TestRankStudents:
    def test_simple_descending_order(self):
        ranked = rank_students([(1, Decimal("80")), (2, Decimal("90")), (3, Decimal("70"))])
        assert [(r.enrollment_id, r.rank) for r in ranked] == [(2, 1), (1, 2), (3, 3)]

    def test_standard_competition_ranking_on_tie(self):
        # 18, 15, 15, 12 -> ranks 1, 2, 2, 4
        ranked = rank_students(
            [(1, Decimal("18")), (2, Decimal("15")), (3, Decimal("15")), (4, Decimal("12"))]
        )
        ranks = {r.enrollment_id: r.rank for r in ranked}
        assert ranks == {1: 1, 2: 2, 3: 2, 4: 4}

    def test_three_way_tie(self):
        ranked = rank_students(
            [(1, Decimal("10")), (2, Decimal("10")), (3, Decimal("10")), (4, Decimal("5"))]
        )
        ranks = {r.enrollment_id: r.rank for r in ranked}
        assert ranks == {1: 1, 2: 1, 3: 1, 4: 4}

    def test_students_without_data_excluded_from_ranking(self):
        ranked = rank_students([(1, Decimal("80")), (2, None)])
        assert len(ranked) == 1
        assert ranked[0].enrollment_id == 1

    def test_single_student_class(self):
        ranked = rank_students([(1, Decimal("60"))])
        assert ranked[0].rank == 1


class TestDecidePromotion:
    def test_above_threshold_passes(self):
        p1 = compute_period_total(1, [cg(1, score="16")])  # 80%
        annual = compute_annual_total(1, [PeriodContribution(p1, Decimal("100"))])
        assert decide_promotion(annual, Decimal("50")) == PromotionDecision.PASS

    def test_exactly_at_threshold_passes(self):
        p1 = compute_period_total(1, [cg(1, score="10")])  # 50%
        annual = compute_annual_total(1, [PeriodContribution(p1, Decimal("100"))])
        assert decide_promotion(annual, Decimal("50")) == PromotionDecision.PASS

    def test_below_threshold_fails(self):
        p1 = compute_period_total(1, [cg(1, score="9")])  # 45%
        annual = compute_annual_total(1, [PeriodContribution(p1, Decimal("100"))])
        assert decide_promotion(annual, Decimal("50")) == PromotionDecision.FAIL

    def test_no_data_is_undetermined(self):
        p1 = compute_period_total(1, [])
        annual = compute_annual_total(1, [PeriodContribution(p1, Decimal("100"))])
        assert decide_promotion(annual, Decimal("50")) == PromotionDecision.UNDETERMINED


class TestQuantizePercentage:
    def test_rounds_half_up(self):
        assert quantize_percentage(Decimal("74.005")) == Decimal("74.01")
        assert quantize_percentage(Decimal("74.004")) == Decimal("74.00")

    def test_no_float_contamination(self):
        # Classic float trap: 0.1 + 0.2 != 0.3 in binary floats.
        value = Decimal("0.1") + Decimal("0.2")
        assert value == Decimal("0.3")
