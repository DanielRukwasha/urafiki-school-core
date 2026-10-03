"""versions de bulletin justifiées et journal des lectures sensibles

Sprint de mise en conformité du socle (invariants 9 et 10). Adds:

- bulletin_versions: one immutable row per published version of a
  class/period's bulletins. Version 1 = first publication; every later
  version is a correction and MUST carry a motif (>= 10 characters), its
  author, its UTC timestamp and the version it corrects — enforced by a
  CHECK constraint. On PostgreSQL a trigger also rejects any UPDATE or
  DELETE, so immutability holds even outside the ORM.
- sensitive_read_logs: journal of sensitive reads (bulletin consultation,
  data export), written by app/services/journal_lectures.py.

Both tables are tenant-scoped and get the same Row Level Security policy
as every other tenant table (see 9d31d5bff2f2).

Backfill: each existing PUBLISH entry of deliberation_audit_logs becomes a
version, in chronological order per (class, period), with its real author
and timestamp. A version > 1 found this way predates motif tracking: its
motif says so explicitly rather than inventing one.

Fully reversible: downgrade drops the trigger, policies and both tables;
no pre-existing table is modified.

Revision ID: c3f1a9d27b40
Revises: 14efd3eb110e
Create Date: 2026-10-03 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c3f1a9d27b40'
down_revision = '14efd3eb110e'
branch_labels = None
depends_on = None

NEW_TENANT_TABLES = ("bulletin_versions", "sensitive_read_logs")
MOTIF_REPRISE = (
    "Correction publiée avant la traçabilité des motifs "
    "(reprise de données, migration c3f1a9d27b40)."
)


def upgrade():
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    op.create_table(
        'bulletin_versions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('publication_id', sa.Integer(), nullable=False),
        sa.Column('numero', sa.Integer(), nullable=False),
        sa.Column('motif', sa.Text(), nullable=True),
        sa.Column('auteur_id', sa.Integer(), nullable=False),
        sa.Column('publie_le', sa.DateTime(timezone=True), nullable=False),
        sa.Column('corrige_version_id', sa.Integer(), nullable=True),
        sa.Column('ecole_id', sa.Integer(), nullable=False),
        sa.CheckConstraint('numero >= 1', name='ck_bulletin_version_numero_positive'),
        sa.CheckConstraint(
            "(numero = 1 AND motif IS NULL AND corrige_version_id IS NULL)"
            " OR (numero > 1 AND motif IS NOT NULL AND length(trim(motif)) >= 10"
            " AND corrige_version_id IS NOT NULL)",
            name='ck_bulletin_version_correction_justifiee',
        ),
        sa.ForeignKeyConstraint(['auteur_id'], ['users.id']),
        sa.ForeignKeyConstraint(['corrige_version_id'], ['bulletin_versions.id']),
        sa.ForeignKeyConstraint(['ecole_id'], ['institutions.id']),
        sa.ForeignKeyConstraint(['publication_id'], ['period_publications.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'ecole_id', 'publication_id', 'numero', name='uq_bulletin_version_numero'
        ),
    )
    with op.batch_alter_table('bulletin_versions', schema=None) as batch_op:
        batch_op.create_index('ix_bulletin_versions_auteur_id', ['auteur_id'], unique=False)
        batch_op.create_index(
            'ix_bulletin_versions_corrige_version_id', ['corrige_version_id'], unique=False
        )
        batch_op.create_index('ix_bulletin_versions_ecole_id', ['ecole_id'], unique=False)
        batch_op.create_index(
            'ix_bulletin_versions_publication_id', ['publication_id'], unique=False
        )

    op.create_table(
        'sensitive_read_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=40), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('actor_label', sa.String(length=100), nullable=True),
        sa.Column('resource', sa.String(length=300), nullable=False),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ecole_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['ecole_id'], ['institutions.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('sensitive_read_logs', schema=None) as batch_op:
        batch_op.create_index('ix_sensitive_read_logs_ecole_id', ['ecole_id'], unique=False)
        batch_op.create_index('ix_sensitive_read_logs_kind', ['kind'], unique=False)
        batch_op.create_index('ix_sensitive_read_logs_user_id', ['user_id'], unique=False)

    _backfill_versions(bind)

    if is_postgres:
        op.execute(
            """
            CREATE FUNCTION bulletin_versions_immuables() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'bulletin_versions : une version publiée est immuable (%)', TG_OP;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER bulletin_versions_immuables
            BEFORE UPDATE OR DELETE ON bulletin_versions
            FOR EACH ROW EXECUTE FUNCTION bulletin_versions_immuables()
            """
        )
        for table_name in NEW_TENANT_TABLES:
            op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
            op.execute(
                f"""
                CREATE POLICY tenant_isolation ON {table_name}
                USING (
                    current_setting('app.current_ecole_id', true) IS NOT NULL
                    AND current_setting('app.current_ecole_id', true) <> ''
                    AND ecole_id = current_setting('app.current_ecole_id', true)::integer
                )
                """
            )


def _backfill_versions(bind):
    publications = sa.table(
        'period_publications',
        sa.column('id', sa.Integer),
        sa.column('ecole_id', sa.Integer),
        sa.column('school_class_id', sa.Integer),
        sa.column('period_id', sa.Integer),
    )
    audit = sa.table(
        'deliberation_audit_logs',
        sa.column('id', sa.Integer),
        sa.column('ecole_id', sa.Integer),
        sa.column('action', sa.String),
        sa.column('school_class_id', sa.Integer),
        sa.column('period_id', sa.Integer),
        sa.column('user_id', sa.Integer),
        sa.column('created_at', sa.DateTime(timezone=True)),
    )
    versions = sa.Table(
        'bulletin_versions',
        sa.MetaData(),
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('ecole_id', sa.Integer),
        sa.Column('publication_id', sa.Integer),
        sa.Column('numero', sa.Integer),
        sa.Column('motif', sa.Text),
        sa.Column('auteur_id', sa.Integer),
        sa.Column('publie_le', sa.DateTime(timezone=True)),
        sa.Column('corrige_version_id', sa.Integer),
    )
    publication_ids = {
        (row.ecole_id, row.school_class_id, row.period_id): row.id
        for row in bind.execute(sa.select(publications))
    }
    published = bind.execute(
        sa.select(audit)
        .where(sa.cast(audit.c.action, sa.String) == 'PUBLISH')
        .order_by(audit.c.created_at, audit.c.id)
    )
    last_version = {}
    for row in published:
        key = (row.ecole_id, row.school_class_id, row.period_id)
        publication_id = publication_ids.get(key)
        if publication_id is None:
            continue
        numero, previous_id = last_version.get(publication_id, (0, None))
        numero += 1
        result = bind.execute(
            versions.insert().values(
                ecole_id=row.ecole_id,
                publication_id=publication_id,
                numero=numero,
                motif=None if numero == 1 else MOTIF_REPRISE,
                auteur_id=row.user_id,
                publie_le=row.created_at,
                corrige_version_id=previous_id,
            )
        )
        last_version[publication_id] = (numero, result.inserted_primary_key[0])


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table_name in NEW_TENANT_TABLES:
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table_name}")
            op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")
        op.execute("DROP TRIGGER IF EXISTS bulletin_versions_immuables ON bulletin_versions")
        op.execute("DROP FUNCTION IF EXISTS bulletin_versions_immuables()")

    with op.batch_alter_table('sensitive_read_logs', schema=None) as batch_op:
        batch_op.drop_index('ix_sensitive_read_logs_user_id')
        batch_op.drop_index('ix_sensitive_read_logs_kind')
        batch_op.drop_index('ix_sensitive_read_logs_ecole_id')
    op.drop_table('sensitive_read_logs')

    with op.batch_alter_table('bulletin_versions', schema=None) as batch_op:
        batch_op.drop_index('ix_bulletin_versions_publication_id')
        batch_op.drop_index('ix_bulletin_versions_ecole_id')
        batch_op.drop_index('ix_bulletin_versions_corrige_version_id')
        batch_op.drop_index('ix_bulletin_versions_auteur_id')
    op.drop_table('bulletin_versions')
