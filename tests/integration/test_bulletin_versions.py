"""Invariant 9 : un bulletin publié est immuable ; toute correction crée une
nouvelle version numérotée, avec motif obligatoire, auteur, horodatage UTC
et référence à la version corrigée."""

from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.deliberation_workflow import (
    BulletinVersion,
    DeliberationAction,
    DeliberationAuditLog,
    ImmutableRecordError,
    PeriodPublication,
)
from app.models.grading import Grade
from app.models.user import RoleEnum
from app.services.deliberation_service import TransitionError, publier_correction

MOTIF = "Erreur de report de la cote de mathématiques (copie relue)."


def _versions():
    return (
        BulletinVersion.query.execution_options(skip_tenant_filter=True)
        .order_by(BulletinVersion.numero)
        .all()
    )


@pytest.fixture()
def published(client, db, make_user, tenant_a_structure, school_class, evaluation_period,
              grille_ligne, enrollment):
    user, password = make_user(email="direction@alpha.example", role=RoleEnum.DIRECTION)
    db.session.add(Grade(
        ecole_id=enrollment.ecole_id, enrollment_id=enrollment.id,
        grille_cours_ligne_id=grille_ligne.id, period_id=evaluation_period.id,
        score=Decimal("15"), entered_by_id=user.id,
    ))
    db.session.commit()
    client.post("/auth/login", data={"email": user.email, "password": password})
    base = f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}/consolidation"
    for action in ("submit", "consolidate", "validate", "publish"):
        assert client.post(f"{base}/{action}").status_code == 302, action
    return {"user": user, "base": base, "class": school_class, "period": evaluation_period}


def test_first_publication_creates_version_1_without_motif(published):
    (version,) = _versions()
    assert version.numero == 1
    assert version.motif is None and version.corrige_version_id is None
    assert version.auteur_id == published["user"].id
    assert version.publie_le.utcoffset() is None or version.publie_le.utcoffset().seconds == 0


def test_correction_creates_numbered_justified_version(published, client):
    response = client.post(f"{published['base']}/correction", data={"motif": MOTIF})
    assert response.status_code == 302

    v1, v2 = _versions()
    assert v2.numero == 2
    assert v2.motif == MOTIF
    assert v2.corrige_version_id == v1.id
    assert v2.auteur_id == published["user"].id
    assert v2.publie_le >= v1.publie_le
    publication = PeriodPublication.query.execution_options(skip_tenant_filter=True).one()
    assert publication.version == 2 and publication.published
    audit = (
        DeliberationAuditLog.query.execution_options(skip_tenant_filter=True)
        .filter_by(action=DeliberationAction.PUBLISH)
        .order_by(DeliberationAuditLog.id.desc())
        .first()
    )
    assert MOTIF in audit.new_value


@pytest.mark.parametrize("motif", ["", "   ", "9 lettres"])
def test_correction_without_real_motif_is_refused(published, client, motif):
    response = client.post(f"{published['base']}/correction", data={"motif": motif})
    assert response.status_code == 422
    assert len(_versions()) == 1


def test_correction_requires_a_published_version(
    app, db, make_user, school_class, evaluation_period
):
    user, _ = make_user(role=RoleEnum.DIRECTION)
    with pytest.raises(TransitionError):
        publier_correction(
            school_class_id=school_class.id, period_id=evaluation_period.id,
            motif=MOTIF, user=user,
        )


def test_correction_is_direction_only(published, client, make_user):
    teacher, password = make_user(email="prof@alpha.example", role=RoleEnum.ENSEIGNANT)
    client.get("/auth/logout")
    client.post("/auth/login", data={"email": teacher.email, "password": password})
    assert client.post(f"{published['base']}/correction", data={"motif": MOTIF}).status_code == 403
    assert len(_versions()) == 1


def test_published_version_cannot_be_updated_or_deleted(published, db):
    (version,) = _versions()
    version.motif = "Réécriture silencieuse de l'historique"
    with pytest.raises(ImmutableRecordError):
        db.session.commit()
    db.session.rollback()

    (version,) = _versions()
    db.session.delete(version)
    with pytest.raises(ImmutableRecordError):
        db.session.commit()
    db.session.rollback()
    assert len(_versions()) == 1


def test_database_rejects_unjustified_correction_even_outside_the_service(published, db):
    (v1,) = _versions()
    db.session.add(BulletinVersion(
        ecole_id=v1.ecole_id, publication_id=v1.publication_id, numero=2,
        auteur_id=v1.auteur_id, corrige_version_id=v1.id, motif=None,
    ))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
