"""Session class closing the identity-map bypass of tenant isolation.

`app/models/tenant_scope.py` injects ``WHERE ecole_id = :tenant`` into every
ORM statement. ``Session.get()`` (and therefore ``db.get_or_404()``) does
not always emit a statement: when the row is already in the session's
identity map it is returned directly, and no criteria ever applies. Any
tenant-B object that reached the identity map — through a
``skip_tenant_filter`` query, a shared session in a background job or a
test — would then be served to a tenant-A request by a plain
``get_or_404(Model, id_from_the_url)``.

This session re-checks ownership on every ``get()`` made inside a request:
a tenant-scoped instance whose ``ecole_id`` is not the request's resolved
tenant is reported as absent (``None``, hence a 404), exactly like a row
the SQL filter would have excluded. ``skip_tenant_filter`` stays the only,
explicit way around it (used by the login user loader).
"""

from __future__ import annotations

from flask import g, has_request_context
from flask_sqlalchemy.session import Session


class TenantScopedSession(Session):
    def get(self, entity, ident, **kwargs):
        instance = super().get(entity, ident, **kwargs)
        if instance is None or not has_request_context():
            return instance
        if (kwargs.get("execution_options") or {}).get("skip_tenant_filter", False):
            return instance

        from app.models.tenant_scope import TenantScopedModel

        if not isinstance(instance, TenantScopedModel):
            return instance
        if instance.ecole_id != getattr(g, "current_ecole_id", None):
            return None
        return instance
