import pytest

from app.models.user import RoleEnum


def login(client, email, password):
    return client.post("/auth/login", data={"email": email, "password": password})


def test_dashboard_requires_authentication(client):
    response = client.get("/admin/")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


@pytest.mark.parametrize(
    "role", [RoleEnum.DIRECTION, RoleEnum.ENSEIGNANT, RoleEnum.SECRETARIAT]
)
def test_dashboard_accessible_to_every_role(client, make_user, role):
    make_user(email=f"{role.value.lower()}@example.com", role=role, password="Secret123!")
    login(client, f"{role.value.lower()}@example.com", "Secret123!")

    response = client.get("/admin/")
    assert response.status_code == 200


def test_users_list_allowed_for_direction(client, make_user):
    make_user(email="direction@example.com", role=RoleEnum.DIRECTION, password="Secret123!")
    login(client, "direction@example.com", "Secret123!")

    response = client.get("/admin/users")
    assert response.status_code == 200


def test_users_list_forbidden_for_teacher(client, make_user):
    make_user(email="teacher@example.com", role=RoleEnum.ENSEIGNANT, password="Secret123!")
    login(client, "teacher@example.com", "Secret123!")

    response = client.get("/admin/users")
    assert response.status_code == 403


def test_academic_years_allowed_for_secretariat(client, make_user):
    make_user(
        email="secretariat@example.com", role=RoleEnum.SECRETARIAT, password="Secret123!"
    )
    login(client, "secretariat@example.com", "Secret123!")

    response = client.get("/admin/academic-years")
    assert response.status_code == 200


def test_academic_years_forbidden_for_teacher(client, make_user):
    make_user(email="teacher@example.com", role=RoleEnum.ENSEIGNANT, password="Secret123!")
    login(client, "teacher@example.com", "Secret123!")

    response = client.get("/admin/academic-years")
    assert response.status_code == 403
