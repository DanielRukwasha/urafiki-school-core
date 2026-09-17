from pathlib import Path

import pytest

from app.ui.consolidation import ConsolidationPayloadError, normalize_consolidation


def payload():
    return {
        "class_name": "Classe A",
        "period_name": "Semestre 1",
        "academic_year": "2026-2027",
        "courses": [{"name": "Course", "status": "incomplete"}],
        "students": [],
        "decisions": [{"student_name": "Student", "automatic_decision": "ADMITTED"}],
        "distribution": [{"label": "10-12", "count": 2, "percent": "50 %"}],
        "class_average": "12.40 %",
        "encoding_rate": "87 %",
        "students_without_grade": 1,
        "blocking_items": [],
        "publication": {"version": 2, "published": False},
    }


def test_normalizer_preserves_server_values_without_calculation():
    view = normalize_consolidation(payload())
    assert view["class_average"] == "12.40 %"
    assert view["decisions"][0]["automatic_decision"] == "ADMITTED"
    assert view["distribution"][0]["percent"] == "50 %"


@pytest.mark.parametrize(
    "broken", [{"class_name": "A"}, {"class_name": "A", "period_name": "P", "courses": "bad"}]
)
def test_invalid_server_payload_fails_closed(broken):
    with pytest.raises(ConsolidationPayloadError):
        normalize_consolidation(broken)


def test_presentation_sources_do_not_compute_metrics_in_browser():
    root = Path(__file__).parents[2]
    for folder in (root / "app/templates/portal", root / "app/static/js"):
        for path in folder.rglob("*"):
            if path.suffix not in {".html", ".js"}:
                continue
            source = path.read_text(encoding="utf-8-sig")
            assert "weighted_points +" not in source
            assert "Math.round" not in source
            assert "Math.max" not in source
            assert "compute_period_total" not in source
