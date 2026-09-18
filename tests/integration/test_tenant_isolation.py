"""Tests bloquants — isolation multi-tenant.

Ces tests tournent sur deux tenants fictifs simultanés (tenant_a / Institut
Mont Carmel et tenant_b / Lycée Kasa-Vubu, voir tests/conftest.py) avec des
barèmes et configurations volontairement différents. Toute pénétration
entre les deux ici doit faire échouer la CI — voir
ARCHITECTURE_MULTITENANT.md. Aucune exception.
"""

import datetime

import pytest

from app.models.academic import AcademicYear
from app.models.platform import TenantAccessAuditLog, TenantAccessEventType
from app.models.user import RoleEnum, User
from app.security.tenant import resolve_tenant
from app.services.tenant_calculation import (
    IncompleteTenantConfigError,
    resolve_tenant_calculation,
)
from app.services.tenant_provisioning import provision_tenant


def test_orm_query_cannot_see_other_tenants_rows(app, db, tenant_a, tenant_b, make_user):
    make_user(email="direction@a.example", ecole_id=tenant_a.id)
    make_user(email="direction@b.example", ecole_id=tenant_b.id)

    with app.test_request_context("/", base_url=f"http://{tenant_a.domain}"):
        resolve_tenant()
        assert {u.email for u in User.query.all()} == {"direction@a.example"}

    with app.test_request_context("/", base_url=f"http://{tenant_b.domain}"):
        resolve_tenant()
        assert {u.email for u in User.query.all()} == {"direction@b.example"}

    # Re-checking tenant_a after a tenant_b request: guards against the
    # statement-cache regression documented in app/models/tenant_scope.py
    # (a closure not properly tracked as a per-execution bind value would
    # silently freeze on tenant_b's id here).
    with app.test_request_context("/", base_url=f"http://{tenant_a.domain}"):
        resolve_tenant()
        assert {u.email for u in User.query.all()} == {"direction@a.example"}


def test_request_with_no_resolvable_tenant_sees_nothing(app, db, tenant_a, make_user):
    make_user(email="direction@a.example", ecole_id=tenant_a.id)

    with app.test_request_context("/"):
        # No before_request ran (test_request_context doesn't trigger it),
        # so g.current_ecole_id is simply unset — the fail-closed default.
        assert User.query.all() == []


def test_duplicate_label_and_matricule_across_tenants_is_allowed(db, tenant_a, tenant_b):
    """The absolute rule in practice: two schools sharing an academic-year
    label or a student matricule must not collide — only ecole_id-scoped
    uniqueness is enforced."""
    from app.models.student import Student

    year_a = AcademicYear(
        ecole_id=tenant_a.id,
        label="2025-2026",
        start_date=datetime.date(2025, 9, 1),
        end_date=datetime.date(2026, 6, 30),
        is_current=True,
    )
    year_b = AcademicYear(
        ecole_id=tenant_b.id,
        label="2025-2026",
        start_date=datetime.date(2025, 9, 1),
        end_date=datetime.date(2026, 6, 30),
        is_current=True,
    )
    student_a = Student(ecole_id=tenant_a.id, matricule="0001", first_name="Alice", last_name="A")
    student_b = Student(ecole_id=tenant_b.id, matricule="0001", first_name="Bob", last_name="B")
    db.session.add_all([year_a, year_b, student_a, student_b])
    db.session.commit()  # must not raise IntegrityError

    assert year_a.id != year_b.id
    assert student_a.global_student_uid != student_b.global_student_uid


def test_login_session_rejected_when_replayed_on_another_tenants_domain(
    app, db, tenant_a, tenant_b, make_user
):
    """Simulates a session cookie being presented on the wrong tenant's
    domain (not achievable via a real browser's same-origin cookie scoping,
    but exactly the class of bug a misconfigured proxy or a forged cookie
    could produce) — must be rejected and audit-logged, never silently
    treated as anonymous."""
    make_user(
        email="direction@a.example",
        password="Secret123!",
        role=RoleEnum.DIRECTION,
        ecole_id=tenant_a.id,
    )

    client = app.test_client()
    base_a = f"http://{tenant_a.domain}"
    base_b = f"http://{tenant_b.domain}"

    login_response = client.post(
        "/auth/login",
        data={"email": "direction@a.example", "password": "Secret123!"},
        base_url=base_a,
    )
    assert login_response.status_code == 302
    session_cookie = client.get_cookie("session", domain=tenant_a.domain)
    assert session_cookie is not None

    # Replay the exact same session cookie value against tenant_b's domain.
    client.set_cookie(
        domain=tenant_b.domain, key="session", value=session_cookie.value, origin_only=False
    )
    response = client.get("/admin/", base_url=base_b)
    assert response.status_code == 403

    logs = (
        TenantAccessAuditLog.query.execution_options(skip_tenant_filter=True)
        .filter_by(event_type=TenantAccessEventType.CROSS_TENANT_SESSION_REJECTED)
        .all()
    )
    assert len(logs) == 1
    assert logs[0].ecole_id == tenant_b.id


def test_calculation_config_does_not_leak_between_tenants(app, tenant_a, tenant_b):
    resolved_a = resolve_tenant_calculation(tenant_a.id)
    resolved_b = resolve_tenant_calculation(tenant_b.id)

    assert resolved_a.percentage_decimal_places == 2
    assert resolved_b.percentage_decimal_places == 1

    # Ambient request tenant is tenant_a; explicitly resolving tenant_b's
    # config must still return tenant_b's own values, not tenant_a's.
    with app.test_request_context("/", base_url=f"http://{tenant_a.domain}"):
        resolve_tenant()
        resolved_b_again = resolve_tenant_calculation(tenant_b.id)
        assert resolved_b_again.percentage_decimal_places == 1


def test_incomplete_tenant_config_raises_explicitly(db):
    from app.models.institution import Institution

    orphan = Institution(name="Ecole Sans Config", short_code="ESC", domain="esc.testserver")
    db.session.add(orphan)
    db.session.commit()

    with pytest.raises(IncompleteTenantConfigError):
        resolve_tenant_calculation(orphan.id)


def test_provision_tenant_creates_a_working_tenant(db):
    result = provision_tenant(
        name="Ecole Provisionnee",
        short_code="EPR",
        domain="eprovisionnee.urafiki.org",
        direction_email="direction@eprovisionnee.example",
        direction_first_name="Nouvelle",
        direction_last_name="Direction",
        academic_year_label="2026-2027",
        academic_year_start=datetime.date(2026, 9, 1),
        academic_year_end=datetime.date(2027, 6, 30),
    )

    assert result.institution.id is not None
    assert result.institution.is_active is True
    assert result.direction_user.check_password(result.one_time_password) is True
    assert result.direction_user.ecole_id == result.institution.id
    assert result.academic_year.ecole_id == result.institution.id

    resolved = resolve_tenant_calculation(result.institution.id)
    assert resolved.strategy_key == "STANDARD"
