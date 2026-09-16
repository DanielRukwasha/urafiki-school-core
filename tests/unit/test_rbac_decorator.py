import pytest
from flask_login import login_user
from werkzeug.exceptions import Forbidden

from app.models.user import RoleEnum
from app.security.rbac import roles_required


@roles_required(RoleEnum.DIRECTION)
def _direction_only_view():
    return "ok"


def test_matching_role_is_allowed(app, make_user):
    user, _ = make_user(email="direction@example.com", role=RoleEnum.DIRECTION)
    with app.test_request_context("/"):
        login_user(user)
        assert _direction_only_view() == "ok"


def test_wrong_role_is_forbidden(app, make_user):
    user, _ = make_user(email="teacher@example.com", role=RoleEnum.ENSEIGNANT)
    with app.test_request_context("/"):
        login_user(user)
        with pytest.raises(Forbidden):
            _direction_only_view()


def test_unauthenticated_redirects_to_login(app):
    with app.test_request_context("/"):
        response = _direction_only_view()
        assert response.status_code == 302
        assert "/auth/login" in response.headers["Location"]
