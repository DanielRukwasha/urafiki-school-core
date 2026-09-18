"""Automatic tenant isolation for SQLAlchemy models.

`TenantScopedModel` is the base every per-école table inherits from. It does
two things without requiring any route or service to remember to filter:

1. Adds a non-nullable, indexed ``ecole_id`` column, defaulted at flush time
   from ``g.current_ecole_id`` (set by the tenant-resolution middleware —
   see ``app/security/tenant.py``) unless the caller supplies it explicitly.
2. Registers a SQLAlchemy ``do_orm_execute`` event that injects
   ``WHERE ecole_id = :current_tenant`` into every SELECT (and ORM-enabled
   UPDATE/DELETE) against any subclass, via ``with_loader_criteria``.

Fail-closed by design: if no tenant has been resolved for the current
request (``g.current_ecole_id`` is unset), the injected criteria is
``false()`` — queries return zero rows rather than leaking every tenant's
data. This is the application-level half of isolation; PostgreSQL Row
Level Security (see the multi-tenant migration) is the independent second
layer that holds even if this code path is bypassed by a bug.
"""

from __future__ import annotations

from flask import g, has_request_context
from sqlalchemy import event, text
from sqlalchemy.orm import Session, declared_attr, with_loader_criteria
from sqlalchemy.sql import false

from app.extensions import db


def current_ecole_id() -> int | None:
    """The tenant resolved for the current request, or None outside one."""
    if not has_request_context():
        return None
    return getattr(g, "current_ecole_id", None)


class TenantScopedModel:
    """Mixin for every model whose rows belong to exactly one école."""

    @declared_attr
    def ecole_id(cls):  # noqa: N805
        return db.Column(
            db.Integer,
            db.ForeignKey("institutions.id"),
            nullable=False,
            index=True,
            default=current_ecole_id,
        )


def sync_rls_tenant_context() -> None:
    """Push the current tenant into the PostgreSQL session, for Row Level
    Security policies (the second, independent isolation layer — see
    ARCHITECTURE_MULTITENANT.md).

    Must be called explicitly right after `g.current_ecole_id` changes
    (from ``app/security/tenant.py::resolve_tenant``), not left to a
    ``do_begin``-style event: the tenant-resolution query itself runs
    before the tenant is known, which would otherwise lock in an empty
    session variable for the rest of that transaction.

    No-op on SQLite (used only for local dev/test convenience — RLS is a
    PostgreSQL feature) and a no-op if the connected role owns the tables,
    since PostgreSQL never applies RLS to a table's owner. Deployments must
    run the web process as a non-owning role for this to take effect; see
    ARCHITECTURE_MULTITENANT.md.
    """
    bind = db.session.get_bind()
    if bind.dialect.name != "postgresql":
        return
    ecole_id = current_ecole_id()
    db.session.execute(
        text("SELECT set_config('app.current_ecole_id', COALESCE(:value, ''), false)"),
        {"value": str(ecole_id) if ecole_id is not None else None},
    )


@event.listens_for(Session, "do_orm_execute")
def _apply_tenant_isolation(execute_state) -> None:
    if not (execute_state.is_select or execute_state.is_update or execute_state.is_delete):
        return
    if execute_state.execution_options.get("skip_tenant_filter", False):
        return

    ecole_id = current_ecole_id()

    # `ecole_id` must be captured as a genuine closure variable (a free
    # variable resolved from the enclosing scope), NOT a default argument
    # (`def _criteria(cls, _ecole_id=ecole_id)`) and not produced by calling
    # another function from inside `_criteria`. `with_loader_criteria`
    # caches the compiled statement per query shape and relies on
    # bytecode-level closure-variable tracking to re-parameterize that
    # cached plan on each call; a default argument or a nested function
    # call is NOT tracked, so the cache silently freezes on whichever value
    # was seen the first time this query shape was compiled — the exact
    # failure mode this must not regress to. Verified via
    # tests/integration/test_tenant_isolation.py, which fails loudly if
    # this freezes again.
    def _criteria(cls):
        if ecole_id is None:
            return false()
        return cls.ecole_id == ecole_id

    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(TenantScopedModel, _criteria, include_aliases=True)
    )
