"""Tests bloquants — injection d'identifiants inter-tenants (invariants 4 et 6).

Un utilisateur authentifié du tenant A injecte un identifiant appartenant au
tenant B par chacun des vecteurs possibles : paramètre de chemin, paramètre
de requête, champ caché de formulaire, payload d'API, identifiants en masse
dans un lot de cotes, en-tête et cookie. Il doit recevoir une ressource
introuvable (404), jamais un refus explicite (403), jamais une donnée de B,
et aucune écriture ne doit atteindre B.

Entités couvertes : classe, cours (ligne de grille), élève, inscription,
cote, bulletin, période, journal d'audit.
"""

import json

import pytest

from app.models.academic import SchoolClass
from app.models.deliberation_workflow import (
    DeliberationAuditLog,
    DeliberationOverride,
    PeriodPublication,
    PublicationStatus,
)
from app.models.grading import Grade, GradeAuditLog
from app.models.teaching import TeacherAssignment
from app.models.user import RoleEnum
from app.security.tenant import resolve_tenant

# Valeurs propres au tenant B (voir tenant_b_world dans tests/conftest.py) :
# aucune ne doit jamais apparaître dans une réponse servie au tenant A.
B_MARKERS = ("Secretbeta", "Bintou", "EFB-0001", "Physique", "Seconde 1", "Fictive Beta",
             "Semestre 1", "beta.example")


@pytest.fixture(autouse=True)
def _tenant_request_context(app, tenant_a):
    with app.test_request_context("/", base_url=f"http://{tenant_a.domain}"):
        resolve_tenant()
        yield


@pytest.fixture()
def attack(client, make_user, school_class, grille_ligne, enrollment, evaluation_period,
           tenant_b_world):
    """Tenant A's DIRECTION, logged in, with a fully working class/period of
    its own — so every 404 below is caused by the injected B identifier,
    not by A's context being incomplete."""
    user, password = make_user(email="direction@alpha.example", role=RoleEnum.DIRECTION)
    response = client.post("/auth/login", data={"email": user.email, "password": password})
    assert response.status_code == 302
    return {
        "a_class": school_class,
        "a_period": evaluation_period,
        "a_ligne": grille_ligne,
        "a_enrollment": enrollment,
        "a_url": f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}",
        "a_domain": school_class.ecole_id and client.application.config["SERVER_NAME"],
        "b": tenant_b_world,
    }


def _unscoped(model):
    return model.query.execution_options(skip_tenant_filter=True)


def _assert_not_found(response, label):
    assert response.status_code == 404, f"{label} : {response.status_code} au lieu de 404"
    _assert_no_b_data(response, label)


def _assert_no_b_data(response, label):
    body = response.get_data(as_text=True)
    leaked = [marker for marker in B_MARKERS if marker in body]
    assert not leaked, f"{label} : données du tenant B divulguées {leaked}"


def _b_state(b):
    """Snapshot of everything an injected write could have altered in B."""
    grade = _unscoped(Grade).filter_by(id=b.grade.id).one()
    return {
        "grade": (grade.score, grade.is_validated, grade.archived_at),
        "grades": _unscoped(Grade).filter_by(ecole_id=b.institution.id).count(),
        "grade_audit": _unscoped(GradeAuditLog).filter_by(ecole_id=b.institution.id).count(),
        "delib_audit": _unscoped(DeliberationAuditLog)
        .filter_by(ecole_id=b.institution.id)
        .count(),
        "overrides": _unscoped(DeliberationOverride).filter_by(ecole_id=b.institution.id).count(),
        "assignments": _unscoped(TeacherAssignment).filter_by(ecole_id=b.institution.id).count(),
        "publication": _unscoped(PeriodPublication).filter_by(id=b.publication.id).one().status,
        "titulaire": _unscoped(SchoolClass).filter_by(id=b.school_class.id).one().titulaire_id,
    }


# --- Vecteur 1 : paramètres de chemin --------------------------------------

