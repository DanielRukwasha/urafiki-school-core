import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from tests import presentation_support
from tests.presentation_support import EXAMPLES  # noqa: F401

branded_app = presentation_support.branded_app

playwright = pytest.importorskip("playwright.sync_api")


def test_two_fictitious_presentations_and_reports(branded_app):
    server = make_server("127.0.0.1", 0, branded_app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    output = Path("tmp/portal-review")
    output.mkdir(parents=True, exist_ok=True)
    try:
        with playwright.sync_playwright() as pw:
            browser = pw.chromium.launch()
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            colors = {}
            for slug, sample in EXAMPLES.items():
                origin = f"http://{slug}.localhost:{server.server_port}"
                page.goto(origin + "/auth/login")
                playwright.expect(page.locator(".identity-large")).to_contain_text(
                    sample["branding"]["display_name"]
                )
                playwright.expect(page.locator(".tenant-logo")).to_have_js_property(
                    "naturalWidth", 64
                )
                assert page.locator("select").count() == 0
                other = EXAMPLES["horizon" if slug == "rivage" else "rivage"]
                assert other["branding"]["display_name"] not in page.content()
                assert other["branding"]["logo_url"] not in page.content()
                colors[slug] = page.locator('input[type="submit"]').evaluate(
                    "(e) => getComputedStyle(e).backgroundColor"
                )
                page.screenshot(path=str(output / f"{slug}-login-desktop.png"), full_page=True)
                page.set_viewport_size({"width": 390, "height": 844})
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.screenshot(path=str(output / f"{slug}-login-mobile.png"), full_page=True)
                page.set_viewport_size({"width": 1440, "height": 1000})
                page.goto(origin + "/_test/report")
                playwright.expect(page.locator(".preview-banner")).to_be_visible()
                playwright.expect(page.locator(".report-logo").first).to_have_js_property(
                    "naturalWidth", 64
                )
                assert sample["period"] in page.content()
                assert other["period"] not in page.content()
                page.screenshot(path=str(output / f"{slug}-report-preview.png"), full_page=True)
            assert colors["rivage"] != colors["horizon"]
            assert not errors
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)
