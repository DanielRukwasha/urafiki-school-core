from app.models.user import RoleEnum


def test_login_page_loads(client):
    response = client.get("/auth/login")
    assert response.status_code == 200


def test_login_with_valid_credentials_redirects_to_dashboard(client, make_user):
    make_user(email="direction@example.com", role=RoleEnum.DIRECTION, password="Secret123!")

    response = client.post(
        "/auth/login",
        data={"email": "direction@example.com", "password": "Secret123!"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Bienvenue" in response.data


def test_login_with_invalid_password_shows_error(client, make_user):
    make_user(email="direction@example.com", role=RoleEnum.DIRECTION, password="Secret123!")

    response = client.post(
        "/auth/login",
        data={"email": "direction@example.com", "password": "wrong-password"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"invalide" in response.data


def test_logout_requires_login(client):
    response = client.get("/auth/logout")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_login_then_logout_clears_session(client, make_user):
    make_user(email="direction@example.com", role=RoleEnum.DIRECTION, password="Secret123!")
    client.post(
        "/auth/login",
        data={"email": "direction@example.com", "password": "Secret123!"},
    )
    response = client.get("/auth/logout", follow_redirects=True)
    assert response.status_code == 200

    protected = client.get("/admin/")
    assert protected.status_code == 302
