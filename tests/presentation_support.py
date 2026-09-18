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


def _seed_example_tenants():
    """Real Institution + TenantConfig rows for every fixture school, so
    requests to `<slug>.localhost` resolve through the real
    resolve_tenant() -> app/tenant_presentation.py path instead of a
    stand-in context processor — resolve_tenant() 404s any domain with no
    matching Institution before a view or context processor ever runs."""
    from app.extensions import db
    from app.models.institution import Institution
    from app.models.platform import CalculationStrategy
    from app.models.tenant_config import TenantConfig

    if CalculationStrategy.query.filter_by(key="STANDARD").first() is None:
        db.session.add(CalculationStrategy(key="STANDARD", description="Standard."))
        db.session.commit()

    for slug, sample in EXAMPLES.items():
        branding, report = sample["branding"], sample["report"]
        institution = Institution(
            name=branding["display_name"],
            short_code=slug.upper(),
            domain=f"{slug}.localhost",
            locale=branding["locale"],
        )
        db.session.add(institution)
        db.session.commit()
        db.session.add(
            TenantConfig(
                ecole_id=institution.id,
                calculation_strategy_key="STANDARD",
                percentage_decimal_places=2,
                mentions=[],
                eliminatory_course_codes=[],
                report_signatures=report.get("signatures", []),
                feature_flags={},
                primary_color=branding.get("primary_color"),
                logo_url=branding.get("logo_url"),
                report_header=next(iter(report.get("header_lines", [])), None),
                report_legal_mentions=report.get("legal_text"),
            )
        )
        db.session.commit()


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

    _seed_example_tenants()

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
