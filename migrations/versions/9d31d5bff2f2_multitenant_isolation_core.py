"""multitenant isolation core

Adds ecole_id to every business table, recomposes unique constraints with
ecole_id leading, introduces the tenant/platform tables (tenant_configs,
calculation_strategies, super_admins, tenant_access_audit_logs), adds
students.global_student_uid, and enables PostgreSQL Row Level Security on
every tenant-scoped table as a second, independent isolation layer.

Existing rows (Institut Mont Carmel, if present) are backfilled to the
single pre-existing institution. Reversible: downgrade() restores the
pre-multitenant schema exactly.

RLS note: PostgreSQL never applies row security to a table's owning role.
The policies created here only take effect once the running web process
connects as a non-owning role — see ARCHITECTURE_MULTITENANT.md. Skipped
entirely on SQLite (dev/test convenience only, not a deployment target).

Revision ID: 9d31d5bff2f2
Revises: 08f82b57aeca
Create Date: 2026-09-16 12:00:00.000000

"""
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = '9d31d5bff2f2'
down_revision = '08f82b57aeca'
branch_labels = None
depends_on = None

# Tables getting a backfilled, NOT NULL ecole_id in this migration (existing
# tables only — tenant_configs/tenant_access_audit_logs are created fresh
# below with ecole_id NOT NULL from birth).
TENANT_TABLES = [
    "academic_years",
    "sections",
    "school_classes",
    "evaluation_periods",
    "courses",
    "students",
    "enrollments",
    "teacher_assignments",
    "users",
    "grades",
    "grade_audit_logs",
]

# All tables carrying ecole_id once this migration completes — the set RLS
# is enabled on.
RLS_TABLES = TENANT_TABLES + ["tenant_configs", "tenant_access_audit_logs"]

STANDARD_STRATEGY_DESCRIPTION = (
    "Moyenne pondérée par coefficient et par période, seuil de passage "
    "unique — comportement du moteur de calcul tel que livré en P2."
)


def _utcnow():
    return datetime.now(timezone.utc)


