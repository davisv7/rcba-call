import os
import logging
from concurrent.futures import ThreadPoolExecutor
from twilio.rest import Client
from database import SessionLocal
from models import CallLog, Member, Meeting
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

executor = ThreadPoolExecutor(max_workers=10)


def get_twilio_client():
    return Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])


def send_reminders(meeting_id, recording_id, org_id):
    db = SessionLocal()
    try:
        meeting = db.get(Meeting, meeting_id)
        members = [m for m in meeting.members if m.active] if meeting else []
        domain = os.environ.get("DOMAIN", "localhost:5000")
        scheme = "http" if "localhost" in domain else "https"
        from_number = os.environ.get("TWILIO_FROM_NUMBER", os.environ.get("TWILIO_FROM", ""))

        logger.info("Sending reminders to %d members (meeting=%d, recording=%d, org=%d)",
                     len(members), meeting_id, recording_id, org_id)

        for member in members:
            entry = CallLog(
                org_id=org_id,
                meeting_id=meeting_id,
                recording_id=recording_id,
                member_id=member.id,
                status="queued",
            )
            db.add(entry)
            db.commit()

            executor.submit(_place_call, entry.id, member.phone, recording_id, domain, scheme, from_number)
    finally:
        db.close()


def _place_call(log_id, phone, recording_id, domain, scheme, from_number):
    db = SessionLocal()
    try:
        entry = db.get(CallLog, log_id)
        if entry.status == "canceled":
            db.close()
            return
        try:
            client = get_twilio_client()
            twiml_url = f"{scheme}://{domain}/twiml?recording_id={recording_id}"
            status_url = f"{scheme}://{domain}/api/call-status"

            logger.info("Placing call to %s, twiml_url=%s", phone, twiml_url)

            call = client.calls.create(
                to=phone,
                from_=from_number,
                url=twiml_url,
                status_callback=status_url,
                status_callback_event=["initiated", "ringing", "answered", "completed"],
                status_callback_method="POST",
            )
            entry.twilio_call_sid = call.sid
            entry.status = "initiated"
            logger.info("Call placed: SID=%s", call.sid)
        except Exception as e:
            logger.error("Call to %s failed: %s", phone, e)
            entry.status = "failed"
        entry.updated_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()
