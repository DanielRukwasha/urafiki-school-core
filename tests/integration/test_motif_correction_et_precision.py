"""Two Backend rules of the published bulletin.

1. The frozen content rounds `pourcentage_affiche` to the tenant's
   configured `percentage_decimal_places` (invariant 2, #69): never the
   platform default, and an incomplete configuration refuses to publish.
   The precision is bounded (0–6): a value outside refuses to publish
   with an explicit error, never an unhandled exception.
2. `peut_lire_motif_correction`: who may read the motif of a correction
   (owner decision, PERMISSIONS.md), with the same integrity contract
   for every profile."""

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
from app.services.contenu_bulletin import ContenuBulletinError, calculer_contenu, ligne_corrigee
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
    """Run the workflow up to publication, checking every step: the
    preparatory transitions must succeed, so a refused publication can
    only come from the publication itself. Returns its response."""
    for action in ("submit", "consolidate", "validate"):
        assert client.post(f"{base}/consolidation/{action}").status_code == 302, action
    return client.post(f"{base}/consolidation/publish")


# --- 1. Configured precision in the frozen content ------------------------


def test_frozen_percentage_uses_the_configured_decimal_places(classe, client, db, tenant_a):
    # Refutation: on main the frozen value is "75.00" whatever the tenant says.
    _config(tenant_a).percentage_decimal_places = 3
    db.session.commit()
    assert _publish(client, classe["base"]).status_code == 302
    (v1,) = _versions()
    contenu = json.loads(v1.contenu)
    (eleve,) = contenu["eleves"]
    assert eleve["total"]["pourcentage_affiche"] == "75.000"
    assert contenu["precision_pourcentage"] == 3


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
    response = _publish(client, classe["base"])
    assert response.status_code == 409
    assert "Configuration de calcul incomplète" in response.get_data(as_text=True)
    assert _versions() == []


@pytest.mark.parametrize("decimales", [30, 7, -1])
def test_out_of_range_precision_refuses_to_publish_explicitly(classe, client, db, tenant_a,
                                                             decimales):
    # Refutation of the Frontend review blocker on #129: 30 decimals made
    # quantize raise decimal.InvalidOperation, an unhandled 500.
    _config(tenant_a).percentage_decimal_places = decimales
    db.session.commit()
    response = _publish(client, classe["base"])
    assert response.status_code == 409
    body = response.get_data(as_text=True)
    assert "Configuration de calcul incomplète" in body
    assert "outside the supported range 0–6" in body
    assert _versions() == []


@pytest.mark.parametrize("decimales", [0, 6])
def test_precision_bounds_are_supported(classe, client, db, tenant_a, decimales):
    _config(tenant_a).percentage_decimal_places = decimales
    db.session.commit()
    assert _publish(client, classe["base"]).status_code == 302
    (v1,) = _versions()
    (eleve,) = json.loads(v1.contenu)["eleves"]
    assert eleve["total"]["pourcentage_affiche"] == ("75" if decimales == 0 else "75.000000")


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


def test_correction_changing_a_grade_and_the_precision_is_class_scope(
    published, client, db, make_user, school_class, grille_ligne, tenant_a
):
    # Refutation of the Frontend review blocker on #129: 75.00 -> 80.000
    # with one grade changed was pinned to that grade's line.
    affected, _ = make_user(email="affected@example.com")
    db.session.add(TeacherAssignment(
        ecole_id=tenant_a.id, teacher_id=affected.id,
        school_class_id=school_class.id, grille_cours_ligne_id=grille_ligne.id,
    ))
    _grade(published["enrollment"], grille_ligne, published["period"]).score = Decimal("16")
    _config(tenant_a).percentage_decimal_places = 3
    db.session.commit()
    response = client.post(published["base"] + "/consolidation/correction", data={"motif": MOTIF})
    assert response.status_code == 302
    v1, v2 = _versions()
    (avant,), (apres,) = json.loads(v1.contenu)["eleves"], json.loads(v2.contenu)["eleves"]
    assert (avant["total"]["pourcentage_affiche"], apres["total"]["pourcentage_affiche"]) == (
        "75.00", "80.000"
    )
    assert not peut_lire_motif_correction(affected, school_class, v2)
    assert peut_lire_motif_correction(published["user"], school_class, v2)


_SANS_CLE = object()


def _contenu(cote, affiche, precision=_SANS_CLE):
    """A minimal frozen content: one student, one line (7). `cote` None
    means no grade yet, hence no percentage. Without `precision`, the
    content has the format frozen before `precision_pourcentage` existed."""
    contenu = {
        "schema": 1, "classe": {}, "periode": {}, "colonnes": [], "presentation": {},
        "eleves": [{
            "inscription_id": 1, "nom_complet": "A", "matricule": "M",
            "cotes": {} if cote is None else {"7": {"cote": cote, "appreciation": None}},
            "total": {"pourcentage_affiche": affiche},
        }],
    }
    if precision is not _SANS_CLE:
        contenu["precision_pourcentage"] = precision
    return contenu


def test_precision_change_is_detected_without_the_frozen_key():
    # Two contents frozen before the key: the displayed decimals decide.
    assert ligne_corrigee(_contenu("15", "75.00"), _contenu("16", "80.00")) == 7
    assert ligne_corrigee(_contenu("15", "75.00"), _contenu("16", "80.000")) is None