READ_SUFFIXES = (
    "/grid",
    "/results",
    "/consolidation",
    "/deliberation",
    "/print/bulletins",
    "/print/palmares",
    "/print/bulletins?format=pdf",
    "/report-template",
    "/report-preview",
)


@pytest.mark.parametrize("suffix", READ_SUFFIXES)
def test_path_param_b_class_is_not_found(client, attack, suffix):
    b = attack["b"]
    url = f"/portal/classes/{b.school_class.id}/periods/{attack['a_period'].id}{suffix}"
    _assert_not_found(client.get(url), f"classe B {suffix}")


@pytest.mark.parametrize("suffix", READ_SUFFIXES)
def test_path_param_b_period_is_not_found(client, attack, suffix):
    b = attack["b"]
    url = f"/portal/classes/{attack['a_class'].id}/periods/{b.periods[0].id}{suffix}"
    _assert_not_found(client.get(url), f"période B {suffix}")


@pytest.mark.parametrize("suffix", READ_SUFFIXES)
def test_path_param_b_class_and_period_together_are_not_found(client, attack, suffix):
    b = attack["b"]
    url = f"/portal/classes/{b.school_class.id}/periods/{b.periods[0].id}{suffix}"
    _assert_not_found(client.get(url), f"classe+période B {suffix}")


@pytest.mark.parametrize("action", ["submit", "consolidate", "validate", "publish"])
def test_path_param_b_bulletin_transition_is_not_found(client, attack, action):
    b = attack["b"]
    before = _b_state(b)
    url = f"/portal/classes/{b.school_class.id}/periods/{b.periods[0].id}/consolidation/{action}"
    _assert_not_found(client.post(url), f"transition {action} sur bulletin B")
    assert _b_state(b) == before


@pytest.mark.parametrize("method", ["get", "post"])
def test_path_param_b_enrollment_override_is_not_found(client, attack, method):
    b = attack["b"]
    before = _b_state(b)
    url = f"{attack['a_url']}/deliberation/{b.enrollment.id}/override"
    data = {"manual_decision": "ADMITTED", "manual_reason": "Injection inter-tenant tentée"}
    response = getattr(client, method)(url, data=data) if method == "post" else client.get(url)
    _assert_not_found(response, f"override inscription B ({method})")
    assert _b_state(b) == before


def test_path_param_b_everything_override_is_not_found(client, attack):
    b = attack["b"]
    before = _b_state(b)
    url = (
        f"/portal/classes/{b.school_class.id}/periods/{b.periods[0].id}"
        f"/deliberation/{b.enrollment.id}/override"
    )
    data = {"manual_decision": "DEFERRED", "manual_reason": "Injection inter-tenant tentée"}
    _assert_not_found(client.post(url, data=data), "override entièrement B")
    assert _b_state(b) == before


# --- Vecteur 2 : payload d'API et lot de cotes -----------------------------


def _sync(client, url, changes):
    return client.post(url + "/sync", data={"changes": json.dumps(changes)})


@pytest.mark.parametrize(
    "field,b_attr",
    [("enrollment", "enrollment"), ("course", "ligne")],
)
def test_sync_payload_with_b_identifier_is_not_found(client, attack, field, b_attr):
    b = attack["b"]
    before = _b_state(b)
    change = {
        "enrollment": attack["a_enrollment"].id,
        "course": attack["a_ligne"].id,
        "value": "9",
        "base": "",
    }
    change[field] = getattr(b, b_attr).id
    _assert_not_found(_sync(client, attack["a_url"], [change]), f"sync {field} B")
    assert _b_state(b) == before


def test_sync_payload_entirely_b_on_b_url_is_not_found(client, attack):
    b = attack["b"]
    before = _b_state(b)
    url = f"/portal/classes/{b.school_class.id}/periods/{b.periods[0].id}"
    change = {"enrollment": b.enrollment.id, "course": b.ligne.id, "value": "1", "base": "7.50"}
    _assert_not_found(_sync(client, url, [change]), "sync entièrement B")
    assert _b_state(b) == before


