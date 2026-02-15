import os
import csv
import re
import uuid
import subprocess
import io
import click
from datetime import datetime, timezone

import bcrypt
from flask import (
    Flask, render_template, request, redirect, url_for, jsonify,
    Response, send_from_directory, flash
)
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from dotenv import load_dotenv
from twilio.twiml.voice_response import VoiceResponse

load_dotenv()

app = Flask(__name__)
db_path = os.path.join(os.path.dirname(__file__), "rcba.db")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-me-in-production")
app.config["UPLOAD_FOLDER"] = os.path.join(os.path.dirname(__file__), "uploads")

from models import db, Organization, User, Member, Recording, Meeting, CallLog

db.init_app(app)

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.init_app(app)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


with app.app_context():
    db.create_all()


def _slugify(name):
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "org"


def _org_upload_dir(org_id):
    path = os.path.join(app.config["UPLOAD_FOLDER"], str(org_id))
    os.makedirs(path, exist_ok=True)
    return path


# --- CLI ---

@app.cli.command("create-superuser")
@click.option("--email", prompt=True)
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
@click.option("--org-name", prompt="Organization name")
def create_superuser(email, password, org_name):
    """Create a superuser account with a new organization."""
    if User.query.filter_by(email=email).first():
        click.echo(f"Error: user with email {email} already exists.")
        return

    slug = _slugify(org_name)
    base_slug = slug
    counter = 1
    while Organization.query.filter_by(slug=slug).first():
        slug = f"{base_slug}-{counter}"
        counter += 1

    org = Organization(name=org_name, slug=slug)
    db.session.add(org)
    db.session.flush()

    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    user = User(org_id=org.id, email=email, password_hash=pw_hash, role="superuser")
    db.session.add(user)
    db.session.commit()
    click.echo(f"Superuser {email} created (org: {org_name}, slug: {slug}).")


# --- Auth ---

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        org_name = request.form.get("org_name", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not org_name or not email or not password:
            flash("All fields are required.")
            return redirect(url_for("register"))

        if User.query.filter_by(email=email).first():
            flash("Email already registered.")
            return redirect(url_for("register"))

        slug = _slugify(org_name)
        base_slug = slug
        counter = 1
        while Organization.query.filter_by(slug=slug).first():
            slug = f"{base_slug}-{counter}"
            counter += 1

        org = Organization(name=org_name, slug=slug)
        db.session.add(org)
        db.session.flush()

        pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        user = User(org_id=org.id, email=email, password_hash=pw_hash, role="owner")
        db.session.add(user)
        db.session.commit()

        login_user(user)
        return redirect(url_for("members_page"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user and bcrypt.checkpw(password.encode(), user.password_hash.encode()):
            login_user(user)
            return redirect(url_for("members_page"))
        flash("Invalid email or password.")
    return render_template("login.html")


@app.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("login"))


# --- Pages ---

@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("members_page"))
    return render_template("landing.html")


@app.route("/members", methods=["GET", "POST"])
@login_required
def members_page():
    org_id = current_user.org_id
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
                        db.session.add(Member(org_id=org_id, name=name, phone=phone))
            db.session.commit()
            flash("CSV imported.")
            return redirect(url_for("members_page"))

        # Single add
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        if name and phone:
            db.session.add(Member(org_id=org_id, name=name, phone=phone))
            db.session.commit()
            flash("Member added.")
        return redirect(url_for("members_page"))

    members = Member.query.filter_by(org_id=org_id).order_by(Member.name).all()
    return render_template("members.html", members=members)


@app.route("/members/<int:id>/edit", methods=["POST"])
@login_required
def member_edit(id):
    m = Member.query.filter_by(id=id, org_id=current_user.org_id).first()
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
    m = Member.query.filter_by(id=id, org_id=current_user.org_id).first()
    if m:
        db.session.delete(m)
        db.session.commit()
        flash("Deleted.")
    return redirect(url_for("members_page"))


@app.route("/recordings")
@login_required
def recordings_page():
    recs = Recording.query.filter_by(org_id=current_user.org_id).order_by(Recording.created_at.desc()).all()
    return render_template("recordings.html", recordings=recs)


@app.route("/api/recordings", methods=["POST"])
@login_required
def upload_recording():
    name = request.form.get("name", "").strip() or "Untitled"
    f = request.files.get("audio")
    if not f:
        return jsonify(error="No audio file"), 400

    org_id = current_user.org_id
    upload_dir = _org_upload_dir(org_id)
    uid = uuid.uuid4().hex[:10]
    webm_path = os.path.join(upload_dir, f"{uid}.webm")
    mp3_path = os.path.join(upload_dir, f"{uid}.mp3")
    f.save(webm_path)

    # Convert to MP3
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", webm_path, "-codec:a", "libmp3lame", "-qscale:a", "4", mp3_path],
        capture_output=True
    )
    os.remove(webm_path)
    if result.returncode != 0:
        return jsonify(error="ffmpeg conversion failed"), 500

    rec = Recording(org_id=org_id, name=name, filename=f"{org_id}/{uid}.mp3")
    db.session.add(rec)
    db.session.commit()
    return jsonify(id=rec.id, name=rec.name, filename=rec.filename)


