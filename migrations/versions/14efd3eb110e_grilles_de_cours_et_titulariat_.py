"""grilles de cours et titulariat contextuel

Business amendment covering two previously unmodeled realities:

(A) A course's weight and maximum vary by study level, and levels are a
    tenant-configurable referential (Niveau), not the free-floating
    `SchoolClass.level_order` integer. `Course` becomes a tenant-wide
    catalog entry; its weight, grouping, display order, grading mode and
    per-period maximum move onto a new grid referential
    (GrilleCours / GrilleCoursLigne / GrilleCoursLigneMaximum, grouped by
    GroupeCours) shared by every class of the same (section, niveau,
    academic_year). `Grade` now references a grid line, not a course
    directly, and gains `appreciation`/`statut` for non-numeric and
    justified-absence/exemption cases.

(B) Titulariat gains a historized source of truth (TitulaireHistorique),
    a temporary delegation mechanism (DelegationTitulariat), and a
    correction-request workflow (DemandeCorrection).

Data migration for (A): every existing (ecole, level_order) pair becomes
one Niveau row; every existing Course row (previously unique per class)
is deduplicated by (ecole, code) into one tenant-wide Course row, and one
GrilleCoursLigne is created per (grille, code) — so two classes that
happened to have separately-entered "Mathématiques" rows with different
coefficients each keep their own grid line (one per distinct
(section, niveau, academic_year) grid), while genuinely duplicate rows
for the very same grid collapse onto one. Each migrated line's single old
`max_score` is copied onto a GrilleCoursLigneMaximum row for every
evaluation period of its academic year — the faithful equivalent of the
old "one maximum for the whole course" behaviour. teacher_assignments and
grades are remapped from the old `course_id` to the new
`grille_cours_ligne_id` via this same mapping.

This migration necessarily changes what a "course" and a "grade" row
mean; downgrade() restores the pre-migration table SHAPES but cannot
losslessly restore the original per-class duplicate Course rows or the
distinction between per-period maxima once collapsed back to one
max_score per course (documented at each such point below) — the same
kind of one-way, schema-shape-only downgrade already established by
migration aa2202d3e6d9 for its Postgres enum widening.

Revision ID: 14efd3eb110e
Revises: aa2202d3e6d9
Create Date: 2026-09-18 12:00:00.000000

"""
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = '14efd3eb110e'
down_revision = 'aa2202d3e6d9'
branch_labels = None
depends_on = None


def _utcnow():
    return datetime.now(timezone.utc)


def _pk_table(name, *columns):
    """A `sa.Table` (not the lighter `sa.table()`) with a real primary key,
    so `result.inserted_primary_key` works for the id-generating inserts
    below on every dialect (SQLite's `lastrowid` included) — `sa.table()`
    carries no primary-key metadata at all."""
    return sa.Table(
        name, sa.MetaData(), sa.Column('id', sa.Integer, primary_key=True), *columns
    )


