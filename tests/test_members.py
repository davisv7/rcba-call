import io
from tests.conftest import make_member


def test_add_member_valid(auth_client):
    resp = auth_client.post("/members", data={
        "name": "Jane Doe", "phone": "5551234567"
    }, follow_redirects=True)
    assert "Member added" in resp.text


def test_add_member_invalid_phone(auth_client):
    resp = auth_client.post("/members", data={
        "name": "Jane Doe", "phone": "123"
    }, follow_redirects=True)
    assert "Invalid phone" in resp.text


def test_edit_member(auth_client):
    m_id = make_member(auth_client._org_id)
    resp = auth_client.post(f"/members/{m_id}/edit", data={
        "name": "Updated Name", "phone": "5559876543", "active": "active"
    }, follow_redirects=True)
    assert "Updated" in resp.text


def test_deactivate_member(auth_client):
    m_id = make_member(auth_client._org_id)
    resp = auth_client.post(f"/members/{m_id}/edit", data={
        "name": "John Doe", "phone": "5551234567"
    }, follow_redirects=True)
    assert resp.status_code == 200


def test_csv_import_valid(auth_client):
    csv_data = "Alice,5551112222\nBob,5553334444\n"
    resp = auth_client.post("/members", files={"csv_file": ("members.csv", csv_data.encode(), "text/csv")},
                            follow_redirects=True)
    assert "2 added" in resp.text


def test_csv_import_invalid_phones_skipped(auth_client):
    csv_data = "Alice,5551112222\nBob,123\n"
    resp = auth_client.post("/members", files={"csv_file": ("members.csv", csv_data.encode(), "text/csv")},
                            follow_redirects=True)
    assert "1 added" in resp.text
    assert "1 skipped" in resp.text


def test_csv_import_empty(auth_client):
    resp = auth_client.post("/members", files={"csv_file": ("empty.csv", b"", "text/csv")},
                            follow_redirects=True)
    assert "0 added" in resp.text


def test_phone_validation():
    from app import _valid_phone
    assert _valid_phone("5551234567") == "+15551234567"
    assert _valid_phone("15551234567") == "+15551234567"
    assert _valid_phone("(555) 123-4567") == "+15551234567"
    assert _valid_phone("abc") is None
    assert _valid_phone("12345") is None
    assert _valid_phone("") is None
