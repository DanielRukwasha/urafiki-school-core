"""contenu figé des versions de bulletin

Invariant 9, revue de #55 (bloquant 1) : une version ne conservait que ses
métadonnées (numéro, motif, auteur, date, version corrigée) ; les
impressions recalculaient depuis les tables vivantes, si bien qu'un
changement de maximum, de libellé ou de cote après publication modifiait
la version 1. Adds to bulletin_versions:

- contenu: the bulletin's full computed content, canonical JSON
  (app/services/contenu_bulletin.py);
- empreinte: SHA-256 of exactly those bytes;
- ck_bulletin_version_contenu_empreinte (PostgreSQL): both present or both
  absent, fingerprint 64 characters;
- PostgreSQL only, ck_bulletin_version_contenu_fige (NOT VALID): every new
  row carries content. NOT VALID because rows backfilled by c3f1a9d27b40
  predate freezing and cannot be filled faithfully afterwards — the live
  tables may have changed since. Reading such a version raises an explicit
  error instead of recalculating (contenu_de_version).

The existing immutability trigger covers the new columns: no UPDATE, ever.

Downgrade refuses to run while frozen content exists — dropping it would
destroy published documents. On an empty or pre-freeze table it is fully
reversible.

Revision ID: d7e2b4c1a9f3
Revises: c3f1a9d27b40
Create Date: 2026-10-16 22:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd7e2b4c1a9f3'
down_revision = 'c3f1a9d27b40'
branch_labels = None
depends_on = None


CHECK_CONTENU_EMPREINTE = (
    "(contenu IS NULL) = (empreinte IS NULL)"
    " AND (empreinte IS NULL OR length(empreinte) = 64)"
)


def upgrade():
    # Plain ADD COLUMN rather than batch mode: on SQLite a batch rebuild
    # copies the rows and drops the table, which the self-referencing
    # corrige_version_id foreign key rejects once versions exist. SQLite is
    # only the local smoke target, so the CHECK constraints are PostgreSQL's.
    op.add_column('bulletin_versions', sa.Column('contenu', sa.Text(), nullable=True))
    op.add_column('bulletin_versions', sa.Column('empreinte', sa.String(length=64), nullable=True))
    if op.get_bind().dialect.name == "postgresql":
        op.create_check_constraint(
            'ck_bulletin_version_contenu_empreinte', 'bulletin_versions', CHECK_CONTENU_EMPREINTE
        )
        op.execute(
            "ALTER TABLE bulletin_versions ADD CONSTRAINT ck_bulletin_version_contenu_fige"
            " CHECK (contenu IS NOT NULL) NOT VALID"
        )


def downgrade():
    bind = op.get_bind()
    frozen = bind.execute(
        sa.text("SELECT count(*) FROM bulletin_versions WHERE contenu IS NOT NULL")
    ).scalar()
    if frozen:
        raise RuntimeError(
            f"{frozen} version(s) de bulletin ont un contenu figé : la descente le "
            "détruirait. Restaurer une sauvegarde plutôt que descendre cette migration."
        )
    if bind.dialect.name == "postgresql":
        op.drop_constraint('ck_bulletin_version_contenu_fige', 'bulletin_versions', type_='check')
        op.drop_constraint(
            'ck_bulletin_version_contenu_empreinte', 'bulletin_versions', type_='check'
        )
    op.execute("ALTER TABLE bulletin_versions DROP COLUMN empreinte")
    op.execute("ALTER TABLE bulletin_versions DROP COLUMN contenu")
