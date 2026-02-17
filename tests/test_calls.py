from unittest.mock import patch, MagicMock
from tests.conftest import make_member, make_recording, make_meeting
from database import SessionLocal
from models import CallLog


def test_send_creates_call_logs(auth_client):
    m_id = make_member(auth_client._org_id)
    rec_id = make_recording(auth_client._org_id)
    mtg_id = make_meeting(auth_client._org_id, member_ids=[m_id])

    with patch("caller.get_twilio_client") as mock_twilio:
        mock_call = MagicMock()
        mock_call.sid = "CA_fake_sid"
        mock_twilio.return_value.calls.create.return_value = mock_call

        resp = auth_client.post("/send", data={
            "meeting_id": mtg_id, "recording_id": rec_id
        }, follow_redirects=True)
        assert resp.status_code == 200

    import time
    time.sleep(1)

    db = SessionLocal()
    logs = db.query(CallLog).filter_by(meeting_id=mtg_id).all()
    assert len(logs) == 1
    assert logs[0].twilio_call_sid == "CA_fake_sid"
    db.close()


def test_twiml_valid_recording(client):
    rec_id = make_recording(1, name="Test", filename="1/test.mp3")
    resp = client.get(f"/twiml?recording_id={rec_id}")
    assert resp.status_code == 200
    assert "Play" in resp.text or "play" in resp.text


def test_twiml_invalid_recording(client):
    resp = client.get("/twiml?recording_id=99999")
    assert resp.status_code == 200
    assert "No recording" in resp.text or "no recording" in resp.text


def test_call_status_webhook(client):
    db = SessionLocal()
    from models import Member, Recording, Meeting
    m = Member(org_id=1, name="Test", phone="+15551234567")
    db.add(m)
    db.flush()
    rec = Recording(org_id=1, name="Rec", filename="1/test.mp3")
    db.add(rec)
    db.flush()
    mtg = Meeting(org_id=1, title="Meet", meeting_date=__import__("datetime").date(2025, 6, 15))
    mtg.members = [m]
    db.add(mtg)
    db.flush()
    log = CallLog(org_id=1, meeting_id=mtg.id, recording_id=rec.id,
                  member_id=m.id, twilio_call_sid="CA_test123", status="queued")
    db.add(log)
    db.commit()
    log_id = log.id
    db.close()

    resp = client.post("/api/call-status", data={
        "CallSid": "CA_test123", "CallStatus": "completed"
    })
    assert resp.status_code == 204

    db = SessionLocal()
    updated = db.get(CallLog, log_id)
    assert updated.status == "completed"
    db.close()


def test_send_progress(auth_client):
    m_id = make_member(auth_client._org_id)
    rec_id = make_recording(auth_client._org_id)
    mtg_id = make_meeting(auth_client._org_id, member_ids=[m_id])

    db = SessionLocal()
    log = CallLog(org_id=auth_client._org_id, meeting_id=mtg_id,
                  recording_id=rec_id, member_id=m_id, status="completed")
    db.add(log)
    db.commit()
    db.close()

    resp = auth_client.get(f"/api/send-progress?meeting_id={mtg_id}")
    data = resp.json()
    assert data["total"] == 1
    assert data["completed"] == 1
