from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Date, Text, ForeignKey, Table
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Organization(Base):
    __tablename__ = "organization"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    slug = Column(String(120), unique=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    users = relationship("User", backref="organization", lazy=True)


class User(Base):
    __tablename__ = "user"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organization.id"), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="owner")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


meeting_members = Table(
    "meeting_members",
    Base.metadata,
    Column("meeting_id", Integer, ForeignKey("meeting.id"), primary_key=True),
    Column("member_id", Integer, ForeignKey("member.id"), primary_key=True),
)


class Member(Base):
    __tablename__ = "member"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organization.id"), nullable=False)
    name = Column(String(120), nullable=False)
    phone = Column(String(20), nullable=False)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Recording(Base):
    __tablename__ = "recording"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organization.id"), nullable=False)
    name = Column(String(120), nullable=False)
    filename = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Meeting(Base):
    __tablename__ = "meeting"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organization.id"), nullable=False)
    title = Column(String(200), nullable=False)
    meeting_date = Column(Date, nullable=False)
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    members = relationship("Member", secondary=meeting_members, backref="meetings", lazy=True)


class CallLog(Base):
    __tablename__ = "call_log"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organization.id"), nullable=False)
    meeting_id = Column(Integer, ForeignKey("meeting.id"), nullable=False)
    recording_id = Column(Integer, ForeignKey("recording.id"), nullable=False)
    member_id = Column(Integer, ForeignKey("member.id"), nullable=False)
    twilio_call_sid = Column(String(40))
    status = Column(String(20), default="queued")
    initiated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    meeting = relationship("Meeting", backref="call_logs")
    recording = relationship("Recording")
    member = relationship("Member")