def upgrade():
    conn = op.get_bind()
    is_postgres = conn.dialect.name == "postgresql"
    now = _utcnow()

    # ------------------------------------------------------------------
    # 1. Shared platform catalog + super-admin table (no tenant data).
    # ------------------------------------------------------------------
    op.create_table(
        "calculation_strategies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=50), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_table(
        "super_admins",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=200), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("is_active_account", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("super_admins", schema=None) as batch_op:
        batch_op.create_index("ix_super_admins_email", ["email"], unique=True)

    calculation_strategies_t = sa.table(
        "calculation_strategies",
        sa.column("key", sa.String),
        sa.column("description", sa.String),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    op.bulk_insert(
        calculation_strategies_t,
        [
            {
                "key": "STANDARD",
                "description": STANDARD_STRATEGY_DESCRIPTION,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )

    # ------------------------------------------------------------------
    # 2. institutions becomes the tenant registry: domain resolution +
    #    lifecycle columns.
    # ------------------------------------------------------------------
    with op.batch_alter_table("institutions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("domain", sa.String(length=255), nullable=True))
        batch_op.add_column(
            sa.Column("custom_domain", sa.String(length=255), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "locale", sa.String(length=10), nullable=False, server_default="fr"
            )
        )
        batch_op.add_column(
            sa.Column(
                "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
            )
        )

    institutions_t = sa.table(
        "institutions",
        sa.column("id", sa.Integer),
        sa.column("short_code", sa.String),
        sa.column("domain", sa.String),
    )
    default_institution_id = conn.execute(
        sa.text("SELECT id FROM institutions ORDER BY id LIMIT 1")
    ).scalar()

    if default_institution_id is not None:
        for row in conn.execute(
            sa.select(institutions_t.c.id, institutions_t.c.short_code)
        ):
            conn.execute(
                institutions_t.update()
                .where(institutions_t.c.id == row.id)
                .values(domain=f"{row.short_code.lower()}.urafiki.org")
            )

    with op.batch_alter_table("institutions", schema=None) as batch_op:
        batch_op.alter_column("domain", nullable=False)
        batch_op.create_unique_constraint("uq_institution_domain", ["domain"])
        batch_op.create_unique_constraint(
            "uq_institution_custom_domain", ["custom_domain"]
        )

    # ------------------------------------------------------------------
    # 3. ecole_id on every business table, backfilled to the sole
    #    pre-existing institution (or left empty if this is a fresh DB).
    # ------------------------------------------------------------------
    for table_name in TENANT_TABLES:
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            batch_op.add_column(sa.Column("ecole_id", sa.Integer(), nullable=True))

        if default_institution_id is not None:
            conn.execute(
                sa.text(f"UPDATE {table_name} SET ecole_id = :eid"),
                {"eid": default_institution_id},
            )

        with op.batch_alter_table(table_name, schema=None) as batch_op:
            batch_op.alter_column("ecole_id", nullable=False)
            batch_op.create_foreign_key(
                f"fk_{table_name}_ecole_id_institutions",
                "institutions",
                ["ecole_id"],
                ["id"],
            )
            batch_op.create_index(f"ix_{table_name}_ecole_id", ["ecole_id"])

    # ------------------------------------------------------------------
    # 4. Recompose unique constraints with ecole_id leading.
    # ------------------------------------------------------------------
    if is_postgres:
        with op.batch_alter_table("academic_years", schema=None) as batch_op:
            batch_op.create_unique_constraint(
                "uq_academic_year_ecole_label", ["ecole_id", "label"]
            )
        op.execute("ALTER TABLE academic_years DROP CONSTRAINT academic_years_label_key")

        with op.batch_alter_table("sections", schema=None) as batch_op:
            batch_op.create_unique_constraint(
                "uq_section_ecole_code", ["ecole_id", "code"]
            )
        op.execute("ALTER TABLE sections DROP CONSTRAINT sections_code_key")
    else:
        # SQLite has no DROP CONSTRAINT, and the original migration declared
        # these two as unnamed table-level UNIQUE constraints — unlike every
        # other constraint in this migration, Alembic's batch mode cannot
        # target an unnamed constraint for removal on SQLite. Rebuild both
        # tables directly instead of leaving the old, now-incorrect
        # single-column UNIQUE in place (it would keep blocking two tenants
        # from sharing an academic year label / section code, defeating the
        # whole point of this migration for local SQLite dev/test runs).
        op.execute(
            """
            CREATE TABLE academic_years_new (
                id INTEGER NOT NULL PRIMARY KEY,
                label VARCHAR(20) NOT NULL,
                start_date DATE NOT NULL,
                end_date DATE NOT NULL,
                is_current BOOLEAN NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                archived_at DATETIME,
                ecole_id INTEGER NOT NULL,
                CONSTRAINT uq_academic_year_ecole_label UNIQUE (ecole_id, label),
                CONSTRAINT fk_academic_years_ecole_id_institutions
                    FOREIGN KEY (ecole_id) REFERENCES institutions (id)
            )
            """
        )
        op.execute(
            "INSERT INTO academic_years_new "
            "SELECT id, label, start_date, end_date, is_current, created_at, "
            "updated_at, archived_at, ecole_id FROM academic_years"
        )
        op.execute("DROP TABLE academic_years")
        op.execute("ALTER TABLE academic_years_new RENAME TO academic_years")
        op.execute(
            "CREATE INDEX ix_academic_years_ecole_id ON academic_years (ecole_id)"
        )

        op.execute(
            """
            CREATE TABLE sections_new (
                id INTEGER NOT NULL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                code VARCHAR(20) NOT NULL,
                description VARCHAR(300),
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                archived_at DATETIME,
                ecole_id INTEGER NOT NULL,
                CONSTRAINT uq_section_ecole_code UNIQUE (ecole_id, code),
                CONSTRAINT fk_sections_ecole_id_institutions
                    FOREIGN KEY (ecole_id) REFERENCES institutions (id)
            )
            """
        )
        op.execute(
            "INSERT INTO sections_new "
            "SELECT id, name, code, description, created_at, updated_at, "
            "archived_at, ecole_id FROM sections"
        )
        op.execute("DROP TABLE sections")
        op.execute("ALTER TABLE sections_new RENAME TO sections")
        op.execute("CREATE INDEX ix_sections_ecole_id ON sections (ecole_id)")

    with op.batch_alter_table("school_classes", schema=None) as batch_op:
        batch_op.drop_constraint("uq_class_year_name", type_="unique")
        batch_op.create_unique_constraint(
            "uq_class_ecole_year_name", ["ecole_id", "academic_year_id", "name"]
        )

    with op.batch_alter_table("evaluation_periods", schema=None) as batch_op:
        batch_op.drop_constraint("uq_period_year_sequence", type_="unique")
        batch_op.create_unique_constraint(
            "uq_period_ecole_year_sequence",
            ["ecole_id", "academic_year_id", "sequence_order"],
        )

    with op.batch_alter_table("courses", schema=None) as batch_op:
        batch_op.drop_constraint("uq_course_class_code", type_="unique")
        batch_op.create_unique_constraint(
            "uq_course_ecole_class_code", ["ecole_id", "school_class_id", "code"]
        )

    with op.batch_alter_table("enrollments", schema=None) as batch_op:
        batch_op.drop_constraint("uq_enrollment_student_year", type_="unique")
        batch_op.create_unique_constraint(
            "uq_enrollment_ecole_student_year",
            ["ecole_id", "student_id", "academic_year_id"],
        )

    with op.batch_alter_table("teacher_assignments", schema=None) as batch_op:
        batch_op.drop_constraint("uq_assignment_teacher_course", type_="unique")
        batch_op.create_unique_constraint(
            "uq_assignment_ecole_teacher_course",
            ["ecole_id", "teacher_id", "course_id"],
        )

    with op.batch_alter_table("grades", schema=None) as batch_op:
        batch_op.drop_constraint("uq_grade_enrollment_course_period", type_="unique")
        batch_op.create_unique_constraint(
            "uq_grade_ecole_enrollment_course_period",
            ["ecole_id", "enrollment_id", "course_id", "period_id"],
        )

    with op.batch_alter_table("students", schema=None) as batch_op:
        batch_op.drop_index("ix_students_matricule")
        batch_op.create_index("ix_students_matricule", ["matricule"], unique=False)
        batch_op.create_unique_constraint(
            "uq_student_ecole_matricule", ["ecole_id", "matricule"]
        )

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index("ix_users_email")
        batch_op.create_index("ix_users_email", ["email"], unique=False)
        batch_op.create_unique_constraint("uq_user_ecole_email", ["ecole_id", "email"])

    # ------------------------------------------------------------------
    # 5. global_student_uid — Phase 3 readiness, never used to resolve a
    #    tenant, unique across the whole platform.
    # ------------------------------------------------------------------
    with op.batch_alter_table("students", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("global_student_uid", sa.String(length=36), nullable=True)
        )

    students_t = sa.table(
        "students", sa.column("id", sa.Integer), sa.column("global_student_uid", sa.String)
    )
    for row in conn.execute(sa.select(students_t.c.id)):
        conn.execute(
            students_t.update()
            .where(students_t.c.id == row.id)
            .values(global_student_uid=str(uuid.uuid4()))
        )

    with op.batch_alter_table("students", schema=None) as batch_op:
        batch_op.alter_column("global_student_uid", nullable=False)
        batch_op.create_unique_constraint(
            "uq_student_global_uid", ["global_student_uid"]
        )

    # ------------------------------------------------------------------
    # 6. Tenant configuration + cross-tenant access audit trail.
    # ------------------------------------------------------------------
    op.create_table(
        "tenant_configs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ecole_id", sa.Integer(), nullable=False),
        sa.Column("calculation_strategy_key", sa.String(length=50), nullable=False),
        sa.Column("percentage_decimal_places", sa.Integer(), nullable=False),
        sa.Column("mentions", sa.JSON(), nullable=False),
        sa.Column("eliminatory_course_codes", sa.JSON(), nullable=False),
        sa.Column("max_allowed_failures", sa.Integer(), nullable=True),
        sa.Column("report_header", sa.String(length=300), nullable=True),
        sa.Column("report_legal_mentions", sa.Text(), nullable=True),
        sa.Column("report_signatures", sa.JSON(), nullable=False),
        sa.Column("logo_url", sa.String(length=500), nullable=True),
        sa.Column("primary_color", sa.String(length=7), nullable=True),
        sa.Column("feature_flags", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["calculation_strategy_key"], ["calculation_strategies.key"]
        ),
        sa.ForeignKeyConstraint(["ecole_id"], ["institutions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ecole_id", name="uq_tenant_config_ecole"),
    )
    with op.batch_alter_table("tenant_configs", schema=None) as batch_op:
        batch_op.create_index("ix_tenant_configs_ecole_id", ["ecole_id"])

    op.create_table(
        "tenant_access_audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ecole_id", sa.Integer(), nullable=False),
        sa.Column(
            "event_type",
            sa.Enum(
                "SUPER_ADMIN_ACCESS",
                "CROSS_TENANT_SESSION_REJECTED",
                name="tenantaccesseventtype",
            ),
            nullable=False,
        ),
        sa.Column("actor_super_admin_id", sa.Integer(), nullable=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("resource", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_super_admin_id"], ["super_admins.id"]),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["ecole_id"], ["institutions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("tenant_access_audit_logs", schema=None) as batch_op:
        batch_op.create_index(
            "ix_tenant_access_audit_logs_ecole_id", ["ecole_id"]
        )
        batch_op.create_index(
            "ix_tenant_access_audit_logs_actor_super_admin_id",
            ["actor_super_admin_id"],
        )
        batch_op.create_index(
            "ix_tenant_access_audit_logs_actor_user_id", ["actor_user_id"]
        )

    if default_institution_id is not None:
        tenant_configs_t = sa.table(
            "tenant_configs",
            sa.column("ecole_id", sa.Integer),
            sa.column("calculation_strategy_key", sa.String),
            sa.column("percentage_decimal_places", sa.Integer),
            sa.column("mentions", sa.JSON),
            sa.column("eliminatory_course_codes", sa.JSON),
            sa.column("report_signatures", sa.JSON),
            sa.column("feature_flags", sa.JSON),
            sa.column("created_at", sa.DateTime),
            sa.column("updated_at", sa.DateTime),
        )
        op.bulk_insert(
            tenant_configs_t,
            [
                {
                    "ecole_id": default_institution_id,
                    "calculation_strategy_key": "STANDARD",
                    "percentage_decimal_places": 2,
                    "mentions": [],
                    "eliminatory_course_codes": [],
                    "report_signatures": [],
                    "feature_flags": {},
                    "created_at": now,
                    "updated_at": now,
                }
            ],
        )

    # ------------------------------------------------------------------
    # 7. Row Level Security — second, independent isolation layer.
    #    PostgreSQL only; no-op on SQLite (dev/test convenience).
    # ------------------------------------------------------------------
    if is_postgres:
        for table_name in RLS_TABLES:
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


def downgrade():
    conn = op.get_bind()
    is_postgres = conn.dialect.name == "postgresql"

    if is_postgres:
        for table_name in RLS_TABLES:
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table_name}")
            op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")

    with op.batch_alter_table("tenant_access_audit_logs", schema=None) as batch_op:
        batch_op.drop_index("ix_tenant_access_audit_logs_actor_user_id")
        batch_op.drop_index("ix_tenant_access_audit_logs_actor_super_admin_id")
        batch_op.drop_index("ix_tenant_access_audit_logs_ecole_id")
    op.drop_table("tenant_access_audit_logs")

    with op.batch_alter_table("tenant_configs", schema=None) as batch_op:
        batch_op.drop_index("ix_tenant_configs_ecole_id")
    op.drop_table("tenant_configs")

    with op.batch_alter_table("students", schema=None) as batch_op:
        batch_op.drop_constraint("uq_student_global_uid", type_="unique")
        batch_op.drop_column("global_student_uid")

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_constraint("uq_user_ecole_email", type_="unique")
        batch_op.drop_index("ix_users_email")
        batch_op.create_index("ix_users_email", ["email"], unique=True)

    with op.batch_alter_table("students", schema=None) as batch_op:
        batch_op.drop_constraint("uq_student_ecole_matricule", type_="unique")
        batch_op.drop_index("ix_students_matricule")
        batch_op.create_index("ix_students_matricule", ["matricule"], unique=True)

    with op.batch_alter_table("grades", schema=None) as batch_op:
        batch_op.drop_constraint(
            "uq_grade_ecole_enrollment_course_period", type_="unique"
        )
        batch_op.create_unique_constraint(
            "uq_grade_enrollment_course_period",
            ["enrollment_id", "course_id", "period_id"],
        )

    with op.batch_alter_table("teacher_assignments", schema=None) as batch_op:
        batch_op.drop_constraint(
            "uq_assignment_ecole_teacher_course", type_="unique"
        )
        batch_op.create_unique_constraint(
            "uq_assignment_teacher_course", ["teacher_id", "course_id"]
        )

    with op.batch_alter_table("enrollments", schema=None) as batch_op:
        batch_op.drop_constraint("uq_enrollment_ecole_student_year", type_="unique")
        batch_op.create_unique_constraint(
            "uq_enrollment_student_year", ["student_id", "academic_year_id"]
        )

    with op.batch_alter_table("courses", schema=None) as batch_op:
        batch_op.drop_constraint("uq_course_ecole_class_code", type_="unique")
        batch_op.create_unique_constraint(
            "uq_course_class_code", ["school_class_id", "code"]
        )

    with op.batch_alter_table("evaluation_periods", schema=None) as batch_op:
        batch_op.drop_constraint("uq_period_ecole_year_sequence", type_="unique")
        batch_op.create_unique_constraint(
            "uq_period_year_sequence", ["academic_year_id", "sequence_order"]
        )

    with op.batch_alter_table("school_classes", schema=None) as batch_op:
        batch_op.drop_constraint("uq_class_ecole_year_name", type_="unique")
        batch_op.create_unique_constraint(
            "uq_class_year_name", ["academic_year_id", "name"]
        )

    with op.batch_alter_table("sections", schema=None) as batch_op:
        batch_op.drop_constraint("uq_section_ecole_code", type_="unique")
    if is_postgres:
        op.execute("ALTER TABLE sections ADD CONSTRAINT sections_code_key UNIQUE (code)")
    else:
        with op.batch_alter_table("sections", schema=None) as batch_op:
            batch_op.create_unique_constraint("sections_code_key", ["code"])

    with op.batch_alter_table("academic_years", schema=None) as batch_op:
        batch_op.drop_constraint("uq_academic_year_ecole_label", type_="unique")
    if is_postgres:
        op.execute(
            "ALTER TABLE academic_years ADD CONSTRAINT academic_years_label_key UNIQUE (label)"
        )
    else:
        with op.batch_alter_table("academic_years", schema=None) as batch_op:
            batch_op.create_unique_constraint("academic_years_label_key", ["label"])

    for table_name in reversed(TENANT_TABLES):
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            batch_op.drop_index(f"ix_{table_name}_ecole_id")
            batch_op.drop_constraint(
                f"fk_{table_name}_ecole_id_institutions", type_="foreignkey"
            )
            batch_op.drop_column("ecole_id")

    with op.batch_alter_table("institutions", schema=None) as batch_op:
        batch_op.drop_constraint("uq_institution_custom_domain", type_="unique")
        batch_op.drop_constraint("uq_institution_domain", type_="unique")
        batch_op.drop_column("is_active")
        batch_op.drop_column("locale")
        batch_op.drop_column("custom_domain")
        batch_op.drop_column("domain")

    op.drop_table("calculation_strategies")
    with op.batch_alter_table("super_admins", schema=None) as batch_op:
        batch_op.drop_index("ix_super_admins_email")
    op.drop_table("super_admins")
