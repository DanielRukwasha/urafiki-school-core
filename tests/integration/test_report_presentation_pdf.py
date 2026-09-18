import io
import os
from pathlib import Path

import pytest
from flask import render_template

from app.ui.report_assets import inline_report_logo
from app.ui.reports import build_report_layout
from app.ui.theming import build_theme
from tests import presentation_support
from tests.presentation_support import EXAMPLES, report_context  # noqa: F401

branded_app = presentation_support.branded_app


@pytest.mark.parametrize("slug", ["rivage", "horizon"])
def test_configured_reports_keep_branding_language_and_a4(branded_app, slug):
    try:
        from pypdf import PdfReader
        from weasyprint import HTML
    except (ImportError, OSError) as error:
        if os.environ.get("REQUIRE_PDF"):
            pytest.fail(str(error))
        pytest.skip("Native PDF dependencies are optional locally")
    sample = EXAMPLES[slug]
    with branded_app.test_request_context(f"http://{slug}.localhost/"):
        logo = inline_report_logo(sample["branding"]["logo_url"])
        assert logo.startswith("data:image/png;base64,")
        html = render_template(
            "portal/print.html",
            **report_context(slug),
            ui_theme=build_theme(sample["branding"]),
            report_layout=build_report_layout(sample["report"]),
            report_logo_url=logo,
            kind="bulletins",
            pdf=True,
            preview=True,
        )
        content = HTML(string=html).write_pdf()
    reader = PdfReader(io.BytesIO(content))
    assert len(reader.pages) == 2
    for page in reader.pages:
        width, height = float(page.mediabox.width), float(page.mediabox.height)
        assert abs(min(width, height) - 595.28) < 1
        assert abs(max(width, height) - 841.89) < 1
        assert (width > height) == (slug == "horizon")
        text = page.extract_text()
        assert sample["branding"]["display_name"] in text
        assert sample["period"] in text
        assert build_report_layout(sample["report"]).labels["preview"] in text
        assert (
            EXAMPLES["horizon" if slug == "rivage" else "rivage"]["branding"]["display_name"]
            not in text
        )
    output = Path("tmp/portal-review")
    output.mkdir(parents=True, exist_ok=True)
    (output / f"{slug}-configured.pdf").write_bytes(content)