def test_bulk_batch_with_one_b_identifier_writes_nothing_at_all(client, attack):
    """Identifiants en masse : un lot mêlant des cellules valides de A et
    une seule cellule de B est rejeté en bloc — ni la cellule de B ni les
    cellules légitimes de A ne sont écrites."""
    b = attack["b"]
    before = _b_state(b)
    a_grades_before = Grade.query.count()
    changes = [
        {"enrollment": attack["a_enrollment"].id, "course": attack["a_ligne"].id,
         "value": "11", "base": ""},
        {"enrollment": b.enrollment.id, "course": b.ligne.id, "value": "1", "base": "7.50"},
    ]
    _assert_not_found(_sync(client, attack["a_url"], changes), "lot mixte A+B")
    assert _b_state(b) == before
    assert Grade.query.count() == a_grades_before


def test_bulk_batch_of_many_b_identifiers_is_not_found(client, attack):
    b = attack["b"]
    before = _b_state(b)
    changes = [
        {"enrollment": b.enrollment.id + offset, "course": b.ligne.id, "value": "1", "base": ""}
        for offset in range(0, 30)
    ]
    _assert_not_found(_sync(client, attack["a_url"], changes), "lot de 30 identifiants B")
    assert _b_state(b) == before


# --- Vecteur 3 : champs cachés de formulaire --------------------------------


@pytest.mark.parametrize(
    "form",
    [
        {"class_id": "b_class", "teacher_id": "a_teacher", "grille_cours_ligne_id": "a_ligne"},
        {"class_id": "a_class", "teacher_id": "b_teacher", "grille_cours_ligne_id": "a_ligne"},
        {"class_id": "a_class", "teacher_id": "a_teacher", "grille_cours_ligne_id": "b_ligne"},
        {"class_id": "b_class", "teacher_id": "b_teacher", "grille_cours_ligne_id": "b_ligne"},
    ],
    ids=["classe-B", "enseignant-B", "cours-B", "tout-B"],
)
def test_assignment_hidden_fields_with_b_identifiers_are_not_found(
    client, attack, make_user, form
):
    b = attack["b"]
    a_teacher, _ = make_user(email="prof@alpha.example", role=RoleEnum.ENSEIGNANT)
    ids = {
        "a_class": attack["a_class"].id, "b_class": b.school_class.id,
        "a_teacher": a_teacher.id, "b_teacher": b.teacher.id,
        "a_ligne": attack["a_ligne"].id, "b_ligne": b.ligne.id,
    }
    before = _b_state(b)
    a_assignments_before = TeacherAssignment.query.count()
    response = client.post("/portal/assignments", data={k: ids[v] for k, v in form.items()})
    _assert_not_found(response, f"attribution {form}")
    assert _b_state(b) == before
    assert TeacherAssignment.query.count() == a_assignments_before


@pytest.mark.parametrize("target", ["b_class", "b_teacher"])
def test_titulaire_hidden_fields_with_b_identifiers_are_not_found(
    client, attack, make_user, target
):
    b = attack["b"]
    a_teacher, _ = make_user(email="prof@alpha.example", role=RoleEnum.ENSEIGNANT)
    data = {
        "kind": "titulaire",
        "class_id": b.school_class.id if target == "b_class" else attack["a_class"].id,
        "titulaire_teacher_id": b.teacher.id if target == "b_teacher" else a_teacher.id,
        "motif": "Injection inter-tenant tentée",
    }
    before = _b_state(b)
    _assert_not_found(client.post("/portal/assignments", data=data), f"titulaire {target}")
    assert _b_state(b) == before


# --- Vecteur 4 : paramètres de requête, en-têtes, cookies -------------------


