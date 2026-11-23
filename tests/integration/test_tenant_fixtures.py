"""Garde-fou : les deux tenants fictifs doivent rester structurellement
divergents. S'ils convergeaient (même nombre de périodes, même barème, même
règle de délibération), la suite ne prouverait plus que le code est
agnostique de l'établissement — voir le tableau dans tests/conftest.py."""

from app.models.academic import EvaluationPeriod
from app.models.deliberation import DeliberationPolicy
from app.models.grille import GrilleCoursLigneMaximum
from app.models.institution import Institution
from app.models.tenant_config import TenantConfig
from tests.conftest import TENANT_A_SPEC, TENANT_B_SPEC


def _structure(ecole_id):
    def scoped(model):
        return model.query.execution_options(skip_tenant_filter=True).filter_by(
            ecole_id=ecole_id
        )

    config = scoped(TenantConfig).one()
    return {
        "periods": scoped(EvaluationPeriod).count(),
        "weights": sorted(p.weight_percent for p in scoped(EvaluationPeriod)),
        "maxima": {m.maximum for m in scoped(GrilleCoursLigneMaximum)},
        "decimals": config.percentage_decimal_places,
        "threshold": {p.passing_threshold_percent for p in scoped(DeliberationPolicy)},
        "eliminatory": config.eliminatory_course_codes,
        "max_failures": config.max_allowed_failures,
        "mentions": len(config.mentions),
    }


def test_fictitious_tenants_diverge_on_every_structural_axis(
    tenant_a, tenant_a_structure, grille_ligne, tenant_b_world
):
    a, b = _structure(tenant_a.id), _structure(tenant_b_world.institution.id)

    assert a["periods"] == TENANT_A_SPEC["periods"] and b["periods"] == TENANT_B_SPEC["periods"]
    assert a["maxima"] == {TENANT_A_SPEC["maximum"]} and b["maxima"] == {TENANT_B_SPEC["maximum"]}
    for axis in a:
        assert a[axis] != b[axis], f"Les tenants fictifs convergent sur « {axis} »."


def test_fictitious_tenants_are_named_as_such(tenant_a, tenant_b):
    for institution in Institution.query.all():
        assert "Fictive" in institution.name
        assert institution.domain.endswith(".testserver")
