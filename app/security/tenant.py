"""Tenant resolution: Host header -> ecole_id, once per request.

`ecole_id` is NEVER accepted from a URL parameter, a form field, a header,
or a cookie a client can set. It is deduced exclusively from the request's
domain (via `Institution.domain` / `Institution.custom_domain`), then
cross-checked against the authenticated account's own `ecole_id`. Any
divergence between the two is rejected — the session is dropped and the
event is written to that tenant's `TenantAccessAuditLog` — never silently
trusted.

A request whose domain resolves to no active tenant is rejected outright
with an explicit error; there is no silent fallback tenant.
"""

from __future__ import annotations

from flask import Flask, abort, g, request
from flask_login import current_user, logout_user

from app.extensions import db
from app.models.institution import Institution
from app.models.platform import TenantAccessAuditLog, TenantAccessEventType
from app.models.tenant_scope import sync_rls_tenant_context

# Requests to these hosts never resolve to a tenant — they are routed to the
# platform super-admin console instead (see the "Console de
# super-administration" issue). No école data is reachable from here.
PLATFORM_ADMIN_HOST_PREFIXES = ("admin.", "console.")


def _request_host() -> str:
    return request.host.rsplit(":", 1)[0].lower()


def resolve_tenant() -> None:
    g.current_ecole_id = None
    g.is_platform_admin_context = False

    host = _request_host()

    if any(host.startswith(prefix) for prefix in PLATFORM_ADMIN_HOST_PREFIXES):
        g.is_platform_admin_context = True
        sync_rls_tenant_context()
        return

    institution = Institution.query.filter(
        (Institution.domain == host) | (Institution.custom_domain == host)
    ).first()

    if institution is None or not institution.is_active:
        sync_rls_tenant_context()
        abort(404, description="Aucune école active ne correspond à ce domaine.")

    g.current_ecole_id = institution.id
    sync_rls_tenant_context()

    if current_user.is_authenticated and current_user.ecole_id != institution.id:
        _reject_cross_tenant_session(institution.id)


def _reject_cross_tenant_session(resolved_ecole_id: int) -> None:
    entry = TenantAccessAuditLog(
        ecole_id=resolved_ecole_id,
        event_type=TenantAccessEventType.CROSS_TENANT_SESSION_REJECTED,
        actor_user_id=current_user.id,
        reason=(
            f"Session utilisateur ecole_id={current_user.ecole_id} presentee "
            f"sur le domaine de l'ecole ecole_id={resolved_ecole_id}."
        ),
        resource=request.path,
    )
    db.session.add(entry)
    db.session.commit()
    logout_user()
    abort(403, description="Session invalide pour ce domaine.")


def init_tenant_resolution(app: Flask) -> None:
    app.before_request(resolve_tenant)
