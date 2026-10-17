"""Server-side internationalization (invariant 11).

French is the reference language: every message identifier (msgid) is the
French text, so an untranslated string still displays correctly in French.
Adding Swahili requires no code change — only a catalog:

    pybabel init -i app/translations/messages.pot -d app/translations -l sw
    (translate app/translations/sw/LC_MESSAGES/messages.po)
    pybabel compile -d app/translations

then set the tenant's `Institution.locale` to "sw". See docs/i18n.md.

The language of a request is the tenant's configured language
(`Institution.locale`, configuration in the database, invariant 2). A
tenant configured with a language the platform does not offer is a
configuration error, raised explicitly — never silently shown in French.
"Offered" means declared in `LANGUES_DISPONIBLES` *and* provisioned: a
compiled catalog (`<lang>/LC_MESSAGES/messages.mo`) exists in one of the
translation directories. A declared language whose catalog was never
compiled would otherwise display every msgid — French — without any error.
Only the reference language needs no catalog, its msgids being its text.
Outside any tenant (platform console, CLI), the default language applies.
"""

from __future__ import annotations

from pathlib import Path

from flask import Flask, current_app, g, has_request_context
from flask_babel import Babel, get_babel

babel = Babel()


class LangueNonDisponibleError(RuntimeError):
    """Raised when a tenant is configured with a language the platform does
    not declare, or declares without a compiled catalog."""


def langues_declarees() -> tuple[str, ...]:
    return tuple(current_app.config["LANGUES_DISPONIBLES"])


def catalogue_compile(locale: str) -> bool:
    return any(
        (Path(directory) / locale / "LC_MESSAGES" / "messages.mo").is_file()
        for directory in get_babel(current_app).translation_directories
    )


def langues_disponibles() -> tuple[str, ...]:
    """Declared languages that can actually be displayed: the reference
    language, plus every other declared language with a compiled catalog."""
    reference = current_app.config["BABEL_DEFAULT_LOCALE"]
    return tuple(
        locale for locale in langues_declarees()
        if locale == reference or catalogue_compile(locale)
    )


def select_locale() -> str:
    default = current_app.config["BABEL_DEFAULT_LOCALE"]
    if not has_request_context():
        return default
    ecole_id = getattr(g, "current_ecole_id", None)
    if ecole_id is None:
        return default

    from app.extensions import db
    from app.models.institution import Institution

    institution = db.session.get(Institution, ecole_id)
    locale = institution.locale if institution is not None else None
    if not locale:
        raise LangueNonDisponibleError(
            f"Tenant ecole_id={ecole_id} sans langue configurée (Institution.locale)."
        )
    if locale in langues_declarees() and locale not in langues_disponibles():
        raise LangueNonDisponibleError(
            f"Tenant ecole_id={ecole_id} configuré en « {locale} » : langue déclarée mais "
            f"sans catalogue compilé ({locale}/LC_MESSAGES/messages.mo). Provisionner le "
            "catalogue (docs/i18n.md) avant d'activer cette langue."
        )
    if locale not in langues_disponibles():
        raise LangueNonDisponibleError(
            f"Tenant ecole_id={ecole_id} configuré en « {locale} », langue non disponible "
            f"(disponibles : {', '.join(langues_disponibles())})."
        )
    return locale


def init_i18n(app: Flask) -> None:
    babel.init_app(app, locale_selector=select_locale)
