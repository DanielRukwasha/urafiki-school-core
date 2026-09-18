"""Presentation helpers (`build_theme`, `build_report_layout`, ...):
independent of tenant persistence and resolution by design — see
app/tenant_presentation.py for the adapter that resolves the current
request's real tenant into these builders' plain-dict configuration."""
