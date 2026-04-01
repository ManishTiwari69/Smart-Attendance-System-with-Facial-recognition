"""
backend/models/database.py
─────────────────────────────────────────────────────────────────────────────
Complete SQLAlchemy ORM models for SmartHospital HMS.

Tables:
    users               – All system actors (Admin, Doctor, SuperDoctor, Staff, Patient)
    face_embeddings     – FaceNet 512-d embedding vectors, one-to-many per user
    patient_profiles    – Extended clinical info linked to a user
    allergies           – Patient allergy records
    conditions          – Patient conditions / diagnoses
    medications         – Prescribed medications
    medical_timeline    – Immutable clinical event log
    reports             – Diagnostic report requests and results
    billing             – Invoices linked to patients
    billing_items       – Line items per invoice
    doctor_assignments  – Links doctors to patients (many-to-many)
    audit_logs          – Immutable security / access audit trail
    sessions            – JWT refresh token store
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Enum, Float, ForeignKey,
    Index, Integer, LargeBinary, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.types import TypeDecorator, CHAR
import json


# ─── Custom Types ─────────────────────────────────────────────────────────────

class GUID(TypeDecorator):
    """Platform-independent UUID: uses PostgreSQL's native UUID,
    falls back to CHAR(36) for SQLite."""
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID())
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == "postgresql":
            return str(value)
        if not isinstance(value, uuid.UUID):
            return str(uuid.UUID(value))
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        return uuid.UUID(str(value))


class JSONList(TypeDecorator):
    """Stores a Python list as a JSON string (for SQLite compatibility)."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return json.dumps(value) if value is not None else "[]"

    def process_result_value(self, value, dialect):
        return json.loads(value) if value else []


# ─── Enums ────────────────────────────────────────────────────────────────────

class UserRole(str, enum.Enum):
    ADMIN        = "admin"
    DOCTOR       = "doctor"
    SUPER_DOCTOR = "superDoctor"
    STAFF        = "staff"
    PATIENT      = "patient"


class EventType(str, enum.Enum):
    VISIT        = "visit"
    REPORT       = "report"
    PRESCRIPTION = "prescription"
    EMERGENCY    = "emergency"
    NOTE         = "note"


class ReportStatus(str, enum.Enum):
    REQUESTED  = "requested"
    IN_PROGRESS = "in_progress"
    COMPLETED  = "completed"
    CANCELLED  = "cancelled"


class BillingStatus(str, enum.Enum):
    DRAFT   = "draft"
    PENDING = "pending"
    PAID    = "paid"
    OVERDUE = "overdue"
    VOID    = "void"


class AuditAction(str, enum.Enum):
    LOGIN_SUCCESS       = "LOGIN_SUCCESS"
    LOGIN_FAILED        = "LOGIN_FAILED"
    FACE_AUTH_SUCCESS   = "FACE_AUTH_SUCCESS"
    FACE_AUTH_FAILED    = "FACE_AUTH_FAILED"
    PIN_AUTH_SUCCESS    = "PIN_AUTH_SUCCESS"
    PIN_AUTH_FAILED     = "PIN_AUTH_FAILED"
    EMERGENCY_OVERRIDE  = "EMERGENCY_OVERRIDE"
    PATIENT_VIEW        = "PATIENT_VIEW"
    PRESCRIPTION_CREATE = "PRESCRIPTION_CREATE"
    REPORT_REQUEST      = "REPORT_REQUEST"
    REPORT_UPLOAD       = "REPORT_UPLOAD"
    BILLING_CREATE      = "BILLING_CREATE"
    BILLING_PAYMENT     = "BILLING_PAYMENT"
    USER_CREATE         = "USER_CREATE"
    USER_UPDATE         = "USER_UPDATE"
    USER_DELETE         = "USER_DELETE"
    FACE_ENROLL         = "FACE_ENROLL"
    LOGOUT              = "LOGOUT"


# ─── Base ─────────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


