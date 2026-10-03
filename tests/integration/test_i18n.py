"""Invariant 11 : architecture i18n côté serveur. Le français est la langue
de référence ; l'ajout du swahili ne demande qu'un catalogue, aucune
réécriture de code."""

import io
import shutil
from pathlib import Path

import pytest
from babel.messages.extract import extract_from_dir
from babel.messages.mofile import write_mo
from babel.messages.pofile import read_po
from flask import render_template_string

from app.i18n import LangueNonDisponibleError, select_locale
from app.security.tenant import resolve_tenant

ROOT = Path(__file__).resolve().parents[2]
TRANSLATIONS = ROOT / "app" / "translations"
MSGID = "Veuillez vous connecter pour accéder à cette page."


def _render_in_tenant(app, tenant, template):
    with app.test_request_context("/", base_url=f"http://{tenant.domain}"):
        resolve_tenant()
        return render_template_string(template)


def test_translation_function_is_exposed_to_templates(app, tenant_a):
    assert _render_in_tenant(app, tenant_a, "{{ _('" + MSGID + "') }}") == MSGID
    assert _render_in_tenant(app, tenant_a, "{{ gettext('" + MSGID + "') }}") == MSGID


def test_language_comes_from_tenant_configuration(app, db, tenant_a):
    with app.test_request_context("/", base_url=f"http://{tenant_a.domain}"):
        resolve_tenant()
        assert select_locale() == "fr"


def test_unavailable_tenant_language_raises_explicitly(app, db, tenant_a):
    tenant_a.locale = "xx"
    db.session.commit()
    with app.test_request_context("/", base_url=f"http://{tenant_a.domain}"):
        resolve_tenant()
        with pytest.raises(LangueNonDisponibleError, match="xx"):
            select_locale()


def test_outside_a_tenant_the_default_language_applies(app):
    with app.test_request_context("/"):
        assert select_locale() == "fr"


def test_adding_swahili_needs_only_a_catalog(app, db, tenant_a, tmp_path):
    """Preuve de l'architecture : un catalogue sw, et le tenant passe en
    swahili sans aucune modification de code."""
    directory = tmp_path / "translations"
    shutil.copytree(TRANSLATIONS, directory)
    with open(TRANSLATIONS / "messages.pot", "rb") as handle:
        catalog = read_po(handle, locale="sw")
    catalog[MSGID].string = "Tafadhali ingia ili kufikia ukurasa huu."
    target = directory / "sw" / "LC_MESSAGES"
    target.mkdir(parents=True)
    with open(target / "messages.mo", "wb") as handle:
        write_mo(handle, catalog)

    app.config["BABEL_TRANSLATION_DIRECTORIES"] = str(directory)
    app.extensions["babel"].translation_directories = [str(directory)]
    tenant_a.locale = "sw"
    db.session.commit()

    rendered = _render_in_tenant(app, tenant_a, "{{ _('" + MSGID + "') }}")
    assert rendered == "Tafadhali ingia ili kufikia ukurasa huu."


def test_french_catalog_covers_every_marked_string():
    """Le catalogue de référence est à jour : toute chaîne marquée dans le
    code ou les gabarits figure dans messages.pot et dans le catalogue fr.
    En cas d'échec : voir docs/i18n.md, « Mettre à jour les catalogues »."""
    method_map = [("app/**.py", "python"), ("app/templates/**.html", "jinja2")]
    marked = {
        message
        for _file, _line, message, _comments, _context in extract_from_dir(
            str(ROOT),
            method_map=method_map,
            keywords={"_": None, "gettext": None, "_l": None, "lazy_gettext": None,
                      "ngettext": (1, 2)},
        )
    }
    marked = {m if isinstance(m, str) else m[0] for m in marked}
    with open(TRANSLATIONS / "messages.pot", "rb") as handle:
        template_ids = {m.id if isinstance(m.id, str) else m.id[0] for m in read_po(handle) if m.id}
    with open(TRANSLATIONS / "fr" / "LC_MESSAGES" / "messages.po", "rb") as handle:
        french_ids = {m.id if isinstance(m.id, str) else m.id[0] for m in read_po(handle) if m.id}
    assert marked, "aucune chaîne marquée : l'extraction ne fonctionne pas"
    assert marked <= template_ids, f"messages.pot à régénérer : {sorted(marked - template_ids)}"
    assert template_ids <= french_ids, f"catalogue fr à mettre à jour : {sorted(template_ids - french_ids)}"


def test_catalogs_compile(tmp_path):
    for po in TRANSLATIONS.glob("*/LC_MESSAGES/messages.po"):
        with open(po, "rb") as handle:
            catalog = read_po(handle)
        write_mo(io.BytesIO(), catalog)