@app.route("/recordings/<int:id>/delete", methods=["POST"])
@login_required
def recording_delete(id):
    rec = Recording.query.filter_by(id=id, org_id=current_user.org_id).first()
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
    org_id = current_user.org_id
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        date_str = request.form.get("meeting_date", "")
        notes = request.form.get("notes", "")
        if title and date_str:
            meeting_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            db.session.add(Meeting(org_id=org_id, title=title, meeting_date=meeting_date, notes=notes))
            db.session.commit()
            flash("Meeting created.")
        return redirect(url_for("meetings_page"))
    meetings = Meeting.query.filter_by(org_id=org_id).order_by(Meeting.meeting_date.desc()).all()
    return render_template("meetings.html", meetings=meetings)


@app.route("/meetings/<int:id>")
@login_required
def meeting_detail(id):
    org_id = current_user.org_id
    meeting = Meeting.query.filter_by(id=id, org_id=org_id).first()
    if not meeting:
        flash("Not found.")
        return redirect(url_for("meetings_page"))
    all_members = Member.query.filter_by(org_id=org_id, active=True).order_by(Member.name).all()
    return render_template("meeting_detail.html", meeting=meeting, all_members=all_members)


@app.route("/meetings/<int:id>/members", methods=["POST"])
@login_required
def meeting_members_update(id):
    org_id = current_user.org_id
    meeting = Meeting.query.filter_by(id=id, org_id=org_id).first()
    if not meeting:
        flash("Not found.")
        return redirect(url_for("meetings_page"))
    selected_ids = request.form.getlist("member_ids", type=int)
    members = Member.query.filter(Member.id.in_(selected_ids), Member.org_id == org_id).all()
    meeting.members = members
    db.session.commit()
    flash("Meeting members updated.")
    next_page = request.args.get("next")
    if next_page == "send":
        return redirect(url_for("send_page",
                                meeting_id=request.args.get("meeting_id", ""),
                                recording_id=request.args.get("recording_id", "")))
    return redirect(url_for("meeting_detail", id=id))


@app.route("/meetings/<int:id>/delete", methods=["POST"])
@login_required
def meeting_delete(id):
    m = Meeting.query.filter_by(id=id, org_id=current_user.org_id).first()
    if m:
        db.session.delete(m)
        db.session.commit()
        flash("Deleted.")
    return redirect(url_for("meetings_page"))


@app.route("/send", methods=["GET", "POST"])
@login_required
def send_page():
    org_id = current_user.org_id
    if request.method == "POST":
        meeting_id = request.form.get("meeting_id", type=int)
        recording_id = request.form.get("recording_id", type=int)
        if meeting_id and recording_id:
            # Verify resources belong to this org
            meeting = Meeting.query.filter_by(id=meeting_id, org_id=org_id).first()
            recording = Recording.query.filter_by(id=recording_id, org_id=org_id).first()
            if meeting and recording:
                from caller import send_reminders
                send_reminders(app, meeting_id, recording_id, org_id)
                flash("Calls are being sent.")
        return redirect(url_for("send_page"))

    meetings = Meeting.query.filter_by(org_id=org_id).order_by(Meeting.meeting_date.desc()).all()
    recordings = Recording.query.filter_by(org_id=org_id).order_by(Recording.created_at.desc()).all()
    sel_meeting = request.args.get("meeting_id", 0, type=int)
    sel_recording = request.args.get("recording_id", 0, type=int)
    return render_template("send.html", meetings=meetings, recordings=recordings,
                           sel_meeting=sel_meeting, sel_recording=sel_recording)


@app.route("/api/meeting-members")
@login_required
def api_meeting_members():
    meeting_id = request.args.get("meeting_id", type=int)
    if not meeting_id:
        return jsonify(members=[])
    meeting = Meeting.query.filter_by(id=meeting_id, org_id=current_user.org_id).first()
    if not meeting:
        return jsonify(members=[])
    members = [{"name": m.name, "phone": m.phone} for m in meeting.members if m.active]
    return jsonify(members=members)


@app.route("/api/send-progress")
@login_required
def send_progress():
    meeting_id = request.args.get("meeting_id", type=int)
    if not meeting_id:
        return jsonify(error="missing meeting_id"), 400
    logs = CallLog.query.filter_by(meeting_id=meeting_id, org_id=current_user.org_id).all()
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
    org_id = current_user.org_id
    meeting_id = request.args.get("meeting_id", type=int)
    q = CallLog.query.filter_by(org_id=org_id)
    if meeting_id:
        q = q.filter_by(meeting_id=meeting_id)
    logs = q.order_by(CallLog.initiated_at.desc()).all()
    meetings = Meeting.query.filter_by(org_id=org_id).order_by(Meeting.meeting_date.desc()).all()
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
