"""Real-browser checks. Install requirements-browser.txt and Chromium to run."""

import datetime
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from app.models.course import Course
from app.models.student import Enrollment, Student
from app.models.user import RoleEnum

playwright = pytest.importorskip("playwright.sync_api")


@pytest.fixture()
def browser_portal(app, db, make_user, course, enrollment, evaluation_period):
    user, password = make_user(role=RoleEnum.DIRECTION)
    db.session.add(
        Course(
            school_class_id=course.school_class_id,
            name="Sciences",
            code="SCI",
            coefficient=2,
            max_score=20,
        )
    )
    pupil = Student(matricule="TEST-002", first_name="Daniel", last_name="Mukendi")
    db.session.add(pupil)
    db.session.flush()
    db.session.add(
        Enrollment(
            student_id=pupil.id,
            school_class_id=course.school_class_id,
            academic_year_id=enrollment.academic_year_id,
            enrollment_date=datetime.date(2025, 9, 1),
        )
    )
    db.session.commit()
    app.config["WTF_CSRF_ENABLED"] = True
    Path("tmp/portal-review").mkdir(parents=True, exist_ok=True)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("dialog", lambda dialog: dialog.accept())
        base = f"http://127.0.0.1:{server.server_port}"
        page.goto(base + "/auth/login")
        page.locator("#email").fill(user.email)
        page.locator("#password").fill(password)
        page.locator('input[type="submit"]').click()
        page.wait_for_url("**/portal/")
        path = f"/portal/classes/{course.school_class_id}/periods/{evaluation_period.id}"
        page.goto(base + path + "/grid")
        page.wait_for_function(
            "document.querySelector('.grade-input') && !document.querySelector('.grade-input').disabled"
        )
        yield page, context, base, path
        context.close()
        browser.close()
        assert not errors
    server.shutdown()
    thread.join(timeout=5)


def test_save_validation_keyboard_and_mobile(browser_portal):
    page, _, _, _ = browser_portal
    cells = page.locator(".grade-input")
    cells.nth(0).fill("12")
    playwright.expect(page.locator(".cell-status").nth(0)).to_have_text("Enregistré sur le serveur")
    cells.nth(0).press("ArrowDown")
    playwright.expect(cells.nth(2)).to_be_focused()
    cells.nth(2).press("Tab")
    playwright.expect(cells.nth(3)).to_be_focused()
    cells.nth(0).fill("99")
    playwright.expect(cells.nth(0)).to_have_attribute("aria-invalid", "true")
    cells.nth(0).fill("14,5")
    playwright.expect(page.locator(".cell-status").nth(0)).to_have_text("Enregistré sur le serveur")
    assert (
        page.evaluate("Object.keys(localStorage).filter(k => k.startsWith('urafiki:')).length") == 0
    )
    for index in range(cells.count()):
        assert cells.nth(index).evaluate("(e) => e.labels.length > 0")
    output = Path("tmp/portal-review")
    output.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(output / "grid-desktop.png"), full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    page.screenshot(path=str(output / "grid-mobile.png"), full_page=True)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), page.evaluate(
        "({width:innerWidth,doc:document.documentElement.scrollWidth,items:[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>innerWidth && !e.closest('.table-wrap')).map(e=>[e.tagName,e.className,e.getBoundingClientRect().right])})"
    )
    page.screenshot(path=str(output / "grid-mobile.png"), full_page=True)


def test_offline_draft_survives_reload_and_reconnect(browser_portal):
    page, context, _, _ = browser_portal
    cell = page.locator(".grade-input").first
    context.set_offline(True)
    cell.fill("16")
    playwright.expect(page.locator(".cell-status").first).to_have_text("Brouillon local")
    assert page.evaluate("Object.keys(localStorage).some(k => k.startsWith('urafiki:'))")
    page.route("**/sync", lambda route: route.abort())
    context.set_offline(False)
    page.reload()
    playwright.expect(cell).to_have_value("16")
    page.unroute("**/sync")
    page.locator("#retry-sync").click()
    playwright.expect(page.locator(".cell-status").first).to_have_text("Enregistré sur le serveur")


def test_edit_during_save_keeps_newer_value(browser_portal):
    page, _, _, _ = browser_portal
    first_request = True

    def intercept(route):
        nonlocal first_request
        response = route.fetch()
        if first_request:
            first_request = False
            page.locator(".grade-input").first.fill("18")
        route.fulfill(response=response)

    page.route("**/sync", intercept)
    page.locator(".grade-input").first.fill("10")
    playwright.expect(page.locator(".cell-status").first).to_have_text("Enregistré sur le serveur")
    page.reload()
    playwright.expect(page.locator(".grade-input").first).to_have_value("18.00")


def test_failed_request_keeps_draft_and_marks_cell(browser_portal):
    page, _, _, _ = browser_portal
    page.route("**/sync", lambda route: route.fulfill(status=400, body="Expired CSRF"))
    page.locator(".grade-input").first.fill("11")
    playwright.expect(page.locator(".grade-input").first).to_have_attribute("aria-invalid", "true")
    assert page.evaluate("Object.keys(localStorage).some(k => k.startsWith('urafiki:'))")
    playwright.expect(page.locator("#storage-warning")).to_be_visible()


def test_results_and_print_preview(browser_portal):
    page, _, base, path = browser_portal
    page.locator(".grade-input").first.fill("12")
    playwright.expect(page.locator(".cell-status").first).to_have_text("Enregistré sur le serveur")
    page.goto(base + path + "/results")
    playwright.expect(page.locator("h1")).to_contain_text("Résultats")
    page.screenshot(path="tmp/portal-review/results.png", full_page=True)
    page.goto(base + path + "/print/bulletins")
    playwright.expect(page.locator(".report")).to_have_count(2)
    page.screenshot(path="tmp/portal-review/bulletin-preview.png", full_page=True)


def test_reopened_tab_restores_drafts_and_blocks_competing_editor(browser_portal):
    page, context, base, path = browser_portal
    context.set_offline(True)
    page.locator(".grade-input").first.fill("17")
    page.route("**/sync", lambda route: route.abort())
    context.set_offline(False)
    other = context.new_page()
    other.goto(base + path + "/grid")
    playwright.expect(other.locator("#sync-summary")).to_contain_text("autre onglet")
    playwright.expect(other.locator(".grade-input").first).to_be_disabled()
    page.close()
    other.route("**/sync", lambda route: route.abort())
    other.reload()
    playwright.expect(other.locator(".grade-input").first).to_have_value("17")
    other.unroute("**/sync")
    other.locator("#retry-sync").click()
    playwright.expect(other.locator(".cell-status").first).to_have_text("Enregistré sur le serveur")
    other.close()


def test_storage_failure_warns_without_claiming_local_save(browser_portal):
    page, context, _, _ = browser_portal
    page.evaluate(
        "() => { Storage.prototype.setItem = () => { throw new Error('Quota exceeded'); }; }"
    )
    context.set_offline(True)
    page.locator(".grade-input").first.fill("13")
    playwright.expect(page.locator("#storage-warning")).to_contain_text(
        "Stockage local indisponible"
    )
    playwright.expect(page.locator(".cell-status").first).to_have_text("Brouillon en mémoire")
