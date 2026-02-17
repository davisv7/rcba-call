import os
import csv
import re
import uuid
import subprocess
import io
from datetime import datetime, timezone

import bcrypt
from fastapi import FastAPI, Request, Depends, Form, UploadFile, File, Query
from fastapi.responses import RedirectResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from dotenv import load_dotenv
from twilio.twiml.voice_response import VoiceResponse

load_dotenv()

from database import get_db, engine
from models import Base, Organization, User, Member, Recording, Meeting, CallLog
from auth import create_access_token, get_current_user, get_optional_user

app = FastAPI()

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(os.path.join(os.path.dirname(__file__), "static"), exist_ok=True)

app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOAD_FOLDER), name="uploads")

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))


def _slugify(name):
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "org"


MAX_AUDIO_SIZE = 50 * 1024 * 1024
MAX_CSV_SIZE = 5 * 1024 * 1024


def _valid_phone(phone):
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("1") and len(digits) == 11:
        digits = digits[1:]
    if len(digits) != 10:
        return None
    return f"+1{digits}"


def _org_upload_dir(org_id):
    path = os.path.join(UPLOAD_FOLDER, str(org_id))
    os.makedirs(path, exist_ok=True)
    return path


def _redirect(path, msg=None):
    url = path
    if msg:
        url += ("&" if "?" in path else "?") + f"msg={msg}"
    return RedirectResponse(url=url, status_code=303)


# --- Auth ---

@app.get("/register")
def register_page(request: Request, msg: str = ""):
    return templates.TemplateResponse("register.html", {"request": request, "msg": msg})


@app.post("/register")
def register(
    request: Request,
    org_name: str = Form(""),
    email: str = Form(""),
    password: str = Form(""),
    db: Session = Depends(get_db),
):
    org_name = org_name.strip()
    email = email.strip()
    if not org_name or not email or not password:
        return _redirect("/register", "All fields are required.")

    if db.query(User).filter_by(email=email).first():
        return _redirect("/register", "Email already registered.")

    slug = _slugify(org_name)
    base_slug = slug
    counter = 1
    while db.query(Organization).filter_by(slug=slug).first():
        slug = f"{base_slug}-{counter}"
        counter += 1

    org = Organization(name=org_name, slug=slug)
    db.add(org)
    db.flush()

    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    user = User(org_id=org.id, email=email, password_hash=pw_hash, role="owner")
    db.add(user)
    db.commit()

    token = create_access_token(user.id, org.id)
    resp = RedirectResponse(url="/members", status_code=303)
    resp.set_cookie("access_token", token, httponly=True, samesite="lax")
    return resp


@app.get("/login")
def login_page(request: Request, msg: str = ""):
    return templates.TemplateResponse("login.html", {"request": request, "msg": msg})


@app.post("/login")
def login(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    db: Session = Depends(get_db),
):
    email = email.strip()
    user = db.query(User).filter_by(email=email).first()
    if user and bcrypt.checkpw(password.encode(), user.password_hash.encode()):
        token = create_access_token(user.id, user.org_id)
        resp = RedirectResponse(url="/members", status_code=303)
        resp.set_cookie("access_token", token, httponly=True, samesite="lax")
        return resp
    return _redirect("/login", "Invalid email or password.")


@app.get("/logout")
def logout():
    resp = RedirectResponse(url="/login", status_code=303)
    resp.delete_cookie("access_token")
    return resp


# --- Pages ---

@app.get("/")
def index(request: Request, user: User = Depends(get_optional_user)):
    if user:
        return RedirectResponse(url="/members", status_code=303)
    return templates.TemplateResponse("landing.html", {"request": request})


