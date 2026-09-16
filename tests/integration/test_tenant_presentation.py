"""Presentation contract tests; backend host resolution is tested after integration."""

import json
from pathlib import Path

import pytest
from flask import request

from app.ui.access import access_notice
from app.ui.reports import build_report_layout
from app.ui.theming import build_theme

EXAMPLES = json.loads(
    (Path(__file__).parents[1] / "fixtures/tenant_presentations.json").read_text(
        encoding="utf-8-sig"
    )
)


@pytest.fixture()
def example_presentations(app):
    @app.context_processor
    def fixture_context():
        sample = EXAMPLES["horizon" if request.host.startswith("horizon") else "rivage"]
        return {
            "ui_theme": build_theme(sample["branding"]),
            "report_layout": build_report_layout(sample["report"]),
        }

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
    client, db, make_user, course, enrollment, evaluation_period
):
    from app.models.grading import Grade
    from app.models.user import RoleEnum

    user, password = make_user(role=RoleEnum.DIRECTION)
    client.post("/auth/login", data={"email": user.email, "password": password})
    prefix = f"/portal/classes/{course.school_class_id}/periods/{evaluation_period.id}"
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
    client, make_user, course, enrollment, evaluation_period
):
    from app.models.user import RoleEnum

    user, password = make_user(role=RoleEnum.DIRECTION)
    client.post("/auth/login", data={"email": user.email, "password": password})
    response = client.post(
        f"/portal/classes/{course.school_class_id}/periods/{evaluation_period.id}/report-preview",
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
    client, make_user, course, enrollment, evaluation_period
):
    user, password = make_user()
    client.post("/auth/login", data={"email": user.email, "password": password})
    prefix = f"/portal/classes/{course.school_class_id}/periods/{evaluation_period.id}"
    assert client.get(prefix + "/report-template").status_code == 403
    assert client.get(prefix + "/report-preview").status_code == 403