def utcnow():
    return datetime.now(timezone.utc)


# ─── Users ────────────────────────────────────────────────────────────────────

class User(Base):
    """
    Central actor table. Roles determine which dashboards / routes are accessible.

    face_embeddings  – list of enrolled FaceNet vectors for this user
    pin_hash         – bcrypt hash of the 4-digit PIN (doctors / patients)
    is_active        – soft-delete / suspension flag
    failed_pin_count – increments on bad PIN; triggers lockout at threshold
    locked_until     – datetime after which lockout expires
    """
    __tablename__ = "users"

    id           = Column(GUID, primary_key=True, default=uuid.uuid4)
    role         = Column(Enum(UserRole), nullable=False)
    first_name   = Column(String(100), nullable=False)
    last_name    = Column(String(100), nullable=False)
    email        = Column(String(255), unique=True, nullable=False)
    phone        = Column(String(30), unique=True, nullable=True)
    pin_hash     = Column(String(255), nullable=True)   # bcrypt
    is_active    = Column(Boolean, default=True, nullable=False)
    failed_pin_count = Column(Integer, default=0, nullable=False)
    locked_until     = Column(DateTime(timezone=True), nullable=True)
    created_at   = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at   = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # Relationships
    face_embeddings  = relationship("FaceEmbedding", back_populates="user",
                                    cascade="all, delete-orphan")
    patient_profile  = relationship("PatientProfile", back_populates="user",
                                    uselist=False, cascade="all, delete-orphan")
    audit_logs       = relationship("AuditLog", back_populates="actor",
                                    foreign_keys="AuditLog.actor_id")
    sessions         = relationship("UserSession", back_populates="user",
                                    cascade="all, delete-orphan")
    doctor_patients  = relationship("DoctorAssignment", back_populates="doctor",
                                    foreign_keys="DoctorAssignment.doctor_id")

    __table_args__ = (
        Index("ix_users_email", "email"),
        Index("ix_users_role", "role"),
    )

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    def __repr__(self):
        return f"<User {self.full_name!r} role={self.role.value}>"


# ─── Face Embeddings ──────────────────────────────────────────────────────────

