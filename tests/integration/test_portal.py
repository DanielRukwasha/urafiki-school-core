"""Portal contracts: authorization, validation, conflicts, audit and rendering.

Out-of-scope access is a 404, never a 403 — whether it is contextual
(wrong/unassigned class or grid line) or the coarse @roles_required gate
("this role is never allowed on this endpoint at all"). The only 403 left
is the deactivated account (PERMISSIONS.md, « 403 légitimes »)."""

import json
from decimal import Decimal

import pytest

from app.models.grading import Grade, GradeAuditLog
from app.models.mixins import utcnow
from app.models.teaching import TeacherAssignment
from app.models.user import RoleEnum
from app.security.tenant import resolve_tenant


@pytest.fixture(autouse=True)
def _tenant_request_context(app, tenant_a):
    """Ambient `Model.query` calls below run outside any HTTP request —
    push a resolved request context so they see tenant_a's data, same as
    every `client.*()` call already gets via before_request. Each
    `client.*()` call still pushes and resolves its own request context on
    top of this one, so nothing here changes what the app itself sees."""
    with app.test_request_context("/", base_url=f"http://{tenant_a.domain}"):
        resolve_tenant()
        yield


@pytest.fixture()
def portal(client, db, make_user, school_class, grille_ligne, enrollment, evaluation_period):
    user, password = make_user(role=RoleEnum.DIRECTION)
    client.post("/auth/login", data={"email": user.email, "password": password})
    return {
        "url": f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}",
        "change": {"enrollment": enrollment.id, "course": grille_ligne.id, "value": "12", "base": ""},
        "user": user,
        "course": grille_ligne,
        "school_class": school_class,
        "period": evaluation_period,
    }


def save(client, portal, changes=None):
    return client.post(
        portal["url"] + "/sync",
        data={"changes": json.dumps(changes if changes is not None else [portal["change"]])},
    )


def test_all_portal_pages_render(client, portal):
    for path in [
        "/portal/",
        "/portal/assignments",
        *[
            portal["url"] + suffix
            for suffix in ["/grid", "/results", "/print/bulletins", "/print/palmares"]
        ],
    ]:
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.headers["Cache-Control"] == "no-store"


def test_save_is_audited_and_retry_is_idempotent(client, portal):
    assert save(client, portal).status_code == 200
    response = save(client, portal)
    assert response.headers["X-Grade-Sync"] == "1"
    assert Grade.query.one().score == Decimal("12")
    assert GradeAuditLog.query.count() == 1


@pytest.mark.parametrize("value", ["", "-1", "21", "NaN", "Infinity", "1.234", "1e999999", "text"])
def test_invalid_score_is_reported_in_cell(client, portal, value):
    portal["change"]["value"] = value
    response = save(client, portal)
    assert response.status_code == 422
    assert b'data-state="error"' in response.data
    assert Grade.query.count() == 0


@pytest.mark.parametrize("changes", [[], {}, [None], [{"enrollment": []}], [1] * 31])
def test_malformed_batch_is_rejected(client, portal, changes):
    # Structural issues (wrong shape/size) are 400; a dict-shaped cell that
    # simply names an out-of-scope enrollment/line lands on the 404
    # out-of-scope path instead — never 403.
    assert save(client, portal, changes).status_code in [400, 404]
    assert Grade.query.count() == 0


def test_entire_batch_authorized_before_writing(client, portal):
    changes = [portal["change"], {**portal["change"], "enrollment": 9999}]
    assert save(client, portal, changes).status_code == 404
    assert Grade.query.count() == 0


def test_duplicate_cells_rejected(client, portal):
    assert save(client, portal, [portal["change"], portal["change"]]).status_code == 400
    assert Grade.query.count() == 0


def test_stale_score_cannot_overwrite_server(client, portal):
    save(client, portal)
    portal["change"]["value"] = "15"
    assert save(client, portal).status_code == 422
    assert Grade.query.one().score == Decimal("12")
    portal["change"]["base"] = "12.00"
    assert save(client, portal).status_code == 200
    assert Grade.query.one().score == Decimal("15")
    assert GradeAuditLog.query.count() == 2


@pytest.mark.parametrize("lock", ["is_validated", "archived_at"])
def test_locked_grades_cannot_be_changed(client, db, portal, lock):
    save(client, portal)
    grade = Grade.query.one()
    setattr(grade, lock, True if lock == "is_validated" else utcnow())
    db.session.commit()
    portal["change"].update(value="14", base="12.00")
    assert save(client, portal).status_code == 422
    assert Grade.query.one().score == Decimal("12")
    assert b'data-locked="true"' in client.get(portal["url"] + "/grid").data


def test_teacher_only_sees_assigned_courses(client, db, portal, make_user):
    teacher, password = make_user(email="teacher@example.com")
    client.get("/auth/logout")
    client.post("/auth/login", data={"email": teacher.email, "password": password})
    # No assignment yet: an ENSEIGNANT with zero visible lines in this
    # class gets a 404 (contextual, out of scope), not 403.
    assert client.get(portal["url"] + "/grid").status_code == 404
    db.session.add(
        TeacherAssignment(
            teacher_id=teacher.id,
            school_class_id=portal["school_class"].id,
            grille_cours_ligne_id=portal["course"].id,
        )
    )
    db.session.commit()
    assert client.get(portal["url"] + "/grid").status_code == 200
    assert save(client, portal).status_code == 200
    assert client.get(portal["url"] + "/results").status_code == 404
    assert client.get("/portal/assignments").status_code == 404


