import json
import random
import re
from pathlib import Path

import pytest

from app.ui.reports import ReportConfigError, build_report_layout
from app.ui.theming import build_theme, contrast, contrast_pairs, safe_asset_url

FIXTURES = Path(__file__).parents[1] / "fixtures" / "tenant_presentations.json"


def test_extreme_and_random_palettes_meet_wcag_aa():
    samples = ["#ffffff", "#ffff00", "#000000", "#ff0000", "#00ff00", "#0000ff", "#777777"]
    rng = random.Random(913)
    samples += [f"#{rng.randrange(0x1000000):06x}" for _ in range(150)]
    for value in samples:
        theme = build_theme({"primary_color": value, "accent_color": value, "neutral_color": value})
        assert all(
            contrast(foreground, background) >= minimum
            for foreground, background, minimum in contrast_pairs(theme)
        ), value


def test_incomplete_and_malicious_theme_uses_safe_fallbacks():
    theme = build_theme(
        {"primary_color": "red; } body {display:none", "display_name": None, "locale": "xx"}
    )
    assert theme.name == "Portail scolaire"
    assert theme.locale == "fr"
    assert all(re.fullmatch(r"#[0-9a-f]{6}", value) for value in theme.tokens.values())
    assert build_theme({"primary_color": "#ffff00"}).adjustments


@pytest.mark.parametrize(
    "url",
    [
        "https://other.test/logo.png",
        "//other.test/logo.png",
        "data:image/svg+xml,x",
        "javascript:alert(1)",
        "/%2e%2e/private",
        "/a/%252e%252e/secret",
        "/a\\b",
        "/a?x=1",
    ],
)
def test_unsafe_assets_are_not_exposed(url):
    assert safe_asset_url(url) is None


def test_same_origin_asset_is_supported():
    assert (
        safe_asset_url("/static/tenant-assets/123/logo.png") == "/static/tenant-assets/123/logo.png"
    )


def test_no_school_identity_or_literal_palette_in_templates_and_styles():
    examples = json.loads(FIXTURES.read_text(encoding="utf-8-sig"))
    names = [entry["branding"]["display_name"] for entry in examples.values()] + [
        "Institut Mont Carmel"
    ]
    root = Path(__file__).parents[2]
    for folder in ("app/templates", "app/static/css", "app/static/js"):
        for path in (root / folder).rglob("*"):
            if not path.is_file():
                continue
            source = path.read_text(encoding="utf-8-sig")
            assert not any(name.casefold() in source.casefold() for name in names), path
            if path.suffix in {".css", ".html"}:
                assert not re.search(r"#[0-9a-fA-F]{3,8}\b", source), path


@pytest.mark.parametrize(
    "config",
    [
        {"columns": ["course", "course", "score"]},
        {"columns": ["course", "bad"]},
        {"columns": [{"x": 1}]},
        {"signatures": ["one"] * 5},
        {"orientation": "portrait; color:red"},
        {"font_size": 3},
    ],
)
def test_report_configuration_rejects_unsafe_or_unreadable_layouts(config):
    with pytest.raises(ReportConfigError):
        build_report_layout(config)


def test_report_preview_marking_cannot_be_removed():
    layout = build_report_layout({"labels": {"preview": ""}})
    assert layout.labels["preview"] == "APERÇU - NON OFFICIEL"
