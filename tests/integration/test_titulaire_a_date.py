"""Issue #84: the titulaire at a past date is read from TitulaireHistorique,
never from the class's current titulaire, then a delegation in force at
that date takes precedence. A bulletin must be able to say who was
titulaire when it was submitted, even after the titulaire changed."""

import datetime

import pytest

from app.models.titulariat import DelegationTitulariat, StatutDelegation, TitulaireHistorique
from app.security.tenant import resolve_tenant
from app.services.authorization_service import (
    est_titulaire_effectif,
    titulaire_effectif,
)

UTC = datetime.UTC


def d(month, day):
    return datetime.datetime(2026, month, day, 8, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _tenant_request_context(app, tenant_a):
    """Service calls below run outside any HTTP request: push a resolved
    request context so tenant-scoped queries see tenant_a's data."""
    with app.test_request_context("/", base_url=f"http://{tenant_a.domain}"):
        resolve_tenant()
        yield


@pytest.fixture()
def x_puis_y(db, tenant_a, make_user, school_class):
    """X titulaire until 1 March, Y from 1 March on; Y is the class's
    current titulaire."""
    x, _ = make_user(email="x@example.com")
    y, _ = make_user(email="y@example.com")
    direction, _ = make_user(email="dir@example.com")
    for teacher, debut, fin in ((x, d(1, 5), d(3, 1)), (y, d(3, 1), None)):
        db.session.add(
            TitulaireHistorique(
                ecole_id=tenant_a.id,
                school_class_id=school_class.id,
                teacher_id=teacher.id,
                date_debut=debut,
                date_fin=fin,
                created_by_id=direction.id,
            )
        )
    school_class.titulaire_id = y.id
    db.session.commit()
    return x, y


def _delegation(db, tenant_a, school_class, delegant, delegataire, debut, fin, **extra):
    db.session.add(
        DelegationTitulariat(
            ecole_id=tenant_a.id,
            school_class_id=school_class.id,
            delegant_id=delegant.id,
            delegataire_id=delegataire.id,
            date_debut=debut,
            date_fin=fin,
            motif="Absence prolongée",
            **extra,
        )
    )
    db.session.commit()


def test_past_date_returns_the_titulaire_of_that_date(x_puis_y, school_class):
    # Refutation of #84: before the fix this returned Y (the present).
    x, y = x_puis_y
    assert titulaire_effectif(school_class, at=d(2, 15)) == x
    assert est_titulaire_effectif(x, school_class, at=d(2, 15))
    assert not est_titulaire_effectif(y, school_class, at=d(2, 15))


def test_change_date_belongs_to_the_new_titulaire(x_puis_y, school_class):
    # Half-open interval: X's stretch ends at 1 March, Y's starts there.
    x, y = x_puis_y
    assert titulaire_effectif(school_class, at=d(3, 1)) == y
    assert titulaire_effectif(school_class, at=d(3, 1) - datetime.timedelta(seconds=1)) == x


def test_present_is_unchanged(x_puis_y, school_class):
    _, y = x_puis_y
    assert titulaire_effectif(school_class) == y
    assert titulaire_effectif(school_class, at=d(6, 1)) == y


def test_date_before_any_history_is_nobody_not_the_current_titulaire(x_puis_y, school_class):
    assert titulaire_effectif(school_class, at=d(1, 1)) is None


def test_delegation_in_force_at_the_past_date_takes_precedence(
    db, tenant_a, make_user, x_puis_y, school_class
):
    x, _ = x_puis_y
    z, _ = make_user(email="z@example.com")
    # Since expired: it was still in force during its window.
    _delegation(db, tenant_a, school_class, x, z, d(2, 10), d(2, 20),
                statut=StatutDelegation.EXPIREE)
    assert titulaire_effectif(school_class, at=d(2, 15)) == z
    assert titulaire_effectif(school_class, at=d(2, 25)) == x


def test_delegation_revoked_before_the_date_does_not_apply(
    db, tenant_a, make_user, x_puis_y, school_class
):
    x, _ = x_puis_y
    z, _ = make_user(email="z@example.com")
    _delegation(db, tenant_a, school_class, x, z, d(2, 10), d(2, 20),
                statut=StatutDelegation.REVOQUEE, revoked_at=d(2, 12))
    assert titulaire_effectif(school_class, at=d(2, 11)) == z
    assert titulaire_effectif(school_class, at=d(2, 15)) == x


def test_delegation_stops_at_the_exact_revocation_instant(
    db, tenant_a, make_user, x_puis_y, school_class
):
    # Exclusive bound: revoked_at > at. At the revocation instant itself
    # the delegation no longer applies; one microsecond before, it does.
    x, _ = x_puis_y
    z, _ = make_user(email="z@example.com")
    revoked_at = d(2, 12)
    _delegation(db, tenant_a, school_class, x, z, d(2, 10), d(2, 20),
                statut=StatutDelegation.REVOQUEE, revoked_at=revoked_at)
    assert titulaire_effectif(school_class, at=revoked_at) == x
    assert titulaire_effectif(school_class, at=revoked_at - datetime.timedelta(microseconds=1)) == z


def test_delegation_without_history_never_yields_a_delegate(
    db, tenant_a, make_user, school_class
):
    # Refutation of the Frontend review blocker on #128: a class whose
    # history was never recorded (no TitulaireHistorique row) but with a
    # delegation covering the date must still answer None.
    delegant, _ = make_user(email="delegant@example.com")
    z, _ = make_user(email="z@example.com")
    school_class.titulaire_id = delegant.id
    db.session.commit()
    _delegation(db, tenant_a, school_class, delegant, z, d(2, 10), d(2, 20),
                statut=StatutDelegation.EXPIREE)
    assert titulaire_effectif(school_class, at=d(2, 15)) is None
    assert not est_titulaire_effectif(z, school_class, at=d(2, 15))


def test_delegation_outside_any_history_stretch_never_yields_a_delegate(
    db, tenant_a, make_user, x_puis_y, school_class
):
    # Same rule before the first history row of a recorded class.
    x, _ = x_puis_y
    z, _ = make_user(email="z@example.com")
    _delegation(db, tenant_a, school_class, x, z, d(1, 1), d(1, 4),
                statut=StatutDelegation.EXPIREE)
    assert titulaire_effectif(school_class, at=d(1, 2)) is None
