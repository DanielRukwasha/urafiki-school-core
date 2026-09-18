"""titulaire scope and submitted state

Business amendment: class titulariat is a per-class scope
(SchoolClass.titulaire_id), never a global role, and the publication
state machine was missing a state — the titulaire's own "submitted"
step between encoding and DIRECTION's "consolidated" — that the app
had skipped straight past. Adds:

- school_classes.titulaire_id
- PublicationStatus.SUBMITTED (between DRAFT and CONSOLIDATED) and
  period_publications.submitted_at
- DeliberationAction.SUBMIT

No existing rows can violate either enum widening (a widen only adds
allowed values, never removes one), so there is nothing to backfill.

Revision ID: aa2202d3e6d9
Revises: bbcaf2ca88d3
Create Date: 2026-09-18 09:17:45.829693

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'aa2202d3e6d9'
down_revision = 'bbcaf2ca88d3'
branch_labels = None
depends_on = None

OLD_PUBLICATION_STATUSES = ("DRAFT", "CONSOLIDATED", "VALIDATED", "PUBLISHED")
NEW_PUBLICATION_STATUSES = ("DRAFT", "SUBMITTED", "CONSOLIDATED", "VALIDATED", "PUBLISHED")
OLD_DELIBERATION_ACTIONS = ("MANUAL_OVERRIDE", "CONSOLIDATE", "VALIDATE", "PUBLISH")
NEW_DELIBERATION_ACTIONS = ("MANUAL_OVERRIDE", "SUBMIT", "CONSOLIDATE", "VALIDATE", "PUBLISH")


def upgrade():
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    with op.batch_alter_table('period_publications', schema=None) as batch_op:
        batch_op.add_column(sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True))

    with op.batch_alter_table('school_classes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('titulaire_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_school_classes_titulaire_id'), ['titulaire_id'], unique=False)
        batch_op.create_foreign_key(
            'fk_school_classes_titulaire_id_users', 'users', ['titulaire_id'], ['id']
        )

    if is_postgres:
        # PostgreSQL 12+ allows ADD VALUE inside a transaction as long as
        # the new value isn't used by a statement in that same
        # transaction — which this migration never does, so no special
        # non-transactional handling is needed here.
        op.execute("ALTER TYPE publicationstatus ADD VALUE 'SUBMITTED' BEFORE 'CONSOLIDATED'")
        op.execute("ALTER TYPE deliberationaction ADD VALUE 'SUBMIT'")
    else:
        # SQLite has no native enum type — sa.Enum compiles to a
        # VARCHAR + CHECK(value IN (...)) constraint, so the old,
        # narrower list is still enforced until the table is rebuilt
        # against the new Enum definition.
        with op.batch_alter_table('period_publications', schema=None) as batch_op:
            batch_op.alter_column(
                'status',
                existing_type=sa.Enum(*OLD_PUBLICATION_STATUSES, name='publicationstatus'),
                type_=sa.Enum(*NEW_PUBLICATION_STATUSES, name='publicationstatus'),
                existing_nullable=False,
            )
        with op.batch_alter_table('deliberation_audit_logs', schema=None) as batch_op:
            batch_op.alter_column(
                'action',
                existing_type=sa.Enum(*OLD_DELIBERATION_ACTIONS, name='deliberationaction'),
                type_=sa.Enum(*NEW_DELIBERATION_ACTIONS, name='deliberationaction'),
                existing_nullable=False,
            )


def downgrade():
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # PostgreSQL cannot remove an enum value at all (ALTER TYPE ... DROP
    # VALUE does not exist); downgrading past this migration on Postgres
    # requires recreating the type from a pre-migration backup, which is
    # out of scope for a schema-only downgrade. Since nothing before this
    # migration ever wrote 'SUBMITTED'/'SUBMIT', simply leaving the wider
    # enum in place on downgrade cannot corrupt older code's behavior —
    # older code just never produces those values.
    if not is_postgres:
        with op.batch_alter_table('deliberation_audit_logs', schema=None) as batch_op:
            batch_op.alter_column(
                'action',
                existing_type=sa.Enum(*NEW_DELIBERATION_ACTIONS, name='deliberationaction'),
                type_=sa.Enum(*OLD_DELIBERATION_ACTIONS, name='deliberationaction'),
                existing_nullable=False,
            )
        with op.batch_alter_table('period_publications', schema=None) as batch_op:
            batch_op.alter_column(
                'status',
                existing_type=sa.Enum(*NEW_PUBLICATION_STATUSES, name='publicationstatus'),
                type_=sa.Enum(*OLD_PUBLICATION_STATUSES, name='publicationstatus'),
                existing_nullable=False,
            )

    with op.batch_alter_table('school_classes', schema=None) as batch_op:
        batch_op.drop_constraint('fk_school_classes_titulaire_id_users', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_school_classes_titulaire_id'))
        batch_op.drop_column('titulaire_id')

    with op.batch_alter_table('period_publications', schema=None) as batch_op:
        batch_op.drop_column('submitted_at')
