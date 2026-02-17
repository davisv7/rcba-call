from tests.conftest import _make_user


def test_register_creates_org_and_user(client):
    resp = client.post("/register", data={
        "org_name": "New Org", "email": "new@test.com", "password": "secret123"
    }, follow_redirects=False)
    assert resp.status_code == 303
    assert "/members" in resp.headers["location"]


def test_register_duplicate_email(auth_client, client):
    resp = client.post("/register", data={
        "org_name": "Dup Org", "email": "test@example.com", "password": "secret123"
    }, follow_redirects=True)
    assert "already registered" in resp.text


def test_login_correct_creds(client):
    client.post("/register", data={
        "org_name": "Login Org", "email": "login@test.com", "password": "pass123"
    })
    resp = client.post("/login", data={
        "email": "login@test.com", "password": "pass123"
    }, follow_redirects=False)
    assert resp.status_code == 303
    assert "/members" in resp.headers["location"]


def test_login_wrong_password(client):
    client.post("/register", data={
        "org_name": "WP Org", "email": "wp@test.com", "password": "pass123"
    })
    resp = client.post("/login", data={
        "email": "wp@test.com", "password": "wrongpass"
    }, follow_redirects=True)
    assert "Invalid" in resp.text


def test_logout(auth_client):
    resp = auth_client.get("/logout", follow_redirects=False)
    assert resp.status_code == 303
    assert "/login" in resp.headers["location"]


def test_protected_routes_redirect(client):
    for path in ["/members", "/recordings", "/meetings", "/send", "/log"]:
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code == 302, f"{path} should redirect when unauthenticated"
        assert "/login" in resp.headers["location"]
