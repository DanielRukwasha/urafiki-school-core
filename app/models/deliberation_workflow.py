"""Manual deliberation overrides, the consolidation/publication state
machine, and the audit trail for both — the backend contract issue #42
asked for, consumed by the portal's consolidation/deliberation views.

Kept separate from `app/models/deliberation.py` (DeliberationPolicy,
P2's configurable pass/fail threshold) since these three model a workflow
built on top of that policy, not the policy itself.
"""

from __future__ import annotations

import enum

from app.extensions import db
from app.models.mixins import TimestampMixin, utcnow
from app.models.tenant_scope import TenantScopedModel


class ManualDecision(str, enum.Enum):
    ADMITTED = "ADMITTED"
    DEFERRED = "DEFERRED"


class DeliberationOverride(db.Model, TenantScopedModel, TimestampMixin):
    """A DIRECTION-entered manual decision for one student, one period.

    The automatic decision (computed fresh each time from grades, never
    stored) always stays visible alongside this — a manual override
    supplements it, it never silently replaces or hides it. One row per
    (enrollment, period): re-submitting the override form updates it in
    place rather than layering a second decision, but every prior value is
    still recoverable from `DeliberationAuditLog`.
    """

    __tablename__ = "deliberation_overrides"
    __table_args__ = (
        db.UniqueConstraint(
            "ecole_id",
            "enrollment_id",
            "period_id",
            name="uq_override_ecole_enrollment_period",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    enrollment_id = db.Column(
        db.Integer, db.ForeignKey("enrollments.id"), nullable=False, index=True
    )
    period_id = db.Column(
        db.Integer, db.ForeignKey("evaluation_periods.id"), nullable=False, index=True
    )
    decision = db.Column(db.Enum(ManualDecision), nullable=False)
    reason = db.Column(db.String(1000), nullable=False)
    decided_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    enrollment = db.relationship("Enrollment")
    period = db.relationship("EvaluationPeriod")
    decided_by = db.relationship("User")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DeliberationOverride enrollment={self.enrollment_id} period={self.period_id}>"


class PublicationStatus(str, enum.Enum):
    DRAFT = "DRAFT"  # encodage en cours
    SUBMITTED = "SUBMITTED"  # soumis par le titulaire
    CONSOLIDATED = "CONSOLIDATED"
    VALIDATED = "VALIDATED"  # validé par la direction
    PUBLISHED = "PUBLISHED"


# A transition is valid only from the state it's named after, in this
# fixed order — no skipping a step, no going backward. There is
# deliberately no "unpublish": a published version is the one families
# see, and un-publishing it is a policy decision for a later issue, not
# an implicit side effect of this state machine.
#
# "submit" belongs to the class's titulaire (a per-class scope, never a
# global role — see SchoolClass.titulaire_id); "consolidate"/"validate"/
# "publish" stay DIRECTION-only. Actor authorization lives in the route
# layer (it needs the class, not just the action name), not here.
NEXT_STATUS = {
    PublicationStatus.DRAFT: PublicationStatus.SUBMITTED,
    PublicationStatus.SUBMITTED: PublicationStatus.CONSOLIDATED,
    PublicationStatus.CONSOLIDATED: PublicationStatus.VALIDATED,
    PublicationStatus.VALIDATED: PublicationStatus.PUBLISHED,
}
TRANSITION_ACTION_FOR_STATUS = {
    PublicationStatus.SUBMITTED: "submit",
    PublicationStatus.CONSOLIDATED: "consolidate",
    PublicationStatus.VALIDATED: "validate",
    PublicationStatus.PUBLISHED: "publish",
}


class PeriodPublication(db.Model, TenantScopedModel, TimestampMixin):
    """Tracks one class/period's position in the consolidate -> validate ->
    publish workflow. `version` increments only on `publish`, since that's
    the only transition that produces a new official, family-facing
    result — consolidating or validating again after edits doesn't need a
    new version number, only a new publish does.
    """

    __tablename__ = "period_publications"
    __table_args__ = (
        db.UniqueConstraint(
            "ecole_id",
            "school_class_id",
            "period_id",
            name="uq_publication_ecole_class_period",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    school_class_id = db.Column(
        db.Integer, db.ForeignKey("school_classes.id"), nullable=False, index=True
    )
    period_id = db.Column(
        db.Integer, db.ForeignKey("evaluation_periods.id"), nullable=False, index=True
    )
    status = db.Column(
        db.Enum(PublicationStatus), nullable=False, default=PublicationStatus.DRAFT
    )
    version = db.Column(db.Integer, nullable=False, default=0)
    submitted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    consolidated_at = db.Column(db.DateTime(timezone=True), nullable=True)
    validated_at = db.Column(db.DateTime(timezone=True), nullable=True)
    published_at = db.Column(db.DateTime(timezone=True), nullable=True)

    school_class = db.relationship("SchoolClass")
    period = db.relationship("EvaluationPeriod")

    @property
    def published(self) -> bool:
        return self.status == PublicationStatus.PUBLISHED

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PeriodPublication class={self.school_class_id} period={self.period_id} {self.status}>"


class DeliberationAction(str, enum.Enum):
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"
    SUBMIT = "SUBMIT"
    CONSOLIDATE = "CONSOLIDATE"
    VALIDATE = "VALIDATE"
    PUBLISH = "PUBLISH"


class DeliberationAuditLog(db.Model, TenantScopedModel):
    """Immutable trail for deliberation-workflow actions — manual
    overrides and publication transitions. Grade-level create/update/
    delete already has its own trail (`GradeAuditLog`, from P2); the
    portal's audit view merges both, sorted by time, rather than
    duplicating grade changes into this table too."""

    __tablename__ = "deliberation_audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.Enum(DeliberationAction), nullable=False)
    enrollment_id = db.Column(
        db.Integer, db.ForeignKey("enrollments.id"), nullable=True, index=True
    )
    period_id = db.Column(
        db.Integer, db.ForeignKey("evaluation_periods.id"), nullable=False, index=True
    )
    school_class_id = db.Column(
        db.Integer, db.ForeignKey("school_classes.id"), nullable=False, index=True
    )
    old_value = db.Column(db.String(1000), nullable=True)
    new_value = db.Column(db.String(1000), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    enrollment = db.relationship("Enrollment")
    period = db.relationship("EvaluationPeriod")
    school_class = db.relationship("SchoolClass")
    user = db.relationship("User")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DeliberationAuditLog {self.action} period={self.period_id}>"
