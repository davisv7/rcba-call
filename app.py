import os
import csv
import uuid
import subprocess
import io
from datetime import datetime, timezone
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for, jsonify,
    Response, send_from_directory, flash, session
)
from dotenv import load_dotenv
from twilio.twiml.voice_response import VoiceResponse

load_dotenv()

app = Flask(__name__)
db_path = os.path.join(os.path.dirname(__file__), "rcba.db")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-me-in-production")
app.config["UPLOAD_FOLDER"] = os.path.join(os.path.dirname(__file__), "uploads")

from models import db, Member, Recording, Meeting, CallLog

db.init_app(app)

with app.app_context():
    db.create_all()

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")


# --- Auth ---

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("members_page"))
        flash("Wrong password.")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect(url_for("login"))


# --- Pages ---

@app.route("/")
def index():
    if session.get("logged_in"):
        return redirect(url_for("members_page"))
    return render_template("landing.html")


@app.route("/members", methods=["GET", "POST"])
@login_required
def members_page():
    if request.method == "POST":
        # CSV import
        f = request.files.get("csv_file")
        if f and f.filename:
            stream = io.TextIOWrapper(f.stream, encoding="utf-8")
            reader = csv.reader(stream)
            for row in reader:
                if len(row) >= 2:
                    name, phone = row[0].strip(), row[1].strip()
                    if name and phone:
                        db.session.add(Member(name=name, phone=phone))
            db.session.commit()
            flash("CSV imported.")
            return redirect(url_for("members_page"))

        # Single add
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        if name and phone:
            db.session.add(Member(name=name, phone=phone))
            db.session.commit()
            flash("Member added.")
        return redirect(url_for("members_page"))

    members = Member.query.order_by(Member.name).all()
    return render_template("members.html", members=members)


@app.route("/members/<int:id>/edit", methods=["POST"])
@login_required
def member_edit(id):
    m = db.session.get(Member, id)
    if not m:
        flash("Not found.")
        return redirect(url_for("members_page"))
    m.name = request.form.get("name", m.name).strip()
    m.phone = request.form.get("phone", m.phone).strip()
    m.active = "active" in request.form
    db.session.commit()
    flash("Updated.")
    return redirect(url_for("members_page"))


@app.route("/members/<int:id>/delete", methods=["POST"])
@login_required
def member_delete(id):
    m = db.session.get(Member, id)
    if m:
        db.session.delete(m)
        db.session.commit()
        flash("Deleted.")
    return redirect(url_for("members_page"))


@app.route("/recordings")
@login_required
def recordings_page():
    recs = Recording.query.order_by(Recording.created_at.desc()).all()
    return render_template("recordings.html", recordings=recs)


@app.route("/api/recordings", methods=["POST"])
@login_required
def upload_recording():
    name = request.form.get("name", "").strip() or "Untitled"
    f = request.files.get("audio")
    if not f:
        return jsonify(error="No audio file"), 400

    uid = uuid.uuid4().hex[:10]
    webm_path = os.path.join(app.config["UPLOAD_FOLDER"], f"{uid}.webm")
    mp3_path = os.path.join(app.config["UPLOAD_FOLDER"], f"{uid}.mp3")
    f.save(webm_path)

    # Convert to MP3
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", webm_path, "-codec:a", "libmp3lame", "-qscale:a", "4", mp3_path],
        capture_output=True
    )
    os.remove(webm_path)
    if result.returncode != 0:
        return jsonify(error="ffmpeg conversion failed"), 500

    rec = Recording(name=name, filename=f"{uid}.mp3")
    db.session.add(rec)
    db.session.commit()
    return jsonify(id=rec.id, name=rec.name, filename=rec.filename)


@app.route("/recordings/<int:id>/delete", methods=["POST"])
@login_required
def recording_delete(id):
    rec = db.session.get(Recording, id)
    if rec:
        path = os.path.join(app.config["UPLOAD_FOLDER"], rec.filename)
        if os.path.exists(path):
            os.remove(path)
        db.session.delete(rec)
        db.session.commit()
        flash("Recording deleted.")
    return redirect(url_for("recordings_page"))


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


