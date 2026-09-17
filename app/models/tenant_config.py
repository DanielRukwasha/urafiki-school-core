"""Everything that varies between schools, modeled as data.

One `TenantConfig` row per école (enforced by a unique constraint on the
inherited `ecole_id`). Nothing here has a silent application-level default:
a tenant with an incomplete config must fail loudly when the calculation
engine runs, not fall back to a guessed value — see
`app/services/tenant_calculation.py`.
"""

from __future__ import annotations

from app.extensions import db
from app.models.mixins import TimestampMixin
from app.models.tenant_scope import TenantScopedModel


class TenantConfig(db.Model, TenantScopedModel, TimestampMixin):
    __tablename__ = "tenant_configs"
    __table_args__ = (
        db.UniqueConstraint("ecole_id", name="uq_tenant_config_ecole"),
    )

    id = db.Column(db.Integer, primary_key=True)

    # Selects the registered rule from the shared catalog (see
    # app/models/platform.py::CalculationStrategy) — never a per-school fork.
    calculation_strategy_key = db.Column(
        db.String(50),
        db.ForeignKey("calculation_strategies.key"),
        nullable=False,
    )
    percentage_decimal_places = db.Column(db.Integer, nullable=False, default=2)

    # Mentions scale, e.g. [{"min_percent": "80", "max_percent": "100",
    # "label": "Excellence"}, ...]. Stored as JSON: the number of bands and
    # their labels are themselves per-school configuration, not a fixed enum.
    mentions = db.Column(db.JSON, nullable=False, default=list)

    eliminatory_course_codes = db.Column(db.JSON, nullable=False, default=list)
    max_allowed_failures = db.Column(db.Integer, nullable=True)

    # Report/bulletin rendering (consumed by the Frontend agent's WeasyPrint
    # templates — see ARCHITECTURE_MULTITENANT.md for the exact context
    # signature exposed to Jinja2).
    report_header = db.Column(db.String(300), nullable=True)
    report_legal_mentions = db.Column(db.Text, nullable=True)
    report_signatures = db.Column(db.JSON, nullable=False, default=list)
    logo_url = db.Column(db.String(500), nullable=True)
    primary_color = db.Column(db.String(7), nullable=True)  # e.g. "#1f6feb"

    feature_flags = db.Column(db.JSON, nullable=False, default=dict)

    calculation_strategy = db.relationship("CalculationStrategy")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TenantConfig ecole={self.ecole_id}>"
