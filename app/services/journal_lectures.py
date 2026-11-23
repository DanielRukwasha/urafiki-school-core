"""Journalisation des lectures sensibles (invariant 10), par décorateur.

Les écritures ont déjà leurs journaux (GradeAuditLog, DeliberationAuditLog).
Ce module couvre ce qui manquait : la consultation d'un bulletin, l'export
de données et l'accès d'un super-administrateur à un tenant.

La règle : on décore la fonction qui PRODUIT la donnée sensible, une seule
fois, jamais chaque route qui l'appelle. Toute nouvelle route qui passe par
une fonction décorée est journalisée sans y penser ; une route qui
contournerait ces fonctions est une anomalie de revue.

- `journaliser_lecture(kind, ...)` : journalise APRÈS une production réussie
  (une tentative refusée en 404 n'a rien lu).
- `journaliser_acces_super_admin` : journalise AVANT l'exécution, motif
  obligatoire — la tentative d'accès elle-même est l'événement.

Contrat transactionnel : chaque décorateur valide (commit) sa propre ligne
de journal. Il ne doit donc jamais valider au passage des écritures de
l'appelant : si la session contient des écritures en attente au moment de
journaliser, il lève `JournalisationError` au lieu de les valider en
silence. Sont visées les écritures encore en session ET celles déjà
envoyées à la base sans être validées (flush explicite, ou autoflush
déclenché par une requête de la lecture décorée elle-même) : un flush qui
écrit marque la transaction, la marque tombe quand la transaction racine se
termine (commit, rollback, close). Une fonction décorée est une lecture ;
l'appelant qui écrit valide ou annule ses écritures avant de lire.
"""

from __future__ import annotations

import functools
import getpass
from collections.abc import Callable

from flask import has_request_context, request
from flask_login import current_user
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.extensions import db
from app.models.journal import SensitiveReadKind, SensitiveReadLog
from app.models.platform import TenantAccessAuditLog, TenantAccessEventType
from app.models.tenant_scope import current_ecole_id


class JournalisationError(RuntimeError):
    """Raised when an access cannot be journaled — the access is then
    refused rather than performed silently."""


def _request_resource() -> str:
    return request.full_path.rstrip("?") if has_request_context() else "hors requête"


def _request_ip() -> str | None:
    return request.remote_addr if has_request_context() else None


def _authenticated_user_id() -> int | None:
    if has_request_context() and current_user.is_authenticated:
        return current_user.id
    return None


_ECRITURES_FLUSHEES = "journal_lectures.ecritures_flushees"


@event.listens_for(Session, "after_flush")
def _marquer_ecritures_flushees(session, flush_context):
    # A flush only runs when the session holds changes, so every flush
    # here wrote rows that the current transaction has not committed yet.
    types = {type(o).__name__ for o in (*session.new, *session.dirty, *session.deleted)}
    session.info.setdefault(_ECRITURES_FLUSHEES, set()).update(types or {"?"})


@event.listens_for(Session, "after_transaction_end")
def _oublier_ecritures_flushees(session, transaction):
    if transaction.parent is None:
        session.info.pop(_ECRITURES_FLUSHEES, None)


def _refuser_ecritures_en_attente(fonction: str) -> None:
    en_attente = [
        *db.session.new,
        *db.session.deleted,
        *(objet for objet in db.session.dirty if db.session.is_modified(objet)),
    ]
    flushees = db.session.info.get(_ECRITURES_FLUSHEES, set())
    if en_attente or flushees:
        types = sorted({type(o).__name__ for o in en_attente} | flushees)
        raise JournalisationError(
            f"Journalisation de {fonction} : écriture(s) de l'appelant non validée(s) "
            f"({len(en_attente)} en attente, {'des' if flushees else 'aucune'} déjà envoyée(s) "
            f"à la base ; {', '.join(types)}). Le journal ne les validera pas à sa place : "
            "valider ou annuler avant la lecture."
        )


def _cli_actor() -> str:
    try:
        return f"cli:{getpass.getuser()}"[:100]
    except Exception:  # noqa: BLE001 - no login name available (container, service)
        return "cli:inconnu"


def journaliser_lecture(
    kind: SensitiveReadKind | Callable[[], SensitiveReadKind],
    *,
    ecole_id: Callable[[tuple, dict, object], int] | None = None,
    resource: Callable[[tuple, dict], str] | None = None,
):
    """Decorator: record a SensitiveReadLog each time the decorated function
    returns sensitive data successfully.

    `kind` may be a callable, evaluated at call time (e.g. a bulletin read
    as a PDF download is an export). `ecole_id` defaults to the request's
    resolved tenant; outside a request it must be supplied (CLI export).
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            tenant_id = ecole_id(args, kwargs, result) if ecole_id else current_ecole_id()
            if tenant_id is None:
                raise JournalisationError(
                    f"Lecture sensible via {func.__qualname__} sans tenant identifiable : "
                    "impossible à journaliser, donc refusée."
                )
            _refuser_ecritures_en_attente(func.__qualname__)
            user_id = _authenticated_user_id()
            db.session.add(
                SensitiveReadLog(
                    ecole_id=tenant_id,
                    kind=SensitiveReadKind(kind() if callable(kind) else kind).value,
                    user_id=user_id,
                    actor_label=None if user_id else _cli_actor(),
                    resource=(resource(args, kwargs) if resource else _request_resource())[:300],
                    ip_address=_request_ip(),
                )
            )
            db.session.commit()
            return result

        return wrapper

    return decorator


def journaliser_acces_super_admin(func):
    """Decorator for every function through which a super-administrator
    reaches a tenant's data. The decorated function must be called with
    keyword arguments `super_admin`, `ecole_id` and `motif`; the access is
    journaled in that tenant's TenantAccessAuditLog BEFORE it happens, and
    refused if the motif is missing."""

    @functools.wraps(func)
    def wrapper(*args, super_admin, ecole_id: int, motif: str, **kwargs):
        if super_admin is None or not getattr(super_admin, "id", None):
            raise JournalisationError("Accès super-administrateur sans identité : refusé.")
        if not motif or len(motif.strip()) < 10:
            raise JournalisationError(
                "Accès super-administrateur à un tenant : motif d'au moins 10 caractères requis."
            )
        _refuser_ecritures_en_attente(func.__qualname__)
        db.session.add(
            TenantAccessAuditLog(
                ecole_id=ecole_id,
                event_type=TenantAccessEventType.SUPER_ADMIN_ACCESS,
                actor_super_admin_id=super_admin.id,
                reason=motif.strip()[:500],
                resource=f"{func.__module__}.{func.__qualname__}"[:200],
            )
        )
        db.session.commit()
        return func(*args, super_admin=super_admin, ecole_id=ecole_id, motif=motif, **kwargs)

    return wrapper