@app.get("/members")
def members_page(
    request: Request,
    msg: str = "",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    members = db.query(Member).filter_by(org_id=user.org_id).order_by(Member.name).all()
    return templates.TemplateResponse("members.html", {
        "request": request, "members": members, "current_user": user, "msg": msg,
    })


@app.post("/members")
async def members_post(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    form = await request.form()
    csv_file = form.get("csv_file")

    if csv_file and hasattr(csv_file, "filename") and csv_file.filename:
        contents = await csv_file.read()
        if len(contents) > MAX_CSV_SIZE:
            return _redirect("/members", "CSV too large (5 MB max).")
        stream = io.StringIO(contents.decode("utf-8", errors="replace"))
        reader = csv.reader(stream)
        added, skipped = 0, 0
        for row in reader:
            if len(row) >= 2:
                name = row[0].strip()
                phone = _valid_phone(row[1].strip())
                if name and phone:
                    db.add(Member(org_id=user.org_id, name=name, phone=phone))
                    added += 1
                elif name:
                    skipped += 1
        db.commit()
        msg = f"CSV imported: {added} added."
        if skipped:
            msg += f" {skipped} skipped (invalid phone)."
        return _redirect("/members", msg)

    name = form.get("name", "").strip()
    phone_raw = form.get("phone", "").strip()
    phone = _valid_phone(phone_raw) if phone_raw else None
    if name and phone:
        db.add(Member(org_id=user.org_id, name=name, phone=phone))
        db.commit()
        return _redirect("/members", "Member added.")
    elif name:
        return _redirect("/members", "Invalid phone number. Use a 10-digit US number.")
    return _redirect("/members")


@app.post("/members/{id}/edit")
def member_edit(
    id: int,
    name: str = Form(""),
    phone: str = Form(""),
    active: str = Form(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    m = db.query(Member).filter_by(id=id, org_id=user.org_id).first()
    if not m:
        return _redirect("/members", "Not found.")
    m.name = name.strip() or m.name
    cleaned = _valid_phone(phone.strip() or m.phone)
    if not cleaned:
        return _redirect("/members", "Invalid phone number. Use a 10-digit US number.")
    m.phone = cleaned
    m.active = active is not None
    db.commit()
    return _redirect("/members", "Updated.")


@app.post("/members/{id}/delete")
def member_delete(
    id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    m = db.query(Member).filter_by(id=id, org_id=user.org_id).first()
    if m:
        db.delete(m)
        db.commit()
    return _redirect("/members", "Deleted.")


@app.get("/recordings")
def recordings_page(
    request: Request,
    msg: str = "",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    recs = db.query(Recording).filter_by(org_id=user.org_id).order_by(Recording.created_at.desc()).all()
    return templates.TemplateResponse("recordings.html", {
        "request": request, "recordings": recs, "current_user": user, "msg": msg,
    })


@app.post("/api/recordings")
async def upload_recording(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    form = await request.form()
    name = (form.get("name", "") or "Untitled").strip()
    f = form.get("audio")
    if not f:
        return JSONResponse({"error": "No audio file"}, status_code=400)
    contents = await f.read()
    if len(contents) > MAX_AUDIO_SIZE:
        return JSONResponse({"error": "File too large (50 MB max)"}, status_code=400)

    org_id = user.org_id
    upload_dir = _org_upload_dir(org_id)
    uid = uuid.uuid4().hex[:10]
    webm_path = os.path.join(upload_dir, f"{uid}.webm")
    mp3_path = os.path.join(upload_dir, f"{uid}.mp3")
    with open(webm_path, "wb") as out:
        out.write(contents)

    result = subprocess.run(
        ["ffmpeg", "-y", "-i", webm_path, "-codec:a", "libmp3lame", "-qscale:a", "4", mp3_path],
        capture_output=True,
    )
    os.remove(webm_path)
    if result.returncode != 0:
        return JSONResponse({"error": "ffmpeg conversion failed"}, status_code=500)

    rec = Recording(org_id=org_id, name=name, filename=f"{org_id}/{uid}.mp3")
    db.add(rec)
    db.commit()
    return JSONResponse({"id": rec.id, "name": rec.name, "filename": rec.filename})


@app.post("/recordings/{id}/delete")
def recording_delete(
    id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rec = db.query(Recording).filter_by(id=id, org_id=user.org_id).first()
    if rec:
        path = os.path.join(UPLOAD_FOLDER, rec.filename)
        if os.path.exists(path):
            os.remove(path)
        db.delete(rec)
        db.commit()
    return _redirect("/recordings", "Recording deleted.")


@app.get("/meetings")
def meetings_page(
    request: Request,
    msg: str = "",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    meetings = db.query(Meeting).filter_by(org_id=user.org_id).order_by(Meeting.meeting_date.desc()).all()
    return templates.TemplateResponse("meetings.html", {
        "request": request, "meetings": meetings, "current_user": user, "msg": msg,
    })


@app.post("/meetings")
def meetings_post(
    request: Request,
    title: str = Form(""),
    meeting_date: str = Form(""),
    notes: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    title = title.strip()
    notes = notes.strip()
    if title and meeting_date:
        try:
            md = datetime.strptime(meeting_date, "%Y-%m-%d").date()
        except ValueError:
            return _redirect("/meetings", "Invalid date format.")
        db.add(Meeting(org_id=user.org_id, title=title, meeting_date=md, notes=notes))
        db.commit()
        return _redirect("/meetings", "Meeting created.")
    return _redirect("/meetings")


@app.get("/meetings/{id}")
def meeting_detail(
    id: int,
    request: Request,
    msg: str = "",
    next: str = "",
    meeting_id: str = "",
    recording_id: str = "",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    meeting = db.query(Meeting).filter_by(id=id, org_id=user.org_id).first()
    if not meeting:
        return _redirect("/meetings", "Not found.")
    all_members = db.query(Member).filter_by(org_id=user.org_id, active=True).order_by(Member.name).all()
    return templates.TemplateResponse("meeting_detail.html", {
        "request": request, "meeting": meeting, "all_members": all_members,
        "current_user": user, "msg": msg,
        "next_param": next, "meeting_id_param": meeting_id, "recording_id_param": recording_id,
    })


@app.post("/meetings/{id}/members")
async def meeting_members_update(
    id: int,
    request: Request,
    next: str = "",
    meeting_id: str = "",
    recording_id: str = "",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    meeting = db.query(Meeting).filter_by(id=id, org_id=user.org_id).first()
    if not meeting:
        return _redirect("/meetings", "Not found.")
    form = await request.form()
    selected_ids = [int(v) for v in form.getlist("member_ids")]
    members = db.query(Member).filter(Member.id.in_(selected_ids), Member.org_id == user.org_id).all()
    meeting.members = members
    db.commit()
    if next == "send":
        return _redirect(f"/send?meeting_id={meeting_id}&recording_id={recording_id}", "Meeting members updated.")
    return _redirect(f"/meetings/{id}", "Meeting members updated.")


@app.post("/meetings/{id}/delete")
def meeting_delete(
    id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    m = db.query(Meeting).filter_by(id=id, org_id=user.org_id).first()
    if m:
        db.delete(m)
        db.commit()
    return _redirect("/meetings", "Deleted.")


@app.get("/send")
def send_page(
    request: Request,
    msg: str = "",
    meeting_id: int = 0,
    recording_id: int = 0,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    meetings = db.query(Meeting).filter_by(org_id=user.org_id).order_by(Meeting.meeting_date.desc()).all()
    recordings = db.query(Recording).filter_by(org_id=user.org_id).order_by(Recording.created_at.desc()).all()
    return templates.TemplateResponse("send.html", {
        "request": request, "meetings": meetings, "recordings": recordings,
        "sel_meeting": meeting_id, "sel_recording": recording_id,
        "current_user": user, "msg": msg,
    })


@app.post("/send")
def send_post(
    meeting_id: int = Form(0),
    recording_id: int = Form(0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if meeting_id and recording_id:
        meeting = db.query(Meeting).filter_by(id=meeting_id, org_id=user.org_id).first()
        recording = db.query(Recording).filter_by(id=recording_id, org_id=user.org_id).first()
        if meeting and recording:
            from caller import send_reminders
            send_reminders(meeting_id, recording_id, user.org_id)
            return _redirect("/send", "Calls are being sent.")
    return _redirect("/send")


@app.get("/api/meeting-members")
def api_meeting_members(
    meeting_id: int = 0,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not meeting_id:
        return JSONResponse({"members": []})
    meeting = db.query(Meeting).filter_by(id=meeting_id, org_id=user.org_id).first()
    if not meeting:
        return JSONResponse({"members": []})
    members = [{"name": m.name, "phone": m.phone} for m in meeting.members if m.active]
    return JSONResponse({"members": members})


@app.get("/api/send-progress")
def send_progress(
    meeting_id: int = 0,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not meeting_id:
        return JSONResponse({"error": "missing meeting_id"}, status_code=400)
    logs = db.query(CallLog).filter_by(meeting_id=meeting_id, org_id=user.org_id).all()
    total = len(logs)
    completed = sum(1 for l in logs if l.status == "completed")
    failed = sum(1 for l in logs if l.status in ("failed", "busy", "no-answer", "canceled"))
    queued = total - completed - failed
    rows = [
        {"member": l.member.name, "phone": l.member.phone, "status": l.status}
        for l in logs
    ]
    return JSONResponse({"total": total, "completed": completed, "failed": failed, "queued": queued, "rows": rows})


@app.post("/api/cancel-calls")
def cancel_calls(
    meeting_id: int = Form(0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not meeting_id:
        return JSONResponse({"error": "missing meeting_id"}, status_code=400)
    canceled = (
        db.query(CallLog)
        .filter_by(meeting_id=meeting_id, org_id=user.org_id)
        .filter(CallLog.status.in_(["queued", "initiated"]))
        .update({"status": "canceled", "updated_at": datetime.now(timezone.utc)}, synchronize_session="fetch")
    )
    db.commit()
    return JSONResponse({"canceled": canceled})


@app.get("/log")
def call_log_page(
    request: Request,
    msg: str = "",
    meeting_id: int = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(CallLog).filter_by(org_id=user.org_id)
    if meeting_id:
        q = q.filter_by(meeting_id=meeting_id)
    logs = q.order_by(CallLog.initiated_at.desc()).all()
    meetings = db.query(Meeting).filter_by(org_id=user.org_id).order_by(Meeting.meeting_date.desc()).all()
    return templates.TemplateResponse("call_log.html", {
        "request": request, "logs": logs, "meetings": meetings,
        "selected_meeting": meeting_id, "current_user": user, "msg": msg,
    })


# --- Twilio endpoints ---

@app.api_route("/twiml", methods=["GET", "POST"])
def twiml(request: Request, recording_id: int = 0, db: Session = Depends(get_db)):
    rec = db.get(Recording, recording_id) if recording_id else None
    resp = VoiceResponse()
    if rec:
        domain = os.environ.get("DOMAIN", request.headers.get("host", "localhost:5000"))
        scheme = "https" if "localhost" not in domain else "http"
        resp.play(f"{scheme}://{domain}/uploads/{rec.filename}")
    else:
        resp.say("No recording found. Goodbye.")
    return Response(content=str(resp), media_type="text/xml")


@app.post("/api/call-status")
async def call_status(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    sid = form.get("CallSid")
    status = form.get("CallStatus")
    if sid and status:
        log = db.query(CallLog).filter_by(twilio_call_sid=sid).first()
        if log:
            log.status = status
            log.updated_at = datetime.now(timezone.utc)
            db.commit()
    return Response(status_code=204)
