"""Invariant 10 : les lectures sensibles sont journalisées — consultation
d'un bulletin, export de données, accès d'un super-administrateur."""

import pytest

from app.models.journal import ImmutableLogError, SensitiveReadKind, SensitiveReadLog
from app.models.platform import SuperAdmin, TenantAccessAuditLog, TenantAccessEventType
from app.models.user import RoleEnum
from app.services.journal_lectures import JournalisationError, journaliser_acces_super_admin
from app.services.tenant_provisioning import export_tenant


def _logs():
    return SensitiveReadLog.query.execution_options(skip_tenant_filter=True).all()


@pytest.fixture()
def direction(client, make_user, school_class, grille_ligne, enrollment, evaluation_period):
    user, password = make_user(email="direction@alpha.example", role=RoleEnum.DIRECTION)
    client.post("/auth/login", data={"email": user.email, "password": password})
    return {
        "user": user,
        "url": f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}",
    }


@pytest.mark.parametrize("suffix", ["/print/bulletins", "/print/palmares", "/results"])
def test_bulletin_consultation_is_journaled(client, direction, tenant_a, suffix):
    assert client.get(direction["url"] + suffix).status_code == 200
    (log,) = _logs()
    assert log.kind == SensitiveReadKind.BULLETIN_CONSULTATION.value
    assert log.user_id == direction["user"].id
    assert log.ecole_id == tenant_a.id
    assert log.resource.startswith(direction["url"] + suffix)


def test_pdf_download_is_journaled_as_an_export(client, direction):
    client.get(direction["url"] + "/print/bulletins?format=pdf")
    (log,) = _logs()
    assert log.kind == SensitiveReadKind.EXPORT_DONNEES.value
    assert "format=pdf" in log.resource


def test_refused_access_reads_nothing_and_logs_nothing(client, direction, tenant_b_world):
    b = tenant_b_world
    url = f"/portal/classes/{b.school_class.id}/periods/{b.periods[0].id}/print/bulletins"
    assert client.get(url).status_code == 404
    assert _logs() == []


def test_tenant_export_is_journaled_with_its_operator(app, tenant_a, make_user):
    make_user(email="direction@alpha.example", role=RoleEnum.DIRECTION)
    export_tenant(domain=tenant_a.domain)
    (log,) = _logs()
    assert log.kind == SensitiveReadKind.EXPORT_DONNEES.value
    assert log.ecole_id == tenant_a.id
    assert log.user_id is None and log.actor_label.startswith("cli:")
    assert tenant_a.domain in log.resource


def test_read_journal_is_immutable(client, direction, db):
    client.get(direction["url"] + "/results")
    (log,) = _logs()
    log.resource = "effacé"
    with pytest.raises(ImmutableLogError):
        db.session.commit()
    db.session.rollback()


@journaliser_acces_super_admin
def _lire_tenant(*, super_admin, ecole_id, motif):
    return f"données de {ecole_id}"


@pytest.fixture()
def super_admin(db):
    admin = SuperAdmin(email="ops@urafiki.example", first_name="Ops", last_name="Urafiki")
    admin.set_password("Password123!")
    db.session.add(admin)
    db.session.commit()
    return admin


def test_super_admin_access_is_journaled_before_it_happens(super_admin, tenant_a):
    motif = "Ticket 42 : vérification d'un bulletin à la demande de l'école"
    assert _lire_tenant(super_admin=super_admin, ecole_id=tenant_a.id, motif=motif)
    (entry,) = TenantAccessAuditLog.query.execution_options(skip_tenant_filter=True).all()
    assert entry.event_type == TenantAccessEventType.SUPER_ADMIN_ACCESS
    assert entry.actor_super_admin_id == super_admin.id
    assert entry.ecole_id == tenant_a.id
    assert entry.reason == motif


@pytest.mark.parametrize("motif", ["", "court"])
def test_super_admin_access_without_motif_is_refused(super_admin, tenant_a, motif):
    with pytest.raises(JournalisationError):
        _lire_tenant(super_admin=super_admin, ecole_id=tenant_a.id, motif=motif)
    assert TenantAccessAuditLog.query.execution_options(skip_tenant_filter=True).count() == 0
