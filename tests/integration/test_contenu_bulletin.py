"""Invariant 9, réfutation (revue de #55, bloquant 1) : une version publiée
fige le bulletin lui-même, pas seulement ses métadonnées. Après
publication, changer un maximum, un libellé de cours, une cote ou l'en-tête
de l'établissement ne modifie pas la version 1 ; une correction crée une
version 2 distincte, motivée, et chaque version reste lisible
explicitement."""

import hashlib
import json
from decimal import Decimal

import pytest

from app.extensions import db as _db
from app.models.course import Course
from app.models.deliberation_workflow import BulletinVersion, PeriodPublication
from app.models.grading import Grade
from app.models.grille import GrilleCoursLigne, GrilleCoursLigneMaximum, GroupeCours
from app.models.institution import Institution
from app.models.user import RoleEnum
from app.services.contenu_bulletin import ContenuBulletinError, contenu_de_version, serialiser

MOTIF = "Cote de mathématiques mal reportée, copie relue en conseil."


def _versions():
    return (
        BulletinVersion.query.execution_options(skip_tenant_filter=True)
        .order_by(BulletinVersion.numero)
        .all()
    )


def _grade(enrollment, ligne, period):
    return (
        Grade.query.execution_options(skip_tenant_filter=True)
        .filter_by(enrollment_id=enrollment.id, grille_cours_ligne_id=ligne.id, period_id=period.id)
        .one()
    )


@pytest.fixture()
def classe(client, db, make_user, tenant_a_structure, school_class, evaluation_period,
           grille_ligne, enrollment):
    """Math 15/20, weight 4: 60 / 80 points, 75.00 %."""
    user, password = make_user(email="direction@alpha.example", role=RoleEnum.DIRECTION)
    db.session.add(Grade(
        ecole_id=enrollment.ecole_id, enrollment_id=enrollment.id,
        grille_cours_ligne_id=grille_ligne.id, period_id=evaluation_period.id,
        score=Decimal("15"), entered_by_id=user.id,
    ))
    db.session.commit()
    client.post("/auth/login", data={"email": user.email, "password": password})
    base = f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}"
    return {
        "user": user, "base": base, "period": evaluation_period,
        "ligne": grille_ligne, "enrollment": enrollment,
    }


@pytest.fixture()
def published(classe, client):
    for action in ("submit", "consolidate", "validate", "publish"):
        assert client.post(f"{classe['base']}/consolidation/{action}").status_code == 302, action
    return classe


def _bulletin(client, published, **query):
    response = client.get(f"{published['base']}/print/bulletins", query_string=query)
    return response.status_code, response.get_data(as_text=True)


def test_every_published_version_freezes_its_content_with_a_matching_fingerprint(published):
    (v1,) = _versions()
    assert v1.contenu and len(v1.empreinte) == 64
    assert hashlib.sha256(v1.contenu.encode("utf-8")).hexdigest() == v1.empreinte
    contenu = json.loads(v1.contenu)
    (eleve,) = contenu["eleves"]
    assert Decimal(eleve["cotes"][str(published["ligne"].id)]["cote"]) == Decimal("15")
    assert eleve["total"]["pourcentage_affiche"] == "75.00"
    assert Decimal(contenu["colonnes"][0]["maximum"]) == Decimal("20")


def test_version_1_is_unchanged_after_grid_label_grade_and_school_changes(published, client, db):
    (v1,) = _versions()
    contenu_v1, empreinte_v1 = v1.contenu, v1.empreinte
    _, html_avant = _bulletin(client, published)

    ligne = published["ligne"]
    maximum = GrilleCoursLigneMaximum.query.execution_options(skip_tenant_filter=True).filter_by(
        grille_cours_ligne_id=ligne.id, periode_id=published["period"].id
    ).one()
    maximum.maximum = Decimal("40")
    _db.session.get(Course, ligne.cours_id).name = "Algebre renommee"
    _grade(published["enrollment"], ligne, published["period"]).score = Decimal("3")
    institution = _db.session.get(Institution, v1.ecole_id)
    institution.name = "Ecole Fictive Alpha Renommee"
    db.session.commit()

    status, html_apres = _bulletin(client, published)
    assert status == 200
    assert "75.00" in html_apres
    assert "Mathematiques" in html_apres
    assert "Algebre renommee" not in html_apres
    assert "Renommee" not in html_apres
    assert html_apres == html_avant

    (v1,) = _versions()
    assert (v1.contenu, v1.empreinte) == (contenu_v1, empreinte_v1)


