"""Two Backend rules of the published bulletin.

1. The frozen content rounds `pourcentage_affiche` to the tenant's
   configured `percentage_decimal_places` (invariant 2, #69): never the
   platform default, and an incomplete configuration refuses to publish.
2. `peut_lire_motif_correction`: who may read the motif of a correction
   (owner decision, PERMISSIONS.md)."""

import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models.course import Course
from app.models.deliberation_workflow import BulletinVersion
from app.models.grille import GrilleCoursLigne, GrilleCoursLigneMaximum
from app.models.institution import Institution
from app.models.teaching import TeacherAssignment
from app.models.tenant_config import TenantConfig
from app.models.user import RoleEnum
from app.security.tenant import resolve_tenant
from app.services.authorization_service import peut_lire_motif_correction
from app.services.contenu_bulletin import ContenuBulletinError, calculer_contenu
from tests.integration.test_contenu_bulletin import _grade
from tests.integration.test_contenu_bulletin import classe as classe_fixture
from tests.integration.test_contenu_bulletin import published as published_fixture

classe = classe_fixture
published = published_fixture

MOTIF = "Cote de mathématiques mal reportée, copie relue en conseil."


@pytest.fixture(autouse=True)
def _tenant_request_context(app, tenant_a):
    """Service calls below run outside any HTTP request: push a resolved
    request context so tenant-scoped queries see tenant_a's data."""
    with app.test_request_context("/", base_url=f"http://{tenant_a.domain}"):
        resolve_tenant()
        yield


def _versions():
    return (
        BulletinVersion.query.execution_options(skip_tenant_filter=True)
        .order_by(BulletinVersion.numero)
        .all()
    )


def _config(tenant):
    return TenantConfig.query.execution_options(skip_tenant_filter=True).filter_by(
        ecole_id=tenant.id
    ).one()


def _publish(client, base):
    for action in ("submit", "consolidate", "validate", "publish"):
        client.post(f"{base}/consolidation/{action}")


# --- 1. Configured precision in the frozen content ------------------------


def test_frozen_percentage_uses_the_configured_decimal_places(classe, client, db, tenant_a):
    # Refutation: on main the frozen value is "75.00" whatever the tenant says.
    _config(tenant_a).percentage_decimal_places = 3
    db.session.commit()
    _publish(client, classe["base"])
    (v1,) = _versions()
    (eleve,) = json.loads(v1.contenu)["eleves"]
    assert eleve["total"]["pourcentage_affiche"] == "75.000"


def test_precision_is_frozen_at_publication(published, client, db, tenant_a):
    (v1,) = _versions()
    _config(tenant_a).percentage_decimal_places = 1
    db.session.commit()
    (eleve,) = json.loads(v1.contenu)["eleves"]
    assert eleve["total"]["pourcentage_affiche"] == "75.00"


def test_incomplete_calculation_config_refuses_to_publish(classe, client, school_class,
                                                         evaluation_period, monkeypatch):
    # calculation_strategy_key is a foreign key and percentage_decimal_places
    # is NOT NULL: an incomplete row cannot be stored, so the resolver's
    # explicit error is simulated.
    from app.services import contenu_bulletin
    from app.services.tenant_calculation import IncompleteTenantConfigError

    def incomplete(ecole_id):
        raise IncompleteTenantConfigError(f"ecole_id={ecole_id}: percentage_decimal_places is not set.")

    monkeypatch.setattr(contenu_bulletin, "resolve_tenant_calculation", incomplete)
    with pytest.raises(ContenuBulletinError, match="Configuration de calcul incomplète"):
        calculer_contenu(school_class, evaluation_period, {})
    _publish(client, classe["base"])
    assert _versions() == []


# --- 2. peut_lire_motif_correction -----------------------------------------


