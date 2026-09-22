"""Presentation contract tests, including real per-domain tenant resolution
(app/tenant_presentation.py) now that the multi-tenant backend is merged."""

import json
from pathlib import Path

import pytest

from app.ui.access import access_notice

EXAMPLES = json.loads(
    (Path(__file__).parents[1] / "fixtures/tenant_presentations.json").read_text(
        encoding="utf-8-sig"
    )
)


@pytest.fixture()
def example_presentations(db, calculation_strategy_standard):
    """A real Institution + TenantConfig per fixture school, each on its
    own domain — so the assertions below exercise the actual
    resolve_tenant() -> app/tenant_presentation.py adapter path, not a
    stand-in context processor."""
    from app.models.institution import Institution
    from app.models.tenant_config import TenantConfig

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
    return EXAMPLES


def test_login_renders_only_current_identity(client, example_presentations):
    for slug, example in example_presentations.items():
        response = client.get(f"http://{slug}.localhost/auth/login")
        html = response.get_data(as_text=True)
        other = example_presentations["rivage" if slug == "horizon" else "horizon"]
        assert example["branding"]["display_name"] in html
        assert example["branding"]["logo_url"] in html
        assert other["branding"]["display_name"] not in html
        assert other["branding"]["logo_url"] not in html
        assert "<select" not in html
        assert '<html lang="fr">' in html
        assert f'lang="{example["branding"]["locale"]}"' in html


@pytest.mark.parametrize(
    "code",
    [
        "invalid_credentials",
        "account_suspended",
        "tenant_unknown",
        "tenant_suspended",
        "rate_limited",
    ],
)
def test_access_states_are_explicit_and_accessible(app, client, code):
    @app.context_processor
    def access_fixture():
        return {"access_notice": access_notice(code, 60 if code == "rate_limited" else None)}

    html = client.get("/auth/login").get_data(as_text=True)
    assert f'data-access-state="{code}"' in html
    assert 'role="alert"' in html
    assert ('id="password"' in html) == (code == "invalid_credentials")
    if code == "rate_limited":
        assert "60 secondes" in html


def test_report_editor_preview_does_not_publish(
    client, db, make_user, school_class, grille_ligne, enrollment, evaluation_period
):
    from app.models.grading import Grade
    from app.models.user import RoleEnum

    user, password = make_user(role=RoleEnum.DIRECTION)
    client.post("/auth/login", data={"email": user.email, "password": password})
    prefix = f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}"
    response = client.get(prefix + "/report-template")
    assert response.status_code == 200
    assert b'title="Aper' in response.data
    response = client.post(
        prefix + "/report-preview",
        data={
            "locale": "en",
            "orientation": "portrait",
            "font_size": "10",
            "header_alignment": "left",
            "column": ["course", "score"],
            "label_bulletin_title": "Custom progress report",
            "legal_text": "<script>alert(1)</script>",
            "signatures": "Head of school",
        },
    )
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Custom progress report" in html
    assert "PREVIEW - NOT OFFICIAL" in html
    assert "&lt;script&gt;" in html and "<script>alert" not in html
    assert Grade.query.count() == 0


def test_preview_rejects_duplicate_columns(
    client, make_user, school_class, grille_ligne, enrollment, evaluation_period
):
    from app.models.user import RoleEnum

    user, password = make_user(role=RoleEnum.DIRECTION)
    client.post("/auth/login", data={"email": user.email, "password": password})
    response = client.post(
        f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}/report-preview",
        data={
            "locale": "fr",
            "orientation": "portrait",
            "font_size": "10",
            "header_alignment": "left",
            "column": ["course", "course", "score"],
        },
    )
    assert response.status_code == 422
    assert b'role="alert"' in response.data


def test_teacher_cannot_edit_or_preview_template(
    client, make_user, school_class, grille_ligne, enrollment, evaluation_period
):
    user, password = make_user()
    client.post("/auth/login", data={"email": user.email, "password": password})
    prefix = f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}"
    assert client.get(prefix + "/report-template").status_code == 403
    assert client.get(prefix + "/report-preview").status_code == 403
