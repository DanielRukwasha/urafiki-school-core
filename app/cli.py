"""`flask tenant ...` commands — onboarding a school must never require a
developer to touch the database by hand.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import click
from flask import Flask

from app.services.tenant_provisioning import (
    TenantProvisioningError,
    export_tenant,
    provision_tenant,
)


def register_cli(app: Flask) -> None:
    @app.cli.group("tenant")
    def tenant_group() -> None:
        """Manage école tenants."""

    @tenant_group.command("create")
    @click.option("--name", required=True, help="Nom complet de l'école.")
    @click.option("--short-code", required=True, help="Code court unique (ex: IMC).")
    @click.option("--domain", required=True, help="Domaine de résolution (ex: montcarmel.urafiki.org).")
    @click.option("--direction-email", required=True)
    @click.option("--direction-first-name", required=True)
    @click.option("--direction-last-name", required=True)
    @click.option("--academic-year-label", required=True, help='Ex: "2026-2027".')
    @click.option("--academic-year-start", required=True, type=click.DateTime(formats=["%Y-%m-%d"]))
    @click.option("--academic-year-end", required=True, type=click.DateTime(formats=["%Y-%m-%d"]))
    @click.option("--timezone", default="UTC")
    @click.option("--locale", default="fr")
    @click.option("--contact-email", default=None)
    def tenant_create(
        name: str,
        short_code: str,
        domain: str,
        direction_email: str,
        direction_first_name: str,
        direction_last_name: str,
        academic_year_label: str,
        academic_year_start,
        academic_year_end,
        timezone: str,
        locale: str,
        contact_email: str | None,
    ) -> None:
        try:
            result = provision_tenant(
                name=name,
                short_code=short_code,
                domain=domain,
                direction_email=direction_email,
                direction_first_name=direction_first_name,
                direction_last_name=direction_last_name,
                academic_year_label=academic_year_label,
                academic_year_start=date(
                    academic_year_start.year,
                    academic_year_start.month,
                    academic_year_start.day,
                ),
                academic_year_end=date(
                    academic_year_end.year, academic_year_end.month, academic_year_end.day
                ),
                timezone=timezone,
                locale=locale,
                contact_email=contact_email,
            )
        except TenantProvisioningError as exc:
            raise click.ClickException(str(exc)) from exc

        click.echo(f"École créée : {result.institution.name} (ecole_id={result.institution.id})")
        click.echo(f"Domaine : {result.institution.domain}")
        click.echo(f"Compte DIRECTION : {result.direction_user.email}")
        click.echo(f"Mot de passe à usage unique : {result.one_time_password}")
        click.echo("(à transmettre à l'école par un canal sécurisé, jamais par ce log)")

    @tenant_group.command("export")
    @click.option("--domain", required=True)
    @click.option("--output-dir", required=True, type=click.Path(file_okay=False))
    def tenant_export(domain: str, output_dir: str) -> None:
        try:
            data = export_tenant(domain=domain)
        except TenantProvisioningError as exc:
            raise click.ClickException(str(exc)) from exc

        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        for table_name, rows in data.items():
            with open(out_path / f"{table_name}.json", "w", encoding="utf-8") as fh:
                json.dump(rows, fh, ensure_ascii=False, indent=2, default=str)

        click.echo(f"Export écrit dans {out_path} ({len(data)} tables).")
