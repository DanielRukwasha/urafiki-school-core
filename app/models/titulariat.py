"""Titulariat is a per-class, time-bounded scope — never a global account
attribute. These three tables are the source of truth the authorization
service (app/services/authorization_service.py) reads; `SchoolClass.titulaire_id`
is only a denormalized "who is titulaire right now" convenience for fast
reads and is kept in sync with `TitulaireHistorique` by the service layer,
never written directly from a route.
"""

import enum

from app.extensions import db
from app.models.mixins import TimestampMixin, utcnow
from app.models.tenant_scope import TenantScopedModel


class TitulaireHistorique(db.Model, TenantScopedModel, TimestampMixin):
    """One stretch of time during which a given teacher was titulaire of a
    given class. `date_fin` NULL means "still current". The service layer
    is responsible for closing the previous open row (setting its
    `date_fin`) before opening a new one — never two open rows for the
    same class at once; there is no database exclusion constraint for
    this (not portably expressible against SQLite, which this project
    also runs its test suite against), so it is enforced exclusively in
    `app.services.authorization_service.affecter_titulaire`.
    """

    __tablename__ = "titulaire_historiques"
    __table_args__ = (
        db.Index("ix_titulaire_hist_ecole_classe_debut", "ecole_id", "school_class_id", "date_debut"),
    )

    id = db.Column(db.Integer, primary_key=True)
    school_class_id = db.Column(
        db.Integer, db.ForeignKey("school_classes.id"), nullable=False, index=True
    )
    teacher_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    date_debut = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    date_fin = db.Column(db.DateTime(timezone=True), nullable=True)
    motif = db.Column(db.String(300), nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    school_class = db.relationship("SchoolClass")
    teacher = db.relationship("User", foreign_keys=[teacher_id])
    created_by = db.relationship("User", foreign_keys=[created_by_id])

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TitulaireHistorique classe={self.school_class_id} teacher={self.teacher_id}>"


class StatutDelegation(str, enum.Enum):
    ACTIVE = "ACTIVE"
    REVOQUEE = "REVOQUEE"
    EXPIREE = "EXPIREE"


class DelegationTitulariat(db.Model, TenantScopedModel, TimestampMixin):
    """A temporary, bounded grant of the titulaire's rights on one class to
    another teacher (e.g. covering an absence) — the titulaire of record
    does not change; `TitulaireHistorique` is untouched. The authorization
    service's "titulaire effectif" resolver checks for an ACTIVE delegation
    covering *now* before falling back to the class's recorded titulaire.
    """

    __tablename__ = "delegations_titulariat"
    __table_args__ = (
        db.CheckConstraint("date_fin > date_debut", name="ck_delegation_fin_apres_debut"),
    )

    id = db.Column(db.Integer, primary_key=True)
    school_class_id = db.Column(
        db.Integer, db.ForeignKey("school_classes.id"), nullable=False, index=True
    )
    delegant_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    delegataire_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    date_debut = db.Column(db.DateTime(timezone=True), nullable=False)
    date_fin = db.Column(db.DateTime(timezone=True), nullable=False)
    motif = db.Column(db.String(300), nullable=False)
    statut = db.Column(db.Enum(StatutDelegation), nullable=False, default=StatutDelegation.ACTIVE)
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=True)
    revoked_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    school_class = db.relationship("SchoolClass")
    delegant = db.relationship("User", foreign_keys=[delegant_id])
    delegataire = db.relationship("User", foreign_keys=[delegataire_id])
    revoked_by = db.relationship("User", foreign_keys=[revoked_by_id])

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<DelegationTitulariat classe={self.school_class_id} "
            f"delegataire={self.delegataire_id} statut={self.statut}>"
        )


class StatutDemandeCorrection(str, enum.Enum):
    EN_ATTENTE = "EN_ATTENTE"
    ACCEPTEE = "ACCEPTEE"
    REFUSEE = "REFUSEE"
    TRAITEE = "TRAITEE"


class DemandeCorrection(db.Model, TenantScopedModel, TimestampMixin):
    """A request to reopen a single, already-locked or already-published
    grade for correction. Raised by a teacher (or titulaire) who no longer
    has write access once a period is submitted/closed; accepted or
    refused by Direction. Acceptance does not itself change the grade —
    it authorizes one, journalized write, which still goes through the
    normal Grade update path (and its own GradeAuditLog entry) so the
    correction is traceable end to end.
    """

    __tablename__ = "demandes_correction"

    id = db.Column(db.Integer, primary_key=True)
    grade_id = db.Column(db.Integer, db.ForeignKey("grades.id"), nullable=False, index=True)
    demandeur_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    motif = db.Column(db.String(500), nullable=False)
    statut = db.Column(
        db.Enum(StatutDemandeCorrection), nullable=False, default=StatutDemandeCorrection.EN_ATTENTE
    )
    traite_par_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    traite_le = db.Column(db.DateTime(timezone=True), nullable=True)
    commentaire_traitement = db.Column(db.String(500), nullable=True)

    grade = db.relationship("Grade")
    demandeur = db.relationship("User", foreign_keys=[demandeur_id])
    traite_par = db.relationship("User", foreign_keys=[traite_par_id])

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DemandeCorrection grade={self.grade_id} statut={self.statut}>"