@pytest.mark.parametrize(
    "path",
    ["/portal/", "/portal/assignments", "/portal/audit", "/admin/users", "/admin/academic-years"],
)
def test_query_params_header_and_cookie_cannot_select_tenant_b(client, attack, path):
    """ecole_id n'est jamais accepté depuis la requête : un paramètre, un
    en-tête ou un cookie désignant B ne change rien — A voit ses propres
    données, et rien de B."""
    b = attack["b"]
    bid = b.institution.id
    client.set_cookie("ecole_id", str(bid), domain=attack["a_domain"])
    response = client.get(
        f"{path}?ecole_id={bid}&tenant={bid}&class_id={b.school_class.id}"
        # Name fragments, not full names: filter forms echo the query back,
        # and the attacker's own input is not a leak.
        "&student=Secret&user=Enseign",
        headers={"X-Ecole-Id": str(bid), "X-Tenant-Id": str(bid), "X-Forwarded-Host": "beta.testserver"},
    )
    assert response.status_code == 200, path
    _assert_no_b_data(response, f"{path} avec ecole_id=B en paramètre/en-tête/cookie")


# --- Entités : journal d'audit, cote, bulletin ------------------------------


def test_audit_log_never_lists_b_entries(client, attack):
    """Journal d'audit : les entrées de B (création de cote, transitions)
    n'apparaissent dans aucun filtre de la vue d'audit de A. Les filtres
    portent sur des fragments de noms de B (le formulaire ré-affiche la
    saisie de l'attaquant, qui n'est pas une fuite)."""
    for query in ("", "?action=CREATE", "?student=Secret", "?user=Enseign", "?action=PUBLISH"):
        _assert_no_b_data(client.get("/portal/audit" + query), f"audit {query}")


def test_a_bulletin_of_a_never_contains_b_grades_or_students(client, attack):
    """Bulletin et palmarès de A : rendus normalement, sans aucune donnée de
    B — même quand B a une cote et un bulletin publié sur des identifiants
    voisins."""
    for suffix in ("/print/bulletins", "/print/palmares", "/results", "/grid"):
        response = client.get(attack["a_url"] + suffix)
        assert response.status_code == 200, suffix
        _assert_no_b_data(response, f"bulletin A {suffix}")


def test_b_published_bulletin_stays_published_and_unchanged(client, attack):
    b = attack["b"]
    for action in ("submit", "consolidate", "validate", "publish"):
        client.post(f"{attack['a_url']}/consolidation/{action}")
    publication = _unscoped(PeriodPublication).filter_by(id=b.publication.id).one()
    assert publication.status == PublicationStatus.PUBLISHED
    assert publication.version == 1


# --- Rôle ENSEIGNANT : même garantie --------------------------------------


def test_teacher_of_a_injecting_b_identifiers_gets_not_found(
    client, app, make_user, school_class, grille_ligne, enrollment, evaluation_period,
    tenant_b_world,
):
    b = tenant_b_world
    teacher, password = make_user(email="prof@alpha.example", role=RoleEnum.ENSEIGNANT)
    from app.extensions import db

    db.session.add(TeacherAssignment(
        teacher_id=teacher.id, school_class_id=school_class.id,
        grille_cours_ligne_id=grille_ligne.id,
    ))
    db.session.commit()
    client.post("/auth/login", data={"email": teacher.email, "password": password})
    a_url = f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}"
    assert client.get(a_url + "/grid").status_code == 200

    before = _b_state(b)
    _assert_not_found(
        client.get(f"/portal/classes/{b.school_class.id}/periods/{b.periods[0].id}/grid"),
        "grille B (enseignant)",
    )
    _assert_not_found(
        _sync(client, a_url, [{"enrollment": b.enrollment.id, "course": grille_ligne.id,
                               "value": "5", "base": ""}]),
        "sync inscription B (enseignant)",
    )
    _assert_not_found(
        client.post(f"/portal/classes/{b.school_class.id}/periods/{b.periods[0].id}"
                    "/consolidation/submit"),
        "soumission bulletin B (enseignant)",
    )
    assert _b_state(b) == before
