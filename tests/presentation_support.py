"""Fictitious presentation fixtures, not a production tenant resolver."""

import base64
import json
import shutil
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from flask import render_template, request

from app.ui.reports import build_report_layout
from app.ui.theming import build_theme

EXAMPLES = json.loads(
    (Path(__file__).parent / "fixtures" / "tenant_presentations.json").read_text(
        encoding="utf-8-sig"
    )
)


def report_context(slug, count=2):
    sample = EXAMPLES[slug]
    maximum = Decimal("20") if slug == "rivage" else Decimal("100")
    courses = [
        NS(id=1, name="Analyse", code="ANA", coefficient=Decimal("2"), max_score=maximum),
        NS(id=2, name="Expression", code="EXP", coefficient=Decimal("1"), max_score=maximum),
    ]
    rows, grades = [], {}
    for index in range(count):
        score = maximum * Decimal("0.75")
        enrollment = NS(
            id=index + 1,
            student=NS(full_name=f"Camille Exemple {index + 1}", matricule=f"S-{index + 1:03}"),
        )
        total = NS(weighted_points=score * 3, weighted_possible=maximum * 3)
        rows.append(NS(enrollment=enrollment, entered=2, total=total, percentage=Decimal("75")))
        for course in courses:
            grades[(enrollment.id, course.id)] = NS(score=score)
    return dict(
        klass=NS(id=1, name="Classe A", academic_year=NS(label="2026-2027")),
        period=NS(id=1, name=sample["period"]),
        courses=courses,
        rows=rows,
        grades=grades,
        ranks={row.enrollment.id: 1 for row in rows},
    )


@pytest.fixture()
def branded_app(app, tmp_path):
    Image = pytest.importorskip("PIL.Image")
    ImageDraw = pytest.importorskip("PIL.ImageDraw")

    static = tmp_path / "static"
    shutil.copytree(app.static_folder, static)
    app.static_folder = str(static)
    folder = static / "tenant-test"
    folder.mkdir()
    for slug, fill in (("rivage", "#a06000"), ("horizon", "#2563eb")):
        logo = Image.new("RGB", (64, 64), "white")
        draw = ImageDraw.Draw(logo)
        if slug == "rivage":
            draw.ellipse((4, 4, 60, 60), fill=fill)
        else:
            draw.rectangle((8, 8, 56, 56), fill=fill)
        logo.save(folder / f"{slug}.png")

    @app.context_processor
    def fixture_presentation():
        slug = "horizon" if request.host.startswith("horizon") else "rivage"
        sample = EXAMPLES[slug]
        return {
            "ui_theme": build_theme(sample["branding"]),
            "report_layout": build_report_layout(sample["report"]),
        }

    @app.get("/_test/report")
    def fixture_report():
        slug = "horizon" if request.host.startswith("horizon") else "rivage"
        return render_template(
            "portal/print.html",
            **report_context(slug),
            kind="bulletins",
            preview=True,
            pdf=False,
            report_logo_url=EXAMPLES[slug]["branding"]["logo_url"],
        )

    return app


def embedded_fixture_logo(app, slug):
    path = Path(app.static_folder) / "tenant-test" / f"{slug}.png"
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")