def test_secretariat_reads_results_but_cannot_encode(client, portal, make_user):
    user, password = make_user(email="secretariat@example.com", role=RoleEnum.SECRETARIAT)
    client.get("/auth/logout")
    client.post("/auth/login", data={"email": user.email, "password": password})
    assert client.get(portal["url"] + "/results").status_code == 200
    assert client.get(portal["url"] + "/grid").status_code == 404
    assert save(client, portal).status_code == 404


def _login_assigned_teacher(client, db, portal, make_user, email="assigned@example.com"):
    teacher, password = make_user(email=email)
    db.session.add(
        TeacherAssignment(
            teacher_id=teacher.id,
            school_class_id=portal["school_class"].id,
            grille_cours_ligne_id=portal["course"].id,
        )
    )
    db.session.commit()
    client.get("/auth/logout")
    client.post("/auth/login", data={"email": teacher.email, "password": password})
    return teacher


@pytest.mark.parametrize(
    "suffix", ["/results", "/print/bulletins", "/print/palmares", "/print/bulletins?format=pdf"]
)
def test_role_never_admitted_gets_404_not_403(client, db, portal, make_user, suffix):
    # A teacher with a real link to the class (course assignment) still
    # gets 404 on results / print_report, whose role gate never admits
    # ENSEIGNANT: the response must not confirm that the resource exists.
    _login_assigned_teacher(client, db, portal, make_user)
    response = client.get(portal["url"] + suffix)
    assert response.status_code == 404
    assert "Accès refusé".encode() not in response.data


def test_own_scope_is_never_404(client, db, portal, make_user):
    # Regression guard for the 403 -> 404 conversion: every role still
    # reaches what is in its own perimeter.
    for path in ["/portal/", "/portal/assignments", portal["url"] + "/grid",
                 portal["url"] + "/results", portal["url"] + "/print/bulletins"]:
        assert client.get(path).status_code == 200, ("direction", path)

    secretariat, password = make_user(email="secr@example.com", role=RoleEnum.SECRETARIAT)
    client.get("/auth/logout")
    client.post("/auth/login", data={"email": secretariat.email, "password": password})
    for path in ["/portal/", portal["url"] + "/results", portal["url"] + "/print/bulletins"]:
        assert client.get(path).status_code == 200, ("secretariat", path)

    _login_assigned_teacher(client, db, portal, make_user)
    for path in ["/portal/", portal["url"] + "/grid"]:
        assert client.get(path).status_code == 200, ("enseignant", path)
    assert save(client, portal).status_code == 200


def test_inactive_account_still_gets_403(client, db, portal, make_user):
    # The one legitimate 403 (PERMISSIONS.md, « 403 légitimes »): the
    # account is the caller's own, only its use is refused — even on a
    # resource that is in its perimeter.
    teacher = _login_assigned_teacher(client, db, portal, make_user)
    assert client.get(portal["url"] + "/grid").status_code == 200
    teacher.is_active_account = False
    db.session.commit()
    assert client.get(portal["url"] + "/grid").status_code == 403
    assert client.get("/portal/").status_code == 403
    # A POST keeps its 401 so the grid keeps its drafts.
    assert save(client, portal).status_code == 401


def test_session_expiry_preserves_server_data(client, portal):
    client.get("/auth/logout")
    assert save(client, portal).status_code == 401
    assert Grade.query.count() == 0


def test_csrf_is_enforced(app, client, portal):
    app.config["WTF_CSRF_ENABLED"] = True
    assert save(client, portal).status_code == 400
    assert Grade.query.count() == 0


def test_archived_year_is_inaccessible(client, db, portal):
    portal["school_class"].academic_year.archived_at = utcnow()
    db.session.commit()
    assert client.get(portal["url"] + "/grid").status_code == 404
    assert save(client, portal).status_code == 404


def test_assignment_is_idempotent(client, db, portal, make_user):
    teacher, _ = make_user(email="teacher@example.com")
    data = {
        "teacher_id": teacher.id,
        "class_id": portal["school_class"].id,
        "grille_cours_ligne_id": portal["course"].id,
    }
    assert client.post("/portal/assignments", data=data).status_code == 302
    assert client.post("/portal/assignments", data=data).status_code == 302
    assert TeacherAssignment.query.count() == 1


def test_missing_scores_are_not_zero(client, portal):
    response = client.get(portal["url"] + "/results")
    assert b"Non " in response.data
    assert b"0.00 %" not in response.data
    save(client, portal)
    assert b"60 %" in client.get(portal["url"] + "/results").data


@pytest.mark.parametrize("target", ["https://example.com", "//example.com", "/\\example.com"])
def test_login_rejects_external_redirect(client, make_user, target):
    user, password = make_user()
    response = client.post(
        "/auth/login",
        query_string={"next": target},
        data={"email": user.email, "password": password},
    )
    assert response.location == "/portal/"
