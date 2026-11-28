"""Published reports expose audit history, never editable report values."""

from decimal import Decimal

from app.models.course import Course
from app.models.grading import Grade
from app.models.grille import GrilleCoursLigne, GrilleCoursLigneMaximum
from app.models.institution import Institution
from app.models.journal import SensitiveReadKind, SensitiveReadLog
from app.models.teaching import TeacherAssignment
from app.models.user import RoleEnum
from tests.integration.test_bulletin_versions import published as published_fixture

published = published_fixture


def test_published_history_and_motivated_correction(client, published, db):
    response = client.get(published["base"])
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'data-bulletin-version="1"' in html
    assert published["user"].full_name in html
    assert "Première publication" in html
    assert 'name="motif"' in html and 'required minlength="10"' in html
    assert "irréversible" in html
    assert 'class="grade-input"' not in html
    assert 'name="score"' not in html

    grade = Grade.query.execution_options(skip_tenant_filter=True).one()
    grade.score = Decimal("16")
    db.session.commit()

    motif = "Correction documentée <script>alert(1)</script>"
    assert client.post(published["base"] + "/correction", data={"motif": motif}).status_code == 302
    html = client.get(published["base"]).get_data(as_text=True)
    assert 'data-bulletin-version="2"' in html
    assert 'data-bulletin-version="1"' in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)</script>" not in html

    reads = SensitiveReadLog.query.execution_options(skip_tenant_filter=True).filter_by(
        user_id=published["user"].id,
        kind=SensitiveReadKind.BULLETIN_CONSULTATION.value,
    )
    assert reads.count() == 0

    bulletin_url = published["base"].removesuffix("/consolidation") + "/print/bulletins"
    assert client.get(bulletin_url + "?version=999").status_code == 404
    assert reads.count() == 0
    assert client.get(bulletin_url).status_code == 200
    (read,) = reads.all()
    assert read.resource == bulletin_url
    assert read.ecole_id == published["class"].ecole_id


def test_motif_is_only_sent_to_the_class_titulaire_and_affected_teacher(
    client, published, db, make_user, grille_ligne
):
    klass = published["class"]
    grade = Grade.query.execution_options(skip_tenant_filter=True).one()
    grade.score = Decimal("16")
    db.session.commit()

    base = published["base"]
    motif = "Rectification de la cote du premier cours."
    assert client.post(base + "/correction", data={"motif": motif}).status_code == 302

    institution = db.session.get(Institution, klass.ecole_id)
    institution.name = "École fictive renommée"
    db.session.commit()
    ambiguous = "Motif de correction de l’en-tête du bulletin."
    assert client.post(base + "/correction", data={"motif": ambiguous}).status_code == 302
    direction = client.get(base).get_data(as_text=True)
    assert motif in direction and ambiguous in direction

    other_course = Course(ecole_id=klass.ecole_id, name="Histoire", code="HIST")
    db.session.add(other_course)
    db.session.flush()
    other_line = GrilleCoursLigne(
        ecole_id=klass.ecole_id,
        cours_id=other_course.id,
        grille_cours_id=grille_ligne.grille_cours_id,
        groupe_cours_id=grille_ligne.groupe_cours_id,
        ordre_affichage=2,
        ponderation=Decimal("1"),
    )
    db.session.add(other_line)
    db.session.flush()
    db.session.add(GrilleCoursLigneMaximum(
        ecole_id=klass.ecole_id, grille_cours_ligne_id=other_line.id,
        periode_id=published["period"].id, maximum=Decimal("20"),
    ))
    db.session.commit()

    titulaire, titulaire_password = make_user(email="titulaire@example.com")
    affected, affected_password = make_user(email="affected@example.com")
    unrelated, unrelated_password = make_user(email="unrelated@example.com")
    secretariat, secretariat_password = make_user(
        email="secretariat@example.com", role=RoleEnum.SECRETARIAT
    )
    klass.titulaire_id = titulaire.id
    for teacher, line in ((affected, grille_ligne), (unrelated, other_line)):
        db.session.add(TeacherAssignment(
            ecole_id=klass.ecole_id, teacher_id=teacher.id,
            school_class_id=klass.id, grille_cours_ligne_id=line.id,
        ))
    db.session.commit()

    def login_as(user, password):
        client.get("/auth/logout")
        assert client.post(
            "/auth/login", data={"email": user.email, "password": password}
        ).status_code == 302

    grid_url = base.removesuffix("/consolidation") + "/grid"
    login_as(titulaire, titulaire_password)
    response = client.get(base)
    assert response.status_code == 200
    assert motif in response.get_data(as_text=True)
    assert ambiguous in response.get_data(as_text=True)
    assert 'name="motif"' not in response.get_data(as_text=True)

    login_as(affected, affected_password)
    response = client.get(grid_url)
    assert response.status_code == 200
    assert motif in response.get_data(as_text=True)
    assert ambiguous not in response.get_data(as_text=True)
    assert motif not in client.get(base).get_data(as_text=True)

    login_as(unrelated, unrelated_password)
    response = client.get(grid_url)
    assert response.status_code == 200
    assert motif not in response.get_data(as_text=True)
    assert ambiguous not in response.get_data(as_text=True)

    login_as(secretariat, secretariat_password)
    bulletin_url = base.removesuffix("/consolidation") + "/print/bulletins"
    response = client.get(bulletin_url)
    assert response.status_code == 200
    assert motif not in response.get_data(as_text=True)
    assert ambiguous not in response.get_data(as_text=True)
    assert motif not in client.get(base).get_data(as_text=True)
