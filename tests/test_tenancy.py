from tests.conftest import _make_user, _auth_cookies, make_member, make_meeting, make_recording
from fastapi.testclient import TestClient
from app import app
from database import SessionLocal
from models import CallLog, Member, Recording, Meeting
from datetime import date


def _login(email, org_id, user_id):
    return TestClient(app, cookies=_auth_cookies(user_id, org_id))


def test_members_isolated():
    org_a, uid_a = _make_user("a@test.com", "Org A", "org-a")
    org_b, uid_b = _make_user("b@test.com", "Org B", "org-b")

    client_a = _login("a@test.com", org_a, uid_a)
    client_b = _login("b@test.com", org_b, uid_b)

    client_a.post("/members", data={"name": "OrgA Member", "phone": "5551112222"})
    client_b.post("/members", data={"name": "OrgB Member", "phone": "5553334444"})

    resp_a = client_a.get("/members")
    assert "OrgA Member" in resp_a.text
    assert "OrgB Member" not in resp_a.text

    resp_b = client_b.get("/members")
    assert "OrgB Member" in resp_b.text
    assert "OrgA Member" not in resp_b.text


def test_recordings_isolated():
    org_a, uid_a = _make_user("a2@test.com", "Org A2", "org-a2")
    org_b, uid_b = _make_user("b2@test.com", "Org B2", "org-b2")

    db = SessionLocal()
    r_a = Recording(org_id=org_a, name="RecA", filename="a/test.mp3")
    r_b = Recording(org_id=org_b, name="RecB", filename="b/test.mp3")
    db.add_all([r_a, r_b])
    db.commit()
    db.close()

    client_a = _login("a2@test.com", org_a, uid_a)
    resp_a = client_a.get("/recordings")
    assert "RecA" in resp_a.text
    assert "RecB" not in resp_a.text


def test_meetings_isolated():
    org_a, uid_a = _make_user("a3@test.com", "Org A3", "org-a3")
    org_b, uid_b = _make_user("b3@test.com", "Org B3", "org-b3")

    client_a = _login("a3@test.com", org_a, uid_a)
    client_b = _login("b3@test.com", org_b, uid_b)

    client_a.post("/meetings", data={"title": "MeetA", "meeting_date": "2025-06-15"})
    client_b.post("/meetings", data={"title": "MeetB", "meeting_date": "2025-06-15"})

    resp_a = client_a.get("/meetings")
    assert "MeetA" in resp_a.text
    assert "MeetB" not in resp_a.text


def test_cant_send_with_other_orgs_resources():
    org_a, uid_a = _make_user("a4@test.com", "Org A4", "org-a4")
    org_b, uid_b = _make_user("b4@test.com", "Org B4", "org-b4")

    db = SessionLocal()
    rec = Recording(org_id=org_b, name="OrgB Rec", filename="b/test.mp3")
    mtg = Meeting(org_id=org_b, title="OrgB Meet", meeting_date=date(2025, 6, 15))
    db.add_all([rec, mtg])
    db.commit()
    mtg_id, rec_id = mtg.id, rec.id
    db.close()

    client_a = _login("a4@test.com", org_a, uid_a)
    resp = client_a.post("/send", data={
        "meeting_id": mtg_id, "recording_id": rec_id
    }, follow_redirects=True)
    assert resp.status_code == 200

    db = SessionLocal()
    logs = db.query(CallLog).filter_by(org_id=org_a).all()
    assert len(logs) == 0
    db.close()


def test_call_log_filtered_by_org():
    org_a, uid_a = _make_user("a5@test.com", "Org A5", "org-a5")
    org_b, uid_b = _make_user("b5@test.com", "Org B5", "org-b5")

    db = SessionLocal()
    m = Member(org_id=org_a, name="MemberA", phone="+15551234567")
    r = Recording(org_id=org_a, name="Rec", filename="a/test.mp3")
    mtg = Meeting(org_id=org_a, title="Meet", meeting_date=date(2025, 6, 15))
    mtg.members = [m]
    db.add_all([m, r, mtg])
    db.commit()

    cl = CallLog(org_id=org_a, meeting_id=mtg.id, recording_id=r.id,
                 member_id=m.id, status="completed")
    db.add(cl)
    db.commit()
    db.close()

    client_b = _login("b5@test.com", org_b, uid_b)
    resp_b = client_b.get("/log")
    assert "MemberA" not in resp_b.text
