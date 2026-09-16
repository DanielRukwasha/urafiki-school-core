"""Presentation helpers, independent of tenant persistence and resolution."""

from app.ui.reports import build_report_layout
from app.ui.theming import build_theme


def install_presentation(app):
    @app.context_processor
    def neutral_presentation():
        # Runtime tenant binding is deliberately deferred until the backend contract lands.
        # Explicit view context or a later context processor can supply these values.
        return {
            "ui_theme": build_theme(),
            "report_layout": build_report_layout(),
            "access_notice": None,
        }
