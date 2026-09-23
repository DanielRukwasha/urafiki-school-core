from types import SimpleNamespace as NS

from flask import render_template

from app.ui.reports import build_report_layout
from app.ui.theming import build_theme


def test_descriptive_report_template_loops_server_structure_without_arithmetic(app):
    document = {
        "density": "compact",
        "title": "Server title",
        "course_label": "Server course",
        "period_columns": [{"label": "P1"}, {"label": "Exam"}],
        "learners": [
            {
                "identity": {"label": "Learner", "reference": "ID-1"},
                "period_label": "Server period",
                "groups": [
                    {
                        "label": "Server group",
                        "included": False,
                        "exclusion_label": "Not counted",
                        "lines": [
                            {
                                "label": "Appreciation course",
                                "included": False,
                                "periods": [{"appreciation": "Excellent", "maximum": None}, {"display": "—"}],
                                "total": None,
                            }
                        ],
                        "subtotal": None,
                    }
                ],
                "synthesis": [{"label": "Server summary", "value": "Server value"}],
                "notes": ["Server note"],
            }
        ],
        "ranking": {"title": "Ranking", "columns": [], "rows": [], "notes": []},
    }
    with app.test_request_context():
        html = render_template(
            "portal/print.html",
            kind="bulletins",
            pdf=False,
            preview=True,
            report_document=document,
            report_layout=build_report_layout(),
            ui_theme=build_theme({"display_name": "Tenant"}),
            report_logo_url=None,
            klass=NS(id=1, name="Class", academic_year=NS(label="Year")),
            period=NS(id=1, name="Period"),
        )
    assert "Server group" in html
    assert "Excellent" in html
    assert "Not counted" in html
    assert "Server value" in html
