"""Central authorization service.

Every contextual permission check in the app goes through here — no route
handler compares `current_user.role` directly. Titulariat and course
assignment are per-class/per-line scopes read from the database
(`TitulaireHistorique`/`DelegationTitulariat`/`TeacherAssignment`), never
a global attribute on the account.

Out-of-scope access is surfaced as 404 (via the `require_*` wrappers),
never 403: a request probing for a class that exists but isn't the
caller's gets the same response as one probing for a class that doesn't
exist at all, so scope can't be enumerated from the response alone.

Published signatures:
    titulaire_effectif(school_class, at=None) -> User | None
    est_titulaire_effectif(user, school_class, at=None) -> bool
    est_attributaire(user, school_class, ligne) -> bool
    peut_lire_cotes_classe(user, school_class) -> bool
    peut_encoder_ligne(user, school_class, ligne, period) -> bool
    peut_soumettre_classe(user, school_class, period) -> bool
    peut_rouvrir_periode(user) -> bool
    peut_valider_bulletin(user) -> bool
    peut_gerer_grille(user) -> bool
    require_lecture_classe(user, school_class) -> None (raises 404)
    require_encodage_ligne(user, school_class, ligne, period) -> None (raises 404)
    require_soumission_classe(user, school_class, period) -> None (raises 404)
    require_direction(user) -> None (raises 404)
    affecter_titulaire(school_class, teacher, *, motif, actor) -> TitulaireHistorique
"""

from __future__ import annotations

from werkzeug.exceptions import NotFound

from app.extensions import db
from app.models.deliberation_workflow import PeriodPublication, PublicationStatus
from app.models.mixins import utcnow
from app.models.teaching import TeacherAssignment
from app.models.titulariat import (
    DelegationTitulariat,
    StatutDelegation,
    TitulaireHistorique,
)
from app.models.user import RoleEnum


def _is_direction(user) -> bool:
    return user is not None and user.role == RoleEnum.DIRECTION


def titulaire_effectif(school_class, at=None):
    """The teacher currently holding titulaire rights for this class,
    honoring an ACTIVE delegation covering `at` (default: now) ahead of
    the class's recorded titulaire. Returns None if neither exists."""
    at = at or utcnow()
    delegation = (
        DelegationTitulariat.query.filter_by(
            school_class_id=school_class.id, statut=StatutDelegation.ACTIVE
        )
        .filter(DelegationTitulariat.date_debut <= at, DelegationTitulariat.date_fin >= at)
        .first()
    )
    if delegation is not None:
        return delegation.delegataire
    return school_class.titulaire


def est_titulaire_effectif(user, school_class, at=None) -> bool:
    effectif = titulaire_effectif(school_class, at=at)
    return effectif is not None and user is not None and effectif.id == user.id


def est_attributaire(user, school_class, ligne) -> bool:
    """Whether `user` is assigned to teach this exact grid line in this
    exact class — the only scope in which a teacher who isn't titulaire
    ever sees or touches a course."""
    return (
        TeacherAssignment.query.filter_by(
            teacher_id=user.id,
            school_class_id=school_class.id,
            grille_cours_ligne_id=ligne.id,
        )
        .filter(TeacherAssignment.archived_at.is_(None))
        .first()
        is not None
    )


def peut_lire_cotes_classe(user, school_class) -> bool:
    """Read-only visibility of every course's grades in a class: Direction,
    or the class's effective titulaire. A plain attributaire only ever
    reads the lines they teach — that's `est_attributaire`, not this."""
    if _is_direction(user):
        return True
    return est_titulaire_effectif(user, school_class)


def _periode_verrouillee(school_class, period) -> bool:
    publication = PeriodPublication.query.filter_by(
        school_class_id=school_class.id, period_id=period.id
    ).first()
    if publication is None:
        return False
    return publication.status != PublicationStatus.DRAFT


def peut_encoder_ligne(user, school_class, ligne, period) -> bool:
    """Write access to one grid line's grades, for one class/period.

    Refused once the period is locked (submitted or beyond) for anyone —
    Direction included: the lock's only path back to write access is a
    journalized reopening or an accepted DemandeCorrection, both handled
    elsewhere, never a bypass here. Below that lock, Direction retains
    the unrestricted write access it has always had (administrative
    oversight); a plain teacher never gets it outside their own
    TeacherAssignment — the titulaire's read-only, class-wide visibility
    never extends to writing a course they don't teach."""
    if _periode_verrouillee(school_class, period):
        return False
    if _is_direction(user):
        return True
    return est_attributaire(user, school_class, ligne)


def peut_soumettre_classe(user, school_class, period) -> bool:
    """Only the class's effective titulaire submits a period for
    consolidation — never a plain attributaire, never Direction directly
    (Direction validates/publishes downstream, it does not submit on the
    titulaire's behalf)."""
    return est_titulaire_effectif(user, school_class)


def peut_rouvrir_periode(user) -> bool:
    return _is_direction(user)


def peut_valider_bulletin(user) -> bool:
    return _is_direction(user)


def peut_gerer_grille(user) -> bool:
    """Grid/referential administration (Niveau, GroupeCours, GrilleCours,
    assignments, titulariat) is Direction-only."""
    return _is_direction(user)


def require_lecture_classe(user, school_class) -> None:
    if not peut_lire_cotes_classe(user, school_class):
        raise NotFound()


def require_encodage_ligne(user, school_class, ligne, period) -> None:
    if not peut_encoder_ligne(user, school_class, ligne, period):
        raise NotFound()


def require_soumission_classe(user, school_class, period) -> None:
    if not peut_soumettre_classe(user, school_class, period):
        raise NotFound()


def require_direction(user) -> None:
    if not _is_direction(user):
        raise NotFound()


def affecter_titulaire(school_class, teacher, *, motif, actor) -> TitulaireHistorique:
    """Assign `teacher` as titulaire of `school_class`, closing any
    currently-open TitulaireHistorique row for the class first — the
    only way this function allows two rows to coexist for a class is
    consecutively in time, never concurrently."""
    now = utcnow()
    ouverte = (
        TitulaireHistorique.query.filter_by(school_class_id=school_class.id, date_fin=None)
        .first()
    )
    if ouverte is not None:
        ouverte.date_fin = now

    nouvelle = TitulaireHistorique(
        school_class_id=school_class.id,
        teacher_id=teacher.id,
        date_debut=now,
        motif=motif,
        created_by_id=actor.id,
    )
    db.session.add(nouvelle)
    school_class.titulaire_id = teacher.id
    db.session.commit()
    return nouvelle