def upgrade():
    conn = op.get_bind()
    now = _utcnow()

    # ------------------------------------------------------------------
    # 1. New standalone referential/history tables.
    # ------------------------------------------------------------------
    op.create_table(
        'niveaux',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ecole_id', sa.Integer(), nullable=False),
        sa.Column('libelle', sa.String(length=100), nullable=False),
        sa.Column('ordre_affichage', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['ecole_id'], ['institutions.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('ecole_id', 'libelle', name='uq_niveau_ecole_libelle'),
    )
    op.create_index('ix_niveaux_ecole_id', 'niveaux', ['ecole_id'])

    op.create_table(
        'groupes_cours',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ecole_id', sa.Integer(), nullable=False),
        sa.Column('libelle', sa.String(length=150), nullable=False),
        sa.Column('ordre_affichage', sa.Integer(), nullable=False),
        sa.Column('affiche_sous_total', sa.Boolean(), nullable=False),
        sa.Column('entre_dans_total_general', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['ecole_id'], ['institutions.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('ecole_id', 'libelle', name='uq_groupe_cours_ecole_libelle'),
    )
    op.create_index('ix_groupes_cours_ecole_id', 'groupes_cours', ['ecole_id'])

    op.create_table(
        'grilles_cours',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ecole_id', sa.Integer(), nullable=False),
        sa.Column('section_id', sa.Integer(), nullable=False),
        sa.Column('niveau_id', sa.Integer(), nullable=False),
        sa.Column('academic_year_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['ecole_id'], ['institutions.id']),
        sa.ForeignKeyConstraint(['section_id'], ['sections.id']),
        sa.ForeignKeyConstraint(['niveau_id'], ['niveaux.id']),
        sa.ForeignKeyConstraint(['academic_year_id'], ['academic_years.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'ecole_id', 'section_id', 'niveau_id', 'academic_year_id',
            name='uq_grille_ecole_section_niveau_annee',
        ),
    )
    op.create_index('ix_grilles_cours_ecole_id', 'grilles_cours', ['ecole_id'])
    op.create_index('ix_grilles_cours_section_id', 'grilles_cours', ['section_id'])
    op.create_index('ix_grilles_cours_niveau_id', 'grilles_cours', ['niveau_id'])
    op.create_index('ix_grilles_cours_academic_year_id', 'grilles_cours', ['academic_year_id'])

    op.create_table(
        'grille_cours_lignes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ecole_id', sa.Integer(), nullable=False),
        sa.Column('grille_cours_id', sa.Integer(), nullable=False),
        sa.Column('cours_id', sa.Integer(), nullable=False),
        sa.Column('groupe_cours_id', sa.Integer(), nullable=False),
        sa.Column('ordre_affichage', sa.Integer(), nullable=False),
        sa.Column('ponderation', sa.Numeric(precision=6, scale=3), nullable=False),
        sa.Column('entre_dans_total_general', sa.Boolean(), nullable=False),
        sa.Column('note_par_appreciation', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint('ponderation > 0', name='ck_ligne_ponderation_positive'),
        sa.ForeignKeyConstraint(['ecole_id'], ['institutions.id']),
        sa.ForeignKeyConstraint(['grille_cours_id'], ['grilles_cours.id']),
        sa.ForeignKeyConstraint(['cours_id'], ['courses.id']),
        sa.ForeignKeyConstraint(['groupe_cours_id'], ['groupes_cours.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'ecole_id', 'grille_cours_id', 'cours_id', name='uq_ligne_ecole_grille_cours'
        ),
    )
    op.create_index('ix_grille_cours_lignes_ecole_id', 'grille_cours_lignes', ['ecole_id'])
    op.create_index('ix_grille_cours_lignes_grille_cours_id', 'grille_cours_lignes', ['grille_cours_id'])
    op.create_index('ix_grille_cours_lignes_cours_id', 'grille_cours_lignes', ['cours_id'])
    op.create_index('ix_grille_cours_lignes_groupe_cours_id', 'grille_cours_lignes', ['groupe_cours_id'])

    op.create_table(
        'grille_cours_ligne_maxima',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ecole_id', sa.Integer(), nullable=False),
        sa.Column('grille_cours_ligne_id', sa.Integer(), nullable=False),
        sa.Column('periode_id', sa.Integer(), nullable=False),
        sa.Column('maximum', sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('maximum > 0', name='ck_maximum_positive'),
        sa.ForeignKeyConstraint(['ecole_id'], ['institutions.id']),
        sa.ForeignKeyConstraint(['grille_cours_ligne_id'], ['grille_cours_lignes.id']),
        sa.ForeignKeyConstraint(['periode_id'], ['evaluation_periods.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'ecole_id', 'grille_cours_ligne_id', 'periode_id', name='uq_maximum_ecole_ligne_periode'
        ),
    )
    op.create_index('ix_grille_cours_ligne_maxima_ecole_id', 'grille_cours_ligne_maxima', ['ecole_id'])
    op.create_index(
        'ix_grille_cours_ligne_maxima_grille_cours_ligne_id',
        'grille_cours_ligne_maxima', ['grille_cours_ligne_id'],
    )
    op.create_index('ix_grille_cours_ligne_maxima_periode_id', 'grille_cours_ligne_maxima', ['periode_id'])

    op.create_table(
        'titulaire_historiques',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ecole_id', sa.Integer(), nullable=False),
        sa.Column('school_class_id', sa.Integer(), nullable=False),
        sa.Column('teacher_id', sa.Integer(), nullable=False),
        sa.Column('date_debut', sa.DateTime(timezone=True), nullable=False),
        sa.Column('date_fin', sa.DateTime(timezone=True), nullable=True),
        sa.Column('motif', sa.String(length=300), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['ecole_id'], ['institutions.id']),
        sa.ForeignKeyConstraint(['school_class_id'], ['school_classes.id']),
        sa.ForeignKeyConstraint(['teacher_id'], ['users.id']),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_titulaire_historiques_ecole_id', 'titulaire_historiques', ['ecole_id'])
    op.create_index('ix_titulaire_historiques_school_class_id', 'titulaire_historiques', ['school_class_id'])
    op.create_index('ix_titulaire_historiques_teacher_id', 'titulaire_historiques', ['teacher_id'])
    op.create_index(
        'ix_titulaire_hist_ecole_classe_debut', 'titulaire_historiques',
        ['ecole_id', 'school_class_id', 'date_debut'],
    )

    op.create_table(
        'delegations_titulariat',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ecole_id', sa.Integer(), nullable=False),
        sa.Column('school_class_id', sa.Integer(), nullable=False),
        sa.Column('delegant_id', sa.Integer(), nullable=False),
        sa.Column('delegataire_id', sa.Integer(), nullable=False),
        sa.Column('date_debut', sa.DateTime(timezone=True), nullable=False),
        sa.Column('date_fin', sa.DateTime(timezone=True), nullable=False),
        sa.Column('motif', sa.String(length=300), nullable=False),
        sa.Column(
            'statut', sa.Enum('ACTIVE', 'REVOQUEE', 'EXPIREE', name='statutdelegation'),
            nullable=False,
        ),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('date_fin > date_debut', name='ck_delegation_fin_apres_debut'),
        sa.ForeignKeyConstraint(['ecole_id'], ['institutions.id']),
        sa.ForeignKeyConstraint(['school_class_id'], ['school_classes.id']),
        sa.ForeignKeyConstraint(['delegant_id'], ['users.id']),
        sa.ForeignKeyConstraint(['delegataire_id'], ['users.id']),
        sa.ForeignKeyConstraint(['revoked_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_delegations_titulariat_ecole_id', 'delegations_titulariat', ['ecole_id'])
    op.create_index('ix_delegations_titulariat_school_class_id', 'delegations_titulariat', ['school_class_id'])
    op.create_index('ix_delegations_titulariat_delegant_id', 'delegations_titulariat', ['delegant_id'])
    op.create_index('ix_delegations_titulariat_delegataire_id', 'delegations_titulariat', ['delegataire_id'])

    op.create_table(
        'demandes_correction',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ecole_id', sa.Integer(), nullable=False),
        sa.Column('grade_id', sa.Integer(), nullable=False),
        sa.Column('demandeur_id', sa.Integer(), nullable=False),
        sa.Column('motif', sa.String(length=500), nullable=False),
        sa.Column(
            'statut',
            sa.Enum('EN_ATTENTE', 'ACCEPTEE', 'REFUSEE', 'TRAITEE', name='statutdemandecorrection'),
            nullable=False,
        ),
        sa.Column('traite_par_id', sa.Integer(), nullable=True),
        sa.Column('traite_le', sa.DateTime(timezone=True), nullable=True),
        sa.Column('commentaire_traitement', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['ecole_id'], ['institutions.id']),
        sa.ForeignKeyConstraint(['grade_id'], ['grades.id']),
        sa.ForeignKeyConstraint(['demandeur_id'], ['users.id']),
        sa.ForeignKeyConstraint(['traite_par_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_demandes_correction_ecole_id', 'demandes_correction', ['ecole_id'])
    op.create_index('ix_demandes_correction_grade_id', 'demandes_correction', ['grade_id'])
    op.create_index('ix_demandes_correction_demandeur_id', 'demandes_correction', ['demandeur_id'])

    # ------------------------------------------------------------------
    # 2. school_classes.niveau_id — one Niveau per existing (ecole,
    #    level_order) pair.
    # ------------------------------------------------------------------
    with op.batch_alter_table('school_classes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('niveau_id', sa.Integer(), nullable=True))

    school_classes_t = sa.table(
        'school_classes',
        sa.column('id', sa.Integer),
        sa.column('ecole_id', sa.Integer),
        sa.column('level_order', sa.Integer),
        sa.column('niveau_id', sa.Integer),
        sa.column('section_id', sa.Integer),
        sa.column('academic_year_id', sa.Integer),
    )
    niveaux_t = _pk_table(
        'niveaux',
        sa.Column('ecole_id', sa.Integer),
        sa.Column('libelle', sa.String),
        sa.Column('ordre_affichage', sa.Integer),
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
    )

    niveau_map = {}
    for row in conn.execute(
        sa.select(school_classes_t.c.ecole_id, school_classes_t.c.level_order).distinct()
    ):
        key = (row.ecole_id, row.level_order)
        result = conn.execute(
            niveaux_t.insert().values(
                ecole_id=row.ecole_id,
                libelle=f"Niveau {row.level_order}",
                ordre_affichage=row.level_order,
                created_at=now,
                updated_at=now,
            )
        )
        niveau_map[key] = result.inserted_primary_key[0]
        conn.execute(
            school_classes_t.update()
            .where(
                school_classes_t.c.ecole_id == row.ecole_id,
                school_classes_t.c.level_order == row.level_order,
            )
            .values(niveau_id=niveau_map[key])
        )

    with op.batch_alter_table('school_classes', schema=None) as batch_op:
        batch_op.alter_column('niveau_id', existing_type=sa.Integer(), nullable=False)
        batch_op.create_index('ix_school_classes_niveau_id', ['niveau_id'])
        batch_op.create_foreign_key(
            'fk_school_classes_niveau_id_niveaux', 'niveaux', ['niveau_id'], ['id']
        )

    # ------------------------------------------------------------------
    # 3. Course catalog + grid backfill from the old per-class courses.
    # ------------------------------------------------------------------
    courses_t = sa.table(
        'courses',
        sa.column('id', sa.Integer),
        sa.column('ecole_id', sa.Integer),
        sa.column('school_class_id', sa.Integer),
        sa.column('name', sa.String),
        sa.column('code', sa.String),
        sa.column('coefficient', sa.Numeric),
        sa.column('max_score', sa.Numeric),
    )
    groupes_t = _pk_table(
        'groupes_cours',
        sa.Column('ecole_id', sa.Integer),
        sa.Column('libelle', sa.String),
        sa.Column('ordre_affichage', sa.Integer),
        sa.Column('affiche_sous_total', sa.Boolean),
        sa.Column('entre_dans_total_general', sa.Boolean),
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
    )
    grilles_t = _pk_table(
        'grilles_cours',
        sa.Column('ecole_id', sa.Integer),
        sa.Column('section_id', sa.Integer),
        sa.Column('niveau_id', sa.Integer),
        sa.Column('academic_year_id', sa.Integer),
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
    )
    lignes_t = _pk_table(
        'grille_cours_lignes',
        sa.Column('ecole_id', sa.Integer),
        sa.Column('grille_cours_id', sa.Integer),
        sa.Column('cours_id', sa.Integer),
        sa.Column('groupe_cours_id', sa.Integer),
        sa.Column('ordre_affichage', sa.Integer),
        sa.Column('ponderation', sa.Numeric),
        sa.Column('entre_dans_total_general', sa.Boolean),
        sa.Column('note_par_appreciation', sa.Boolean),
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
    )
    maxima_t = _pk_table(
        'grille_cours_ligne_maxima',
        sa.Column('ecole_id', sa.Integer),
        sa.Column('grille_cours_ligne_id', sa.Integer),
        sa.Column('periode_id', sa.Integer),
        sa.Column('maximum', sa.Numeric),
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
    )
    periods_t = sa.table(
        'evaluation_periods', sa.column('id', sa.Integer), sa.column('academic_year_id', sa.Integer)
    )

    class_rows = {
        row.id: row
        for row in conn.execute(
            sa.select(
                school_classes_t.c.id,
                school_classes_t.c.ecole_id,
                school_classes_t.c.section_id,
                school_classes_t.c.niveau_id,
                school_classes_t.c.academic_year_id,
            )
        )
    }
    periods_by_year: dict[int, list[int]] = {}
    for row in conn.execute(sa.select(periods_t.c.id, periods_t.c.academic_year_id)):
        periods_by_year.setdefault(row.academic_year_id, []).append(row.id)

    all_course_rows = conn.execute(sa.select(courses_t)).fetchall()

    default_groupe = {}
    for ecole_id in {row.ecole_id for row in all_course_rows}:
        result = conn.execute(
            groupes_t.insert().values(
                ecole_id=ecole_id,
                libelle="Cours",
                ordre_affichage=1,
                affiche_sous_total=True,
                entre_dans_total_general=True,
                created_at=now,
                updated_at=now,
            )
        )
        default_groupe[ecole_id] = result.inserted_primary_key[0]

    # Survivor course row per (ecole, code) — the lowest id, deterministic.
    survivor_id: dict[tuple, int] = {}
    for row in sorted(all_course_rows, key=lambda r: r.id):
        key = (row.ecole_id, row.code)
        survivor_id.setdefault(key, row.id)

    grille_map: dict[tuple, int] = {}
    ligne_created: dict[tuple, int] = {}
    ligne_map: dict[int, int] = {}  # old course_id -> grille_cours_ligne_id

    for row in all_course_rows:
        code_key = (row.ecole_id, row.code)
        klass = class_rows[row.school_class_id]
        triple = (row.ecole_id, klass.section_id, klass.niveau_id, klass.academic_year_id)

        if triple not in grille_map:
            result = conn.execute(
                grilles_t.insert().values(
                    ecole_id=row.ecole_id,
                    section_id=klass.section_id,
                    niveau_id=klass.niveau_id,
                    academic_year_id=klass.academic_year_id,
                    created_at=now,
                    updated_at=now,
                )
            )
            grille_map[triple] = result.inserted_primary_key[0]
        grille_id = grille_map[triple]

        ligne_key = (grille_id, code_key)
        if ligne_key not in ligne_created:
            result = conn.execute(
                lignes_t.insert().values(
                    ecole_id=row.ecole_id,
                    grille_cours_id=grille_id,
                    cours_id=survivor_id[code_key],
                    groupe_cours_id=default_groupe[row.ecole_id],
                    ordre_affichage=1,
                    ponderation=row.coefficient,
                    entre_dans_total_general=True,
                    note_par_appreciation=False,
                    created_at=now,
                    updated_at=now,
                )
            )
            new_ligne_id = result.inserted_primary_key[0]
            ligne_created[ligne_key] = new_ligne_id
            for periode_id in periods_by_year.get(klass.academic_year_id, []):
                conn.execute(
                    maxima_t.insert().values(
                        ecole_id=row.ecole_id,
                        grille_cours_ligne_id=new_ligne_id,
                        periode_id=periode_id,
                        maximum=row.max_score,
                        created_at=now,
                        updated_at=now,
                    )
                )
        ligne_map[row.id] = ligne_created[ligne_key]

    # ------------------------------------------------------------------
    # 4. teacher_assignments: course_id -> (school_class_id, grille_cours_ligne_id).
    # ------------------------------------------------------------------
    with op.batch_alter_table('teacher_assignments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('school_class_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('grille_cours_ligne_id', sa.Integer(), nullable=True))

    assignments_t = sa.table(
        'teacher_assignments',
        sa.column('id', sa.Integer),
        sa.column('course_id', sa.Integer),
        sa.column('school_class_id', sa.Integer),
        sa.column('grille_cours_ligne_id', sa.Integer),
    )
    course_school_class = {row.id: row.school_class_id for row in all_course_rows}
    for row in conn.execute(sa.select(assignments_t.c.id, assignments_t.c.course_id)):
        conn.execute(
            assignments_t.update()
            .where(assignments_t.c.id == row.id)
            .values(
                school_class_id=course_school_class[row.course_id],
                grille_cours_ligne_id=ligne_map[row.course_id],
            )
        )

    with op.batch_alter_table('teacher_assignments', schema=None) as batch_op:
        batch_op.drop_constraint('uq_assignment_ecole_teacher_course', type_='unique')
        # `course_id`'s FK was never explicitly named (unnamed in the
        # initial migration) — dropping the column below drops it with it
        # on both dialects (Postgres auto-drops a local-column FK when its
        # column is dropped; SQLite batch mode excludes it when rebuilding
        # the table). Naming it here would fail on SQLite, which never
        # gave it a constraint name to match against.
        batch_op.drop_index('ix_teacher_assignments_course_id')
        batch_op.drop_column('course_id')
        batch_op.alter_column('school_class_id', existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column('grille_cours_ligne_id', existing_type=sa.Integer(), nullable=False)
        batch_op.create_index('ix_teacher_assignments_school_class_id', ['school_class_id'])
        batch_op.create_index('ix_teacher_assignments_grille_cours_ligne_id', ['grille_cours_ligne_id'])
        batch_op.create_foreign_key(
            'fk_teacher_assignments_school_class_id_school_classes',
            'school_classes', ['school_class_id'], ['id'],
        )
        batch_op.create_foreign_key(
            'fk_teacher_assignments_grille_cours_ligne_id_lignes',
            'grille_cours_lignes', ['grille_cours_ligne_id'], ['id'],
        )
        batch_op.create_unique_constraint(
            'uq_assignment_ecole_teacher_class_ligne',
            ['ecole_id', 'teacher_id', 'school_class_id', 'grille_cours_ligne_id'],
        )

    # ------------------------------------------------------------------
    # 5. grades: course_id -> grille_cours_ligne_id; score nullable;
    #    new appreciation/statut columns.
    # ------------------------------------------------------------------
    with op.batch_alter_table('grades', schema=None) as batch_op:
        batch_op.add_column(sa.Column('grille_cours_ligne_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('appreciation', sa.String(length=500), nullable=True))
        batch_op.add_column(
            sa.Column(
                'statut', sa.Enum('ABSENCE_JUSTIFIEE', 'DISPENSE', name='gradestatut'), nullable=True
            )
        )

    grades_t = sa.table(
        'grades', sa.column('id', sa.Integer), sa.column('course_id', sa.Integer),
        sa.column('grille_cours_ligne_id', sa.Integer),
    )
    for row in conn.execute(sa.select(grades_t.c.id, grades_t.c.course_id)):
        conn.execute(
            grades_t.update()
            .where(grades_t.c.id == row.id)
            .values(grille_cours_ligne_id=ligne_map[row.course_id])
        )

    with op.batch_alter_table('grades', schema=None) as batch_op:
        batch_op.drop_constraint('uq_grade_ecole_enrollment_course_period', type_='unique')
        # Same unnamed-FK note as teacher_assignments.course_id above.
        batch_op.drop_index('ix_grades_course_id')
        batch_op.drop_column('course_id')
        batch_op.alter_column('grille_cours_ligne_id', existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column('score', existing_type=sa.Numeric(precision=6, scale=2), nullable=True)
        batch_op.create_index('ix_grades_grille_cours_ligne_id', ['grille_cours_ligne_id'])
        batch_op.create_foreign_key(
            'fk_grades_grille_cours_ligne_id_lignes',
            'grille_cours_lignes', ['grille_cours_ligne_id'], ['id'],
        )
        batch_op.create_unique_constraint(
            'uq_grade_ecole_enrollment_ligne_period',
            ['ecole_id', 'enrollment_id', 'grille_cours_ligne_id', 'period_id'],
        )
        batch_op.create_check_constraint(
            'ck_grade_score_xor_appreciation',
            'NOT (score IS NOT NULL AND appreciation IS NOT NULL)',
        )

    # ------------------------------------------------------------------
    # 6. grade_audit_logs: course_id snapshot -> grille_cours_ligne_id.
    # ------------------------------------------------------------------
    with op.batch_alter_table('grade_audit_logs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('grille_cours_ligne_id', sa.Integer(), nullable=True))

    audit_t = sa.table(
        'grade_audit_logs', sa.column('id', sa.Integer), sa.column('course_id', sa.Integer),
        sa.column('grille_cours_ligne_id', sa.Integer),
    )
    for row in conn.execute(sa.select(audit_t.c.id, audit_t.c.course_id)):
        conn.execute(
            audit_t.update()
            .where(audit_t.c.id == row.id)
            .values(grille_cours_ligne_id=ligne_map[row.course_id])
        )

    with op.batch_alter_table('grade_audit_logs', schema=None) as batch_op:
        batch_op.drop_column('course_id')
        batch_op.alter_column('grille_cours_ligne_id', existing_type=sa.Integer(), nullable=False)

    # ------------------------------------------------------------------
    # 7. Drop non-survivor duplicate course rows, then reshape `courses`
    #    into a tenant-wide catalog (drop school_class_id/coefficient/
    #    max_score, unique on (ecole_id, code) alone).
    # ------------------------------------------------------------------
    survivor_ids = set(survivor_id.values())
    non_survivor_ids = [row.id for row in all_course_rows if row.id not in survivor_ids]
    if non_survivor_ids:
        conn.execute(courses_t.delete().where(courses_t.c.id.in_(non_survivor_ids)))

    with op.batch_alter_table('courses', schema=None) as batch_op:
        batch_op.drop_constraint('uq_course_ecole_class_code', type_='unique')
        # Same unnamed-FK note as teacher_assignments.course_id above.
        batch_op.drop_index('ix_courses_school_class_id')
        batch_op.drop_constraint('ck_course_coefficient_positive', type_='check')
        batch_op.drop_constraint('ck_course_max_score_positive', type_='check')
        batch_op.drop_column('school_class_id')
        batch_op.drop_column('coefficient')
        batch_op.drop_column('max_score')
        batch_op.create_unique_constraint('uq_course_ecole_code', ['ecole_id', 'code'])


def downgrade():
    """Restores the pre-migration table SHAPES. Cannot losslessly restore
    the original per-class duplicate Course rows (they were merged by
    (ecole, code) in upgrade()) or per-period maxima (collapsed to a
    single max_score per course here) — the same documented, one-way
    trade-off already established by aa2202d3e6d9 for its own
    non-reversible widening. Every class that shared a merged course
    keeps that course's (school_class_id-less) identity; this downgrade
    re-attaches each surviving course row to the FIRST class its grid
    line appears in, and takes each course's max_score from its EARLIEST
    (lowest id) GrilleCoursLigneMaximum row.
    """
    conn = op.get_bind()

    with op.batch_alter_table('courses', schema=None) as batch_op:
        batch_op.add_column(sa.Column('school_class_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('coefficient', sa.Numeric(precision=6, scale=3), nullable=True))
        batch_op.add_column(sa.Column('max_score', sa.Numeric(precision=6, scale=2), nullable=True))
        batch_op.drop_constraint('uq_course_ecole_code', type_='unique')

    courses_t = sa.table(
        'courses', sa.column('id', sa.Integer), sa.column('ecole_id', sa.Integer),
        sa.column('school_class_id', sa.Integer), sa.column('coefficient', sa.Numeric),
        sa.column('max_score', sa.Numeric),
    )
    lignes_t = sa.table(
        'grille_cours_lignes', sa.column('id', sa.Integer), sa.column('grille_cours_id', sa.Integer),
        sa.column('cours_id', sa.Integer), sa.column('ponderation', sa.Numeric),
    )
    grilles_t = sa.table(
        'grilles_cours', sa.column('id', sa.Integer), sa.column('section_id', sa.Integer),
        sa.column('niveau_id', sa.Integer), sa.column('academic_year_id', sa.Integer),
    )
    school_classes_t = sa.table(
        'school_classes', sa.column('id', sa.Integer), sa.column('section_id', sa.Integer),
        sa.column('niveau_id', sa.Integer), sa.column('academic_year_id', sa.Integer),
    )
    maxima_t = sa.table(
        'grille_cours_ligne_maxima', sa.column('id', sa.Integer),
        sa.column('grille_cours_ligne_id', sa.Integer), sa.column('maximum', sa.Numeric),
    )

    class_by_triple: dict[tuple, int] = {}
    for row in conn.execute(
        sa.select(
            school_classes_t.c.id, school_classes_t.c.section_id,
            school_classes_t.c.niveau_id, school_classes_t.c.academic_year_id,
        )
    ):
        class_by_triple.setdefault((row.section_id, row.niveau_id, row.academic_year_id), row.id)

    for course_row in conn.execute(sa.select(courses_t.c.id)):
        ligne_row = conn.execute(
            sa.select(lignes_t.c.id, lignes_t.c.grille_cours_id, lignes_t.c.ponderation)
            .where(lignes_t.c.cours_id == course_row.id)
            .order_by(lignes_t.c.id)
        ).first()
        if ligne_row is None:
            conn.execute(courses_t.delete().where(courses_t.c.id == course_row.id))
            continue
        grille_row = conn.execute(
            sa.select(grilles_t.c.section_id, grilles_t.c.niveau_id, grilles_t.c.academic_year_id)
            .where(grilles_t.c.id == ligne_row.grille_cours_id)
        ).first()
        school_class_id = class_by_triple.get(
            (grille_row.section_id, grille_row.niveau_id, grille_row.academic_year_id)
        )
        maximum_row = conn.execute(
            sa.select(maxima_t.c.maximum)
            .where(maxima_t.c.grille_cours_ligne_id == ligne_row.id)
            .order_by(maxima_t.c.id)
        ).first()
        conn.execute(
            courses_t.update()
            .where(courses_t.c.id == course_row.id)
            .values(
                school_class_id=school_class_id,
                coefficient=ligne_row.ponderation,
                max_score=maximum_row.maximum if maximum_row else 20,
            )
        )

    with op.batch_alter_table('courses', schema=None) as batch_op:
        batch_op.alter_column('school_class_id', existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column('coefficient', existing_type=sa.Numeric(precision=6, scale=3), nullable=False)
        batch_op.alter_column('max_score', existing_type=sa.Numeric(precision=6, scale=2), nullable=False)
        batch_op.create_index('ix_courses_school_class_id', ['school_class_id'])
        batch_op.create_foreign_key(
            'courses_school_class_id_fkey', 'school_classes', ['school_class_id'], ['id']
        )
        batch_op.create_check_constraint('ck_course_coefficient_positive', 'coefficient > 0')
        batch_op.create_check_constraint('ck_course_max_score_positive', 'max_score > 0')
        batch_op.create_unique_constraint(
            'uq_course_ecole_class_code', ['ecole_id', 'school_class_id', 'code']
        )

    with op.batch_alter_table('grade_audit_logs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('course_id', sa.Integer(), nullable=True))

    audit_t = sa.table(
        'grade_audit_logs', sa.column('id', sa.Integer), sa.column('course_id', sa.Integer),
        sa.column('grille_cours_ligne_id', sa.Integer),
    )
    lignes_cours_t = sa.table('grille_cours_lignes', sa.column('id', sa.Integer), sa.column('cours_id', sa.Integer))
    ligne_to_course = {
        row.id: row.cours_id for row in conn.execute(sa.select(lignes_cours_t.c.id, lignes_cours_t.c.cours_id))
    }
    for row in conn.execute(sa.select(audit_t.c.id, audit_t.c.grille_cours_ligne_id)):
        conn.execute(
            audit_t.update().where(audit_t.c.id == row.id)
            .values(course_id=ligne_to_course[row.grille_cours_ligne_id])
        )
    with op.batch_alter_table('grade_audit_logs', schema=None) as batch_op:
        batch_op.alter_column('course_id', existing_type=sa.Integer(), nullable=False)
        batch_op.drop_column('grille_cours_ligne_id')

    with op.batch_alter_table('grades', schema=None) as batch_op:
        batch_op.drop_constraint('ck_grade_score_xor_appreciation', type_='check')
        batch_op.drop_constraint('uq_grade_ecole_enrollment_ligne_period', type_='unique')
        batch_op.drop_constraint('fk_grades_grille_cours_ligne_id_lignes', type_='foreignkey')
        batch_op.drop_index('ix_grades_grille_cours_ligne_id')
        batch_op.add_column(sa.Column('course_id', sa.Integer(), nullable=True))

    grades_t = sa.table(
        'grades', sa.column('id', sa.Integer), sa.column('course_id', sa.Integer),
        sa.column('grille_cours_ligne_id', sa.Integer), sa.column('score', sa.Numeric),
    )
    for row in conn.execute(sa.select(grades_t.c.id, grades_t.c.grille_cours_ligne_id)):
        conn.execute(
            grades_t.update().where(grades_t.c.id == row.id)
            .values(course_id=ligne_to_course[row.grille_cours_ligne_id])
        )
    with op.batch_alter_table('grades', schema=None) as batch_op:
        batch_op.alter_column('course_id', existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column('score', existing_type=sa.Numeric(precision=6, scale=2), nullable=False)
        batch_op.drop_column('grille_cours_ligne_id')
        batch_op.drop_column('appreciation')
        batch_op.drop_column('statut')
        batch_op.create_index('ix_grades_course_id', ['course_id'])
        batch_op.create_foreign_key('grades_course_id_fkey', 'courses', ['course_id'], ['id'])
        batch_op.create_unique_constraint(
            'uq_grade_ecole_enrollment_course_period',
            ['ecole_id', 'enrollment_id', 'course_id', 'period_id'],
        )

    with op.batch_alter_table('teacher_assignments', schema=None) as batch_op:
        batch_op.drop_constraint('uq_assignment_ecole_teacher_class_ligne', type_='unique')
        batch_op.drop_constraint('fk_teacher_assignments_grille_cours_ligne_id_lignes', type_='foreignkey')
        batch_op.drop_constraint('fk_teacher_assignments_school_class_id_school_classes', type_='foreignkey')
        batch_op.drop_index('ix_teacher_assignments_grille_cours_ligne_id')
        batch_op.drop_index('ix_teacher_assignments_school_class_id')
        batch_op.add_column(sa.Column('course_id', sa.Integer(), nullable=True))

    assignments_t = sa.table(
        'teacher_assignments', sa.column('id', sa.Integer), sa.column('course_id', sa.Integer),
        sa.column('grille_cours_ligne_id', sa.Integer),
    )
    for row in conn.execute(sa.select(assignments_t.c.id, assignments_t.c.grille_cours_ligne_id)):
        conn.execute(
            assignments_t.update().where(assignments_t.c.id == row.id)
            .values(course_id=ligne_to_course[row.grille_cours_ligne_id])
        )
    with op.batch_alter_table('teacher_assignments', schema=None) as batch_op:
        batch_op.alter_column('course_id', existing_type=sa.Integer(), nullable=False)
        batch_op.drop_column('school_class_id')
        batch_op.drop_column('grille_cours_ligne_id')
        batch_op.create_index('ix_teacher_assignments_course_id', ['course_id'])
        batch_op.create_foreign_key(
            'teacher_assignments_course_id_fkey', 'courses', ['course_id'], ['id']
        )
        batch_op.create_unique_constraint(
            'uq_assignment_ecole_teacher_course', ['ecole_id', 'teacher_id', 'course_id']
        )

    with op.batch_alter_table('school_classes', schema=None) as batch_op:
        batch_op.drop_constraint('fk_school_classes_niveau_id_niveaux', type_='foreignkey')
        batch_op.drop_index('ix_school_classes_niveau_id')
        batch_op.drop_column('niveau_id')

    op.drop_table('demandes_correction')
    op.drop_table('delegations_titulariat')
    op.drop_table('titulaire_historiques')
    op.drop_table('grille_cours_ligne_maxima')
    op.drop_table('grille_cours_lignes')
    op.drop_table('grilles_cours')
    op.drop_table('groupes_cours')
    op.drop_table('niveaux')

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TYPE IF EXISTS statutdelegation")
        op.execute("DROP TYPE IF EXISTS statutdemandecorrection")
        op.execute("DROP TYPE IF EXISTS gradestatut")
