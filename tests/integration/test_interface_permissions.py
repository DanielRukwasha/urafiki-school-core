"""Proof from raw server responses, before any CSS or JavaScript runs."""

from html.parser import HTMLParser

import pytest

from app.models.deliberation_workflow import PeriodPublication, PublicationStatus
from app.models.grading import Grade
from app.models.teaching import TeacherAssignment
from app.models.user import RoleEnum
from app.security.tenant import resolve_tenant
from tests.integration.test_titulaire import second_grille_ligne as second_line_fixture

second_grille_ligne = second_line_fixture


class Controls(HTMLParser):
    def __init__(self):
        super().__init__()
        self.grade_inputs = []
        self.inputs = []

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if tag == "input":
            self.inputs.append(data)
            if "grade-input" in data.get("class", "").split():
                self.grade_inputs.append(data)


@pytest.mark.parametrize("status", [PublicationStatus.SUBMITTED, PublicationStatus.PUBLISHED])
def test_locked_publication_has_no_grade_input_or_sync_action(
    app, client, db, tenant_a, make_user, school_class, grille_ligne, enrollment, evaluation_period, status,
):
    with app.test_request_context("/", base_url=f"http://{tenant_a.domain}"):
        resolve_tenant()
        user, password = make_user(role=RoleEnum.DIRECTION)
        db.session.add(PeriodPublication(school_class_id=school_class.id, period_id=evaluation_period.id, status=status))
        db.session.commit()
    client.post("/auth/login", data={"email": user.email, "password": password})
    body = client.get(f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}/grid").get_data(as_text=True)
    controls = Controls()
    controls.feed(body)
    assert not controls.grade_inputs
    assert 'id="sync-form"' not in body
    assert 'id="retry-sync"' not in body
    assert 'class="grade-readonly"' in body


def test_unassigned_course_and_grade_never_reach_response(
    app, client, db, tenant_a, make_user, school_class, grille_ligne, enrollment, evaluation_period, second_grille_ligne,
):
    with app.test_request_context("/", base_url=f"http://{tenant_a.domain}"):
        resolve_tenant()
        user, password = make_user()
        # A unique identity and score can be searched in the entire raw HTML.
        second_grille_ligne.cours.name = "INVISIBLE_COURSE_9f3e"
        db.session.add(TeacherAssignment(teacher_id=user.id, school_class_id=school_class.id, grille_cours_ligne_id=grille_ligne.id))
        db.session.add(Grade(enrollment_id=enrollment.id, grille_cours_ligne_id=second_grille_ligne.id, period_id=evaluation_period.id, score="19.37", entered_by_id=user.id))
        db.session.commit()
    client.post("/auth/login", data={"email": user.email, "password": password})
    response = client.get(f"/portal/classes/{school_class.id}/periods/{evaluation_period.id}/grid")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "INVISIBLE_COURSE_9f3e" not in body
    assert "19.37" not in body
    assert f'data-course="{second_grille_ligne.id}"' not in body
