import os
import tempfile
import pytest
import bcrypt
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Set up test DB before importing app
_test_db_fd, _test_db_path = tempfile.mkstemp(suffix=".db")
os.close(_test_db_fd)
os.environ["DATABASE_URL"] = f"sqlite:///{_test_db_path}"
os.environ["SECRET_KEY"] = "test-secret"

from httpx import ASGITransport, AsyncClient
from fastapi.testclient import TestClient
from database import engine, SessionLocal, get_db
from models import Base, Organization, User, Member, Recording, Meeting, CallLog
from auth import create_access_token
from app import app


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    os.unlink(_test_db_path)


@pytest.fixture(autouse=True)
def clean_db():
    yield
    db = SessionLocal()
    try:
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(table.delete())
        db.commit()
    finally:
        db.close()


@pytest.fixture
def db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client():
    return TestClient(app)


def _make_user(email, org_name, slug):
    db = SessionLocal()
    org = Organization(name=org_name, slug=slug)
    db.add(org)
    db.flush()
    pw = bcrypt.hashpw(b"password123", bcrypt.gensalt()).decode()
    user = User(org_id=org.id, email=email, password_hash=pw, role="owner")
    db.add(user)
    db.commit()
    org_id, user_id = org.id, user.id
    db.close()
    return org_id, user_id


def _auth_cookies(user_id, org_id):
    token = create_access_token(user_id, org_id)
    return {"access_token": token}


@pytest.fixture
def auth_client():
    org_id, user_id = _make_user("test@example.com", "Test Org", "test-org")
    c = TestClient(app, cookies=_auth_cookies(user_id, org_id))
    c._org_id = org_id
    c._user_id = user_id
    return c


@pytest.fixture
def second_org():
    org_id, user_id = _make_user("other@example.com", "Other Org", "other-org")
    return {"org_id": org_id, "user_id": user_id, "email": "other@example.com"}


@pytest.fixture
def second_client(second_org):
    c = TestClient(app, cookies=_auth_cookies(second_org["user_id"], second_org["org_id"]))
    c._org_id = second_org["org_id"]
    return c


def make_member(org_id, name="John Doe", phone="+15551234567"):
    db = SessionLocal()
    m = Member(org_id=org_id, name=name, phone=phone)
    db.add(m)
    db.commit()
    db.refresh(m)
    m_id = m.id
    db.close()
    return m_id


def make_recording(org_id, name="Test Rec", filename="1/test.mp3"):
    db = SessionLocal()
    r = Recording(org_id=org_id, name=name, filename=filename)
    db.add(r)
    db.commit()
    db.refresh(r)
    r_id = r.id
    db.close()
    return r_id


def make_meeting(org_id, title="Test Meeting", member_ids=None):
    db = SessionLocal()
    m = Meeting(org_id=org_id, title=title, meeting_date=date(2025, 6, 15))
    if member_ids:
        members = db.query(Member).filter(Member.id.in_(member_ids)).all()
        m.members = members
    db.add(m)
    db.commit()
    db.refresh(m)
    m_id = m.id
    db.close()
    return m_id