def test_correction_freezes_a_distinct_version_2_and_each_version_stays_readable(
    published, client, db
):
    _grade(published["enrollment"], published["ligne"], published["period"]).score = Decimal("18")
    db.session.commit()

    assert client.post(
        f"{published['base']}/consolidation/correction", data={"motif": MOTIF}
    ).status_code == 302

    v1, v2 = _versions()
    assert v2.numero == 2 and v2.motif == MOTIF and v2.corrige_version_id == v1.id
    assert v2.empreinte != v1.empreinte

    assert "90.00" in _bulletin(client, published)[1]
    assert "90.00" in _bulletin(client, published, version=2)[1]
    status, html_v1 = _bulletin(client, published, version=1)
    assert status == 200 and "75.00" in html_v1 and "90.00" not in html_v1


def test_correction_identical_to_the_published_version_is_refused(published, client):
    response = client.post(
        f"{published['base']}/consolidation/correction", data={"motif": MOTIF}
    )
    assert response.status_code == 422
    assert "identique à la version 1" in response.get_data(as_text=True)
    assert len(_versions()) == 1


@pytest.mark.parametrize("version", ["0", "2", "abc", "-1"])
def test_reading_a_version_that_does_not_exist_is_a_404(published, client, version):
    assert _bulletin(client, published, version=version)[0] == 404


def test_an_unpublished_period_has_no_version_to_read(classe, client):
    assert _bulletin(client, classe, version=1)[0] == 404
    status, html = _bulletin(client, classe)
    assert status == 200 and "75.00" in html


def test_concurrent_correction_is_a_controlled_409_not_a_500(published, client, db):
    (v1,) = _versions()
    _grade(published["enrollment"], published["ligne"], published["period"]).score = Decimal("18")
    texte, empreinte = serialiser({"autre": "publication concurrente"})
    # Another request committed version 2 between this request's read of
    # the counter and its own insert.
    db.session.add(BulletinVersion(
        ecole_id=v1.ecole_id, publication_id=v1.publication_id, numero=2,
        motif="Correction concurrente enregistrée.", auteur_id=v1.auteur_id,
        corrige_version_id=v1.id, contenu=texte, empreinte=empreinte,
    ))
    db.session.commit()

    response = client.post(
        f"{published['base']}/consolidation/correction", data={"motif": MOTIF}
    )
    assert response.status_code == 409
    assert len(_versions()) == 2
    publication = PeriodPublication.query.execution_options(skip_tenant_filter=True).one()
    assert publication.version == 1


def test_a_version_whose_content_no_longer_matches_its_fingerprint_is_refused(published):
    (v1,) = _versions()
    altered = BulletinVersion(numero=1, contenu=v1.contenu.replace('"75.00"', '"95.00"'),
                              empreinte=v1.empreinte)
    with pytest.raises(ContenuBulletinError, match="empreinte"):
        contenu_de_version(altered)


def test_a_version_published_before_content_freezing_is_never_recalculated():
    legacy = BulletinVersion(numero=1, contenu=None, empreinte=None)
    with pytest.raises(ContenuBulletinError, match="avant le gel"):
        contenu_de_version(legacy)


def test_a_group_excluded_from_the_general_total_is_excluded_from_the_bulletin(
    classe, client, db, grille_cours, evaluation_period, tenant_a
):
    """The printed bulletin must agree with the consolidation (invariant
    8): an excluded group's line is shown but does not count. Before the
    fix the bulletin counted it: (60 + 2) / (80 + 10) = 68.89 %."""
    groupe = GroupeCours(ecole_id=tenant_a.id, libelle="Hors total", ordre_affichage=2,
                         entre_dans_total_general=False)
    cours = Course(ecole_id=tenant_a.id, name="Religion", code="REL")
    db.session.add_all([groupe, cours])
    db.session.commit()
    ligne = GrilleCoursLigne(ecole_id=tenant_a.id, grille_cours_id=grille_cours.id,
                             cours_id=cours.id, groupe_cours_id=groupe.id,
                             ordre_affichage=2, ponderation=Decimal("1"))
    db.session.add(ligne)
    db.session.commit()
    db.session.add_all([
        GrilleCoursLigneMaximum(ecole_id=tenant_a.id, grille_cours_ligne_id=ligne.id,
                                periode_id=evaluation_period.id, maximum=Decimal("10")),
        Grade(ecole_id=tenant_a.id, enrollment_id=classe["enrollment"].id,
              grille_cours_ligne_id=ligne.id, period_id=evaluation_period.id,
              score=Decimal("2"), entered_by_id=classe["user"].id),
    ])
    db.session.commit()

    status, html = _bulletin(client, classe)
    assert status == 200
    assert "Religion" in html
    assert "75.00" in html and "68.89" not in html