@pytest.mark.parametrize("avant, apres", [
    # First grade entered: no percentage before, same configured precision.
    (_contenu(None, None, 2), _contenu("15", "75.00", 2)),
    # Last grade removed: the reverse.
    (_contenu("15", "75.00", 2), _contenu(None, None, 2)),
    # Version frozen before the key, displaying two decimals, corrected
    # by a new one at two decimals.
    (_contenu("15", "75.00"), _contenu("16", "80.00", 2)),
], ids=["premiere-cote", "derniere-cote-retiree", "ancien-format"])
def test_single_line_correction_at_constant_precision_stays_pinned(avant, apres):
    # Refutation of the Frontend review blocker 1 on 3fb011c.
    assert ligne_corrigee(avant, apres) == 7


@pytest.mark.parametrize("avant, apres", [
    # Old format with no percentage: its precision cannot be established.
    (_contenu(None, None), _contenu("15", "75.00", 2)),
    # A content contradicting its own key.
    (_contenu("15", "75.000", 2), _contenu("16", "80.00", 2)),
    # Same key on both sides, but configured precision changed.
    (_contenu("15", "75.00", 2), _contenu("16", "80.000", 3)),
], ids=["ancien-format-sans-pourcentage", "cle-contredite", "precision-changee"])
def test_unestablished_or_changed_precision_is_class_scope(avant, apres):
    assert ligne_corrigee(avant, apres) is None


def test_unchanged_bulletin_in_the_old_format_cannot_be_republished(
    classe, client, db, monkeypatch
):
    # Refutation of the Frontend review blocker 2 on 3fb011c: v1 frozen in
    # the format without `precision_pourcentage`, nothing changed, then a
    # correction — its fingerprint differs only because of the new key.
    from app.services import deliberation_service

    calculer = deliberation_service.calculer_contenu

    def ancien_format(*args):
        contenu = calculer(*args)
        del contenu["precision_pourcentage"]
        return contenu

    monkeypatch.setattr(deliberation_service, "calculer_contenu", ancien_format)
    assert _publish(client, classe["base"]).status_code == 302
    monkeypatch.undo()
    (v1,) = _versions()
    assert "precision_pourcentage" not in json.loads(v1.contenu)

    response = client.post(classe["base"] + "/consolidation/correction", data={"motif": MOTIF})
    assert response.status_code == 422
    assert "identique à la version 1" in response.get_data(as_text=True)
    assert _versions() == [v1]


def test_real_correction_of_a_bulletin_in_the_old_format_is_published(
    classe, client, db, monkeypatch
):
    # Guard: the equivalence never swallows a real change.
    from app.services import deliberation_service

    calculer = deliberation_service.calculer_contenu

    def ancien_format(*args):
        contenu = calculer(*args)
        del contenu["precision_pourcentage"]
        return contenu

    monkeypatch.setattr(deliberation_service, "calculer_contenu", ancien_format)
    assert _publish(client, classe["base"]).status_code == 302
    monkeypatch.undo()
    _grade(classe["enrollment"], classe["ligne"], classe["period"]).score = Decimal("16")
    db.session.commit()
    response = client.post(classe["base"] + "/consolidation/correction", data={"motif": MOTIF})
    assert response.status_code == 302
    assert len(_versions()) == 2


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


def _copie(version, **champs):
    """Detached copy of a version: the stored version itself is immutable."""
    attributs = dict(
        publication=version.publication, corrige_version=version.corrige_version,
        contenu=version.contenu, empreinte=version.empreinte, numero=version.numero,
    )
    attributs.update(champs)
    return SimpleNamespace(**attributs)


def test_altered_frozen_content_is_read_by_nobody_and_logged(corrections, school_class,
                                                              monkeypatch):
    # Integrity conditions the motif for every profile, class scope included.
    c = corrections
    altered = _copie(c.v2, contenu=c.v2.contenu + " ")
    for user in (c.direction, c.titulaire, c.affected):
        errors = _record_errors(monkeypatch)
        assert not peut_lire_motif_correction(user, school_class, altered), user.email
        assert any("empreinte" in message for message in errors), user.email


def test_content_without_its_fingerprint_counts_as_altered(corrections, school_class,
                                                           monkeypatch):
    c = corrections
    errors = _record_errors(monkeypatch)
    assert not peut_lire_motif_correction(c.direction, school_class,
                                          _copie(c.v2, empreinte=None))
    assert errors


def test_altered_corrected_version_refuses_the_attributaire_only(corrections, school_class,
                                                                 monkeypatch):
    # v2's own content is intact: the class scope reads its motif. The
    # attributaire's reading depends on comparing with v1, which is broken.
    c = corrections
    version = _copie(c.v2, corrige_version=_copie(c.v1, contenu=c.v1.contenu + " "))
    errors = _record_errors(monkeypatch)
    assert peut_lire_motif_correction(c.direction, school_class, version)
    assert peut_lire_motif_correction(c.titulaire, school_class, version)
    assert errors == []
    assert not peut_lire_motif_correction(c.affected, school_class, version)
    assert any("empreinte" in message for message in errors)


def test_content_frozen_before_migration_is_class_scope_without_noise(
    corrections, school_class, monkeypatch
):
    # Nothing to verify and nothing broken: the motif (a column of the
    # version) stays readable by the class scope, never by an attributaire.
    c = corrections
    legacy = _copie(c.v2, contenu=None, empreinte=None)
    legacy_parent = _copie(c.v2, corrige_version=_copie(c.v1, contenu=None, empreinte=None))
    errors = _record_errors(monkeypatch)
    assert peut_lire_motif_correction(c.direction, school_class, legacy)
    assert peut_lire_motif_correction(c.titulaire, school_class, legacy)
    assert not peut_lire_motif_correction(c.affected, school_class, legacy)
    assert not peut_lire_motif_correction(c.affected, school_class, legacy_parent)
    assert not peut_lire_motif_correction(c.secretariat, school_class, legacy)
    assert errors == []
