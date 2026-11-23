"""Interface invariants, executed by the existing required CI test job."""

import ast
import base64
import hashlib
import json
import re
import unicodedata
from pathlib import Path

from jinja2 import Environment, nodes

from app.ui.theming import build_theme, contrast, contrast_pairs

ROOT = Path(__file__).parents[2]


def normalized(value):
    return "".join(
        char for char in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(char)
    )


def test_no_fixture_school_course_or_level_names_in_interface():
    # Derive named identities from fixture data, not from a growing product list.
    examples = json.loads((ROOT / "tests/fixtures/tenant_presentations.json").read_text(encoding="utf-8-sig"))
    identities = {entry["branding"]["display_name"] for entry in examples.values()}
    for path in (ROOT / "tests").rglob("*.py"):
        for call in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if not isinstance(call, ast.Call):
                continue
            name = getattr(call.func, "id", "")
            if name not in {"Institution", "Course", "SchoolClass", "Niveau"}:
                continue
            for argument in call.keywords:
                if argument.arg in {"name", "nom", "domain", "short_code"} and isinstance(argument.value, ast.Constant):
                    if isinstance(argument.value.value, str):
                        identities.add(argument.value.value)
    for folder in ("app/templates", "app/static"):
        for path in (ROOT / folder).rglob("*"):
            if path.is_file() and path.suffix in {".html", ".css", ".js", ".svg", ".json"}:
                source = normalized(path.read_text(encoding="utf-8-sig"))
                for identity in identities:
                    assert not re.search(r"(?<!\w)" + re.escape(normalized(identity)) + r"(?!\w)", source), (path, identity)


def test_no_business_arithmetic_in_templates():
    env = Environment()
    for path in (ROOT / "app/templates").rglob("*.html"):
        tree = env.parse(path.read_text())
        for operation in tree.find_all(nodes.BinExpr):
            attributes = {item.attr for item in operation.find_all(nodes.Getattr)}
            assert not attributes.intersection({"score", "coefficient", "weighted_points", "weighted_possible", "percentage", "rank"}), (path, operation.lineno)


def test_two_deliberately_different_tenant_palettes_have_aa_contrast(tmp_path):
    examples = json.loads((ROOT / "tests/fixtures/tenant_presentations.json").read_text(encoding="utf-8-sig"))
    evidence = {}
    for slug, sample in examples.items():
        theme = build_theme(sample["branding"])
        ratios = [contrast(fg, bg) for fg, bg, _ in contrast_pairs(theme)]
        for (fg, bg, minimum), ratio in zip(contrast_pairs(theme), ratios, strict=True):
            assert ratio >= minimum, (slug, fg, bg, ratio, minimum)
        evidence[slug] = {"primary_requested": sample["branding"]["primary_color"], "primary_used": theme.tokens["primary"], "adjustments": theme.adjustments, "pairs": [{"foreground": fg, "background": bg, "ratio": contrast(fg, bg), "minimum": minimum} for fg, bg, minimum in contrast_pairs(theme)]}
    assert examples["rivage"]["branding"]["primary_color"] == "#ffff00"
    assert evidence["rivage"]["adjustments"]
    output = ROOT / "tmp/portal-review"
    output.mkdir(parents=True, exist_ok=True)
    (output / "contrast-ratios.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2))


def test_bootstrap_is_local_and_matches_official_integrity():
    content = (ROOT / "app/static/vendor/bootstrap-5.3.8.min.css").read_bytes()
    assert base64.b64encode(hashlib.sha384(content).digest()).decode() == "sRIl4kxILFvY47J16cr9ZwB07vP4J8+LH7qKQnuqkuIAvNWLzeN8tE5YBujZqJLB"
    assert "vendor/bootstrap-5.3.8.min.css" in (ROOT / "app/templates/base.html").read_text()