class FaceEmbedding(Base):
    """
    Stores a FaceNet (InceptionResnetV1) 512-dimensional float32 embedding
    as raw bytes (LargeBinary).

    Multiple embeddings per user are averaged during verification to improve
    robustness (different lighting, angles, glasses, etc.).

    embedding_bytes:  numpy float32 array serialised with numpy.tobytes()
                      Deserialise: np.frombuffer(row.embedding_bytes, dtype=np.float32)
    quality_score:    MTCNN detection confidence at enrolment time (0–1)
    is_primary:       The canonical embedding used for quick single-comparison
    """
    __tablename__ = "face_embeddings"

    id              = Column(GUID, primary_key=True, default=uuid.uuid4)
    user_id         = Column(GUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    embedding_bytes = Column(LargeBinary, nullable=False)   # 512 * 4 = 2048 bytes
    quality_score   = Column(Float, nullable=True)           # MTCNN probability
    is_primary      = Column(Boolean, default=False)
    label           = Column(String(50), nullable=True)       # e.g. "glasses", "front", "angle45"
    created_at      = Column(DateTime(timezone=True), default=utcnow)

    user = relationship("User", back_populates="face_embeddings")

    __table_args__ = (
        Index("ix_face_embeddings_user_id", "user_id"),
    )

    def __repr__(self):
        return f"<FaceEmbedding user={self.user_id} primary={self.is_primary}>"


# ─── Patient Profiles ─────────────────────────────────────────────────────────

class PatientProfile(Base):
    """
    Extended clinical data for users with role=PATIENT.
    One-to-one with User via user_id.
    """
    __tablename__ = "patient_profiles"

    id          = Column(GUID, primary_key=True, default=uuid.uuid4)
    user_id     = Column(GUID, ForeignKey("users.id", ondelete="CASCADE"),
                         unique=True, nullable=False)
    patient_number = Column(String(20), unique=True, nullable=False)  # e.g. "P-0042"
    date_of_birth  = Column(DateTime, nullable=True)
    gender         = Column(String(20), nullable=True)
    blood_type     = Column(String(5), nullable=True)
    address        = Column(Text, nullable=True)
    emergency_contact_name  = Column(String(150), nullable=True)
    emergency_contact_phone = Column(String(30), nullable=True)
    insurance_provider      = Column(String(100), nullable=True)
    insurance_policy_number = Column(String(100), nullable=True)
    notes          = Column(Text, nullable=True)
    created_at     = Column(DateTime(timezone=True), default=utcnow)
    updated_at     = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # Relationships
    user         = relationship("User", back_populates="patient_profile")
    allergies    = relationship("Allergy", back_populates="patient",
                                cascade="all, delete-orphan")
    conditions   = relationship("Condition", back_populates="patient",
                                cascade="all, delete-orphan")
    medications  = relationship("Medication", back_populates="patient",
                                cascade="all, delete-orphan")
    timeline     = relationship("MedicalTimelineEvent", back_populates="patient",
                                cascade="all, delete-orphan",
                                order_by="MedicalTimelineEvent.event_date.desc()")
    reports      = relationship("MedicalReport", back_populates="patient",
                                cascade="all, delete-orphan")
    billing      = relationship("Invoice", back_populates="patient",
                                cascade="all, delete-orphan")
    doctor_assignments = relationship("DoctorAssignment", back_populates="patient")

    __table_args__ = (
        Index("ix_patient_profiles_patient_number", "patient_number"),
    )

    @property
    def age(self):
        if self.date_of_birth:
            today = datetime.now()
            return today.year - self.date_of_birth.year - (
                (today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day)
            )
        return None

    def __repr__(self):
        return f"<PatientProfile {self.patient_number}>"


# ─── Allergies ────────────────────────────────────────────────────────────────

class Allergy(Base):
    __tablename__ = "allergies"

    id          = Column(GUID, primary_key=True, default=uuid.uuid4)
    patient_id  = Column(GUID, ForeignKey("patient_profiles.id", ondelete="CASCADE"), nullable=False)
    allergen    = Column(String(200), nullable=False)
    severity    = Column(String(20), nullable=True)   # mild / moderate / severe / life-threatening
    reaction    = Column(String(300), nullable=True)
    verified_by = Column(String(150), nullable=True)   # doctor who confirmed
    noted_at    = Column(DateTime(timezone=True), default=utcnow)

    patient = relationship("PatientProfile", back_populates="allergies")


# ─── Conditions ───────────────────────────────────────────────────────────────

class Condition(Base):
    __tablename__ = "conditions"

    id          = Column(GUID, primary_key=True, default=uuid.uuid4)
    patient_id  = Column(GUID, ForeignKey("patient_profiles.id", ondelete="CASCADE"), nullable=False)
    name        = Column(String(300), nullable=False)
    icd10_code  = Column(String(20), nullable=True)
    status      = Column(String(30), default="active")  # active / resolved / chronic
    diagnosed_at = Column(DateTime, nullable=True)
    resolved_at  = Column(DateTime, nullable=True)
    notes       = Column(Text, nullable=True)

    patient = relationship("PatientProfile", back_populates="conditions")


# ─── Medications ──────────────────────────────────────────────────────────────

class Medication(Base):
    __tablename__ = "medications"

    id             = Column(GUID, primary_key=True, default=uuid.uuid4)
    patient_id     = Column(GUID, ForeignKey("patient_profiles.id", ondelete="CASCADE"), nullable=False)
    prescribed_by  = Column(GUID, ForeignKey("users.id"), nullable=True)
    name           = Column(String(200), nullable=False)
    dosage         = Column(String(100), nullable=True)     # e.g. "500mg"
    frequency      = Column(String(100), nullable=True)     # e.g. "Twice daily"
    route          = Column(String(50), nullable=True)      # oral / IV / topical
    start_date     = Column(DateTime, nullable=True)
    end_date       = Column(DateTime, nullable=True)
    is_active      = Column(Boolean, default=True)
    notes          = Column(Text, nullable=True)
    created_at     = Column(DateTime(timezone=True), default=utcnow)

    patient     = relationship("PatientProfile", back_populates="medications")
    prescriber  = relationship("User", foreign_keys=[prescribed_by])


# ─── Medical Timeline Events ──────────────────────────────────────────────────

class MedicalTimelineEvent(Base):
    """
    Immutable event log — records are never updated, only appended.
    Covers visits, prescriptions, emergencies, report results, notes.
    """
    __tablename__ = "medical_timeline"

    id            = Column(GUID, primary_key=True, default=uuid.uuid4)
    patient_id    = Column(GUID, ForeignKey("patient_profiles.id", ondelete="CASCADE"), nullable=False)
    actor_id      = Column(GUID, ForeignKey("users.id"), nullable=True)   # doctor/staff who created
    event_type    = Column(Enum(EventType), nullable=False)
    event_date    = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    title         = Column(String(300), nullable=False)
    description   = Column(Text, nullable=True)
    metadata_json = Column(Text, nullable=True)    # arbitrary JSON for event-specific data

    patient = relationship("PatientProfile", back_populates="timeline")
    actor   = relationship("User", foreign_keys=[actor_id])

    __table_args__ = (
        Index("ix_timeline_patient_date", "patient_id", "event_date"),
    )


# ─── Medical Reports ──────────────────────────────────────────────────────────

class MedicalReport(Base):
    """
    Lifecycle: Doctor requests → Staff uploads → Doctor notified → Completed.
    file_path: server-side path to uploaded file (PDF/image).
    """
    __tablename__ = "medical_reports"

    id             = Column(GUID, primary_key=True, default=uuid.uuid4)
    patient_id     = Column(GUID, ForeignKey("patient_profiles.id", ondelete="CASCADE"), nullable=False)
    requested_by   = Column(GUID, ForeignKey("users.id"), nullable=True)
    uploaded_by    = Column(GUID, ForeignKey("users.id"), nullable=True)
    report_number  = Column(String(30), unique=True, nullable=False)   # e.g. "R-1001"
    name           = Column(String(300), nullable=False)
    category       = Column(String(100), nullable=True)   # radiology / pathology / cardiology
    status         = Column(Enum(ReportStatus), default=ReportStatus.REQUESTED)
    file_path      = Column(String(500), nullable=True)
    file_mime_type = Column(String(100), nullable=True)
    notes          = Column(Text, nullable=True)
    requested_at   = Column(DateTime(timezone=True), default=utcnow)
    completed_at   = Column(DateTime(timezone=True), nullable=True)

    patient   = relationship("PatientProfile", back_populates="reports")
    requester = relationship("User", foreign_keys=[requested_by])
    uploader  = relationship("User", foreign_keys=[uploaded_by])

    __table_args__ = (
        Index("ix_reports_patient_status", "patient_id", "status"),
    )


# ─── Billing / Invoices ───────────────────────────────────────────────────────

class Invoice(Base):
    __tablename__ = "invoices"

    id              = Column(GUID, primary_key=True, default=uuid.uuid4)
    patient_id      = Column(GUID, ForeignKey("patient_profiles.id", ondelete="CASCADE"), nullable=False)
    created_by      = Column(GUID, ForeignKey("users.id"), nullable=True)
    invoice_number  = Column(String(30), unique=True, nullable=False)   # e.g. "INV-5001"
    status          = Column(Enum(BillingStatus), default=BillingStatus.PENDING)
    subtotal        = Column(Numeric(12, 2), default=0)
    tax             = Column(Numeric(12, 2), default=0)
    total           = Column(Numeric(12, 2), default=0)
    paid_at         = Column(DateTime(timezone=True), nullable=True)
    payment_method  = Column(String(50), nullable=True)    # card / cash / insurance
    payment_ref     = Column(String(200), nullable=True)   # transaction ID
    notes           = Column(Text, nullable=True)
    due_date        = Column(DateTime, nullable=True)
    created_at      = Column(DateTime(timezone=True), default=utcnow)
    updated_at      = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    patient    = relationship("PatientProfile", back_populates="billing")
    creator    = relationship("User", foreign_keys=[created_by])
    line_items = relationship("InvoiceLineItem", back_populates="invoice",
                              cascade="all, delete-orphan")


class InvoiceLineItem(Base):
    __tablename__ = "invoice_line_items"

    id          = Column(GUID, primary_key=True, default=uuid.uuid4)
    invoice_id  = Column(GUID, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False)
    description = Column(String(300), nullable=False)
    quantity    = Column(Integer, default=1)
    unit_price  = Column(Numeric(10, 2), nullable=False)
    total       = Column(Numeric(10, 2), nullable=False)

    invoice = relationship("Invoice", back_populates="line_items")


# ─── Doctor–Patient Assignments ───────────────────────────────────────────────

class DoctorAssignment(Base):
    """
    Manages which doctor(s) are assigned to each patient.
    A patient can have a primary + specialist doctors.
    """
    __tablename__ = "doctor_assignments"

    id          = Column(GUID, primary_key=True, default=uuid.uuid4)
    doctor_id   = Column(GUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    patient_id  = Column(GUID, ForeignKey("patient_profiles.id", ondelete="CASCADE"), nullable=False)
    is_primary  = Column(Boolean, default=False)
    assigned_at = Column(DateTime(timezone=True), default=utcnow)
    assigned_by = Column(GUID, ForeignKey("users.id"), nullable=True)   # staff who assigned

    doctor  = relationship("User", back_populates="doctor_patients",
                           foreign_keys=[doctor_id])
    patient = relationship("PatientProfile", back_populates="doctor_assignments")

    __table_args__ = (
        UniqueConstraint("doctor_id", "patient_id", name="uq_doctor_patient"),
    )


# ─── Sessions (Refresh Token Store) ──────────────────────────────────────────

class UserSession(Base):
    __tablename__ = "user_sessions"

    id            = Column(GUID, primary_key=True, default=uuid.uuid4)
    user_id       = Column(GUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    refresh_token = Column(String(512), unique=True, nullable=False)
    ip_address    = Column(String(50), nullable=True)
    user_agent    = Column(String(300), nullable=True)
    is_revoked    = Column(Boolean, default=False)
    created_at    = Column(DateTime(timezone=True), default=utcnow)
    expires_at    = Column(DateTime(timezone=True), nullable=False)

    user = relationship("User", back_populates="sessions")


# ─── Audit Logs ───────────────────────────────────────────────────────────────

class AuditLog(Base):
    """
    Append-only security / compliance log. Never updated or deleted.
    Captures every sensitive action with actor, target, IP, and result.
    """
    __tablename__ = "audit_logs"

    id           = Column(GUID, primary_key=True, default=uuid.uuid4)
    actor_id     = Column(GUID, ForeignKey("users.id"), nullable=True)  # null for anonymous
    action       = Column(Enum(AuditAction), nullable=False)
    target_type  = Column(String(50), nullable=True)   # "patient", "report", "invoice", …
    target_id    = Column(String(50), nullable=True)   # ID of the affected resource
    ip_address   = Column(String(50), nullable=True)
    user_agent   = Column(String(300), nullable=True)
    success      = Column(Boolean, nullable=False)
    detail       = Column(Text, nullable=True)         # JSON or human-readable context
    created_at   = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    actor = relationship("User", back_populates="audit_logs",
                         foreign_keys=[actor_id])

    __table_args__ = (
        Index("ix_audit_actor_date", "actor_id", "created_at"),
        Index("ix_audit_action_date", "action", "created_at"),
    )
