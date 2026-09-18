"""Resolves the current request's real tenant into app/ui/'s presentation
contracts (`ui_theme`, `report_layout`) — the adapter app/ui/'s own module
docstrings describe as pending until the multi-tenant backend merges.

Kept out of app/ui/ on purpose: that package is explicitly persistence- and
resolution-free (see its docstrings and THEMING.md), so this is the one
place allowed to import both the tenant models and the presentation
builders, translating `TenantConfig` into the plain dicts `build_theme()`
and `build_report_layout()` expect.

Fields `TenantConfig` doesn't store yet (accent/neutral colors, favicon,
report columns/orientation/font size) are simply omitted here rather than
invented — the builders already have validated, accessible defaults for
anything omitted, and a school without real values for a field falls back
to that shared default, never to another school's value.
"""

from flask import g

from app.extensions import db
from app.models.institution import Institution
from app.models.tenant_config import TenantConfig
from app.ui.reports import build_report_layout
from app.ui.theming import build_theme


def _resolved_tenant() -> tuple[Institution | None, TenantConfig | None]:
    ecole_id = getattr(g, "current_ecole_id", None)
    if ecole_id is None:
        return None, None
    institution = db.session.get(Institution, ecole_id)
    if institution is None:
        return None, None
    config = TenantConfig.query.filter_by(ecole_id=ecole_id).first()
    return institution, config


def resolve_presentation():
    """The current request's (theme, report_layout) pair, resolved once.

    Public on purpose: a view that needs these values ahead of rendering
    (portal report routes build a PDF from rendered HTML, so they need the
    theme before calling render_template) should call this directly rather
    than trigger it indirectly through `current_app.update_template_context`
    — that runs *every* registered context processor including this one,
    and render_template() will already invoke it again on its own, so
    routes doing both were resolving the tenant's Institution/TenantConfig
    twice per request for no benefit (their own explicit ui_theme=/
    report_layout= kwargs to render_template always win anyway).
    """
    institution, config = _resolved_tenant()
    if institution is None:
        # No tenant resolved for this request (e.g. the platform-admin
        # host, or a request outside the normal tenant-resolution flow) —
        # the same neutral, DB-free defaults app/ui/ used before this
        # adapter existed.
        return build_theme(), build_report_layout()

    branding = {"display_name": institution.name, "locale": institution.locale}
    report = {"locale": institution.locale}
    # header_lines carries whatever short descriptive text sits under the
    # report title — the pre-theming print template used to show the
    # school's address there directly; folding it back in here keeps that
    # on the printed bulletin instead of silently dropping it.
    header_lines = [line for line in (config.report_header if config else None, institution.address) if line]
    if header_lines:
        report["header_lines"] = header_lines
    if config is not None:
        if config.primary_color:
            branding["primary_color"] = config.primary_color
        if config.logo_url:
            branding["logo_url"] = config.logo_url
        if config.report_legal_mentions:
            report["legal_text"] = config.report_legal_mentions
        if config.report_signatures:
            report["signatures"] = config.report_signatures

    return build_theme(branding), build_report_layout(report)


def install_tenant_presentation(app):
    @app.context_processor
    def tenant_presentation():
        theme, layout = resolve_presentation()
        return {"ui_theme": theme, "report_layout": layout, "access_notice": None}