@app.route("/meetings", methods=["GET", "POST"])
@login_required
def meetings_page():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        date_str = request.form.get("meeting_date", "")
        notes = request.form.get("notes", "")
        if title and date_str:
            meeting_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            db.session.add(Meeting(title=title, meeting_date=meeting_date, notes=notes))
            db.session.commit()
            flash("Meeting created.")
        return redirect(url_for("meetings_page"))
    meetings = Meeting.query.order_by(Meeting.meeting_date.desc()).all()
    return render_template("meetings.html", meetings=meetings)


@app.route("/meetings/<int:id>/delete", methods=["POST"])
@login_required
def meeting_delete(id):
    m = db.session.get(Meeting, id)
    if m:
        db.session.delete(m)
        db.session.commit()
        flash("Deleted.")
    return redirect(url_for("meetings_page"))


@app.route("/send", methods=["GET", "POST"])
@login_required
def send_page():
    if request.method == "POST":
        meeting_id = request.form.get("meeting_id", type=int)
        recording_id = request.form.get("recording_id", type=int)
        if meeting_id and recording_id:
            from caller import send_reminders
            send_reminders(app, meeting_id, recording_id)
            flash("Calls are being sent.")
        return redirect(url_for("send_page"))

    meetings = Meeting.query.order_by(Meeting.meeting_date.desc()).all()
    recordings = Recording.query.order_by(Recording.created_at.desc()).all()
    return render_template("send.html", meetings=meetings, recordings=recordings)


@app.route("/api/send-progress")
@login_required
def send_progress():
    meeting_id = request.args.get("meeting_id", type=int)
    if not meeting_id:
        return jsonify(error="missing meeting_id"), 400
    logs = CallLog.query.filter_by(meeting_id=meeting_id).all()
    total = len(logs)
    completed = sum(1 for l in logs if l.status == "completed")
    failed = sum(1 for l in logs if l.status in ("failed", "busy", "no-answer", "canceled"))
    queued = total - completed - failed
    rows = [
        {"member": l.member.name, "phone": l.member.phone, "status": l.status}
        for l in logs
    ]
    return jsonify(total=total, completed=completed, failed=failed, queued=queued, rows=rows)


@app.route("/log")
@login_required
def call_log_page():
    meeting_id = request.args.get("meeting_id", type=int)
    q = CallLog.query
    if meeting_id:
        q = q.filter_by(meeting_id=meeting_id)
    logs = q.order_by(CallLog.initiated_at.desc()).all()
    meetings = Meeting.query.order_by(Meeting.meeting_date.desc()).all()
    return render_template("call_log.html", logs=logs, meetings=meetings, selected_meeting=meeting_id)


# --- Twilio endpoints ---

@app.route("/twiml", methods=["GET", "POST"])
def twiml():
    recording_id = request.args.get("recording_id", type=int)
    rec = db.session.get(Recording, recording_id) if recording_id else None
    resp = VoiceResponse()
    if rec:
        domain = os.environ.get("DOMAIN", request.host)
        scheme = "https" if "localhost" not in domain else "http"
        resp.play(f"{scheme}://{domain}/uploads/{rec.filename}")
    else:
        resp.say("No recording found. Goodbye.")
    return Response(str(resp), mimetype="text/xml")


@app.route("/api/call-status", methods=["POST"])
def call_status():
    sid = request.form.get("CallSid")
    status = request.form.get("CallStatus")
    if sid and status:
        log = CallLog.query.filter_by(twilio_call_sid=sid).first()
        if log:
            log.status = status
            log.updated_at = datetime.now(timezone.utc)
            db.session.commit()
    return "", 204


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    domain = os.environ.get("DOMAIN", "")

    # Auto-start ngrok tunnel for local dev
    if not domain or domain.startswith("localhost"):
        try:
            from pyngrok import ngrok
            tunnel = ngrok.connect(port)
            public_url = tunnel.public_url.replace("http://", "https://")
            os.environ["DOMAIN"] = public_url.replace("https://", "")
            print(f" * ngrok tunnel: {public_url}")
        except Exception as e:
            print(f" * ngrok not available: {e}")
            print(" * Twilio callbacks won't work without a public URL")

    app.run(debug=True, port=port)