@pytest.fixture()
def corrections(published, client, db, make_user, school_class, grille_ligne,
                evaluation_period, tenant_a):
    """v1 published; v2 changes only the first line's grade; v3 adds a
    second line and renames the school (no single line); v4 changes the
    grades of both lines."""
    base = published["base"] + "/consolidation"
    enrollment, period = published["enrollment"], published["period"]

    _grade(enrollment, grille_ligne, period).score = Decimal("16")
    db.session.commit()
    assert client.post(base + "/correction", data={"motif": MOTIF}).status_code == 302

    other_course = Course(ecole_id=tenant_a.id, name="Histoire", code="HIST")
    db.session.add(other_course)
    db.session.flush()
    other_line = GrilleCoursLigne(
        ecole_id=tenant_a.id, cours_id=other_course.id,
        grille_cours_id=grille_ligne.grille_cours_id, groupe_cours_id=grille_ligne.groupe_cours_id,
        ordre_affichage=2, ponderation=Decimal("1"),
    )
    db.session.add(other_line)
    db.session.flush()
    db.session.add(GrilleCoursLigneMaximum(
        ecole_id=tenant_a.id, grille_cours_ligne_id=other_line.id,
        periode_id=evaluation_period.id, maximum=Decimal("20"),
    ))
    db.session.commit()

    db.session.get(Institution, tenant_a.id).name = "École fictive renommée"
    db.session.commit()
    assert client.post(base + "/correction", data={"motif": MOTIF}).status_code == 302

    from app.models.grading import Grade

    _grade(enrollment, grille_ligne, period).score = Decimal("17")
    db.session.add(Grade(
        ecole_id=tenant_a.id, enrollment_id=enrollment.id, grille_cours_ligne_id=other_line.id,
        period_id=period.id, score=Decimal("10"), entered_by_id=published["user"].id,
    ))
    db.session.commit()
    assert client.post(base + "/correction", data={"motif": MOTIF}).status_code == 302

    titulaire, _ = make_user(email="titulaire@example.com")
    affected, _ = make_user(email="affected@example.com")
    other, _ = make_user(email="other@example.com")
    unassigned, _ = make_user(email="unassigned@example.com")
    secretariat, _ = make_user(email="secretariat@example.com", role=RoleEnum.SECRETARIAT)
    school_class.titulaire_id = titulaire.id
    for teacher, line in ((affected, grille_ligne), (other, other_line)):
        db.session.add(TeacherAssignment(
            ecole_id=tenant_a.id, teacher_id=teacher.id,
            school_class_id=school_class.id, grille_cours_ligne_id=line.id,
        ))
    db.session.commit()
    v1, v2, v3, v4 = _versions()
    return SimpleNamespace(
        v1=v1, v2=v2, v3=v3, v4=v4, direction=published["user"], titulaire=titulaire,
        affected=affected, other=other, unassigned=unassigned, secretariat=secretariat,
    )


def test_direction_and_titulaire_read_every_motif(corrections, school_class):
    for user in (corrections.direction, corrections.titulaire):
        for version in (corrections.v2, corrections.v3, corrections.v4):
            assert peut_lire_motif_correction(user, school_class, version)


def test_attributaire_reads_only_the_correction_of_their_single_line(corrections, school_class):
    c = corrections
    assert peut_lire_motif_correction(c.affected, school_class, c.v2)
    # No single line: the school's name (v3), two lines at once (v4).
    assert not peut_lire_motif_correction(c.affected, school_class, c.v3)
    assert not peut_lire_motif_correction(c.affected, school_class, c.v4)
    # A first publication has no motif.
    assert not peut_lire_motif_correction(c.affected, school_class, c.v1)


def test_others_never_read_a_motif(corrections, school_class):
    c = corrections
    for user in (c.other, c.unassigned, c.secretariat, None):
        for version in (c.v1, c.v2, c.v3, c.v4):
            assert not peut_lire_motif_correction(user, school_class, version)


def test_version_of_another_class_is_refused(corrections, school_class):
    other_class = SimpleNamespace(id=school_class.id + 1000)
    assert not peut_lire_motif_correction(corrections.direction, other_class, corrections.v2)


def _record_errors(monkeypatch):
    """Capture the module logger's errors directly: the app's logging
    setup may stop propagation to the root logger, which caplog reads."""
    from app.services import authorization_service

    messages = []
    monkeypatch.setattr(
        authorization_service.logger, "error",
        lambda msg, *args: messages.append(msg % args),
    )
    return messages


def test_altered_frozen_content_fails_closed_and_is_logged(corrections, school_class,
                                                            monkeypatch):
    # Detached copy: the stored version itself is immutable.
    v2 = corrections.v2
    altered = SimpleNamespace(
        publication=v2.publication,
        corrige_version=v2.corrige_version,
        contenu=v2.contenu + " ",
        empreinte=v2.empreinte,
        numero=v2.numero,
    )
    errors = _record_errors(monkeypatch)
    assert not peut_lire_motif_correction(corrections.affected, school_class, altered)
    assert any("empreinte" in message for message in errors)


def test_content_frozen_before_migration_is_refused_without_noise(
    corrections, school_class, monkeypatch
):
    v2 = corrections.v2
    legacy = SimpleNamespace(
        publication=v2.publication, corrige_version=v2.corrige_version,
        contenu=None, empreinte=None, numero=v2.numero,
    )
    errors = _record_errors(monkeypatch)
    assert not peut_lire_motif_correction(corrections.affected, school_class, legacy)
    assert errors == []
