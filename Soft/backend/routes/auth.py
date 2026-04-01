"""
backend/services/auth.py
─────────────────────────────────────────────────────────────────────────────
Authentication service:
    • JWT access + refresh token lifecycle
    • PIN verification with bcrypt + lockout
    • Face auth orchestration (calls face_recognition service)
    • Emergency override logic (SuperDoctor bypass)
    • Audit logging for every auth event
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from sqlalchemy.orm import Session

from backend.models.database import (
    AuditAction, AuditLog, FaceEmbedding, User, UserRole, UserSession,
)
from backend.services.face_recognition import verify_face

logger = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────

JWT_SECRET          = os.getenv("JWT_SECRET_KEY", "dev-secret-change-me")
JWT_ALGORITHM       = "HS256"
ACCESS_EXPIRES_MIN  = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRES_MINUTES", 60))
REFRESH_EXPIRES_DAYS = int(os.getenv("JWT_REFRESH_TOKEN_EXPIRES_DAYS", 7))
MAX_PIN_ATTEMPTS    = int(os.getenv("RATE_LIMIT_PIN", 5))
PIN_LOCKOUT_MIN     = int(os.getenv("PIN_LOCKOUT_MINUTES", 15))
BCRYPT_ROUNDS       = int(os.getenv("BCRYPT_ROUNDS", 12))


# ─── PIN Utilities ────────────────────────────────────────────────────────────

def hash_pin(pin: str) -> str:
    """Hash a PIN with bcrypt."""
    return bcrypt.hashpw(pin.encode(), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode()


def check_pin(pin: str, pin_hash: str) -> bool:
    """Verify a PIN against its bcrypt hash."""
    return bcrypt.checkpw(pin.encode(), pin_hash.encode())


# ─── JWT Utilities ────────────────────────────────────────────────────────────

def create_access_token(user: User) -> str:
    payload = {
        "sub":   str(user.id),
        "role":  user.role.value,
        "name":  user.full_name,
        "iat":   datetime.now(timezone.utc),
        "exp":   datetime.now(timezone.utc) + timedelta(minutes=ACCESS_EXPIRES_MIN),
        "jti":   str(uuid.uuid4()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_refresh_token() -> str:
    return secrets.token_urlsafe(64)


def decode_access_token(token: str) -> dict:
    """Decode and validate JWT. Raises jwt.ExpiredSignatureError / jwt.InvalidTokenError."""
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


# ─── Audit Helper ─────────────────────────────────────────────────────────────

def _log(
    db: Session,
    action: AuditAction,
    success: bool,
    actor_id: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    ip: Optional[str] = None,
    detail: Optional[dict] = None,
):
    db.add(AuditLog(
        actor_id=actor_id,
        action=action,
        success=success,
        target_type=target_type,
        target_id=target_id,
        ip_address=ip,
        detail=json.dumps(detail) if detail else None,
    ))
    # No commit here – caller manages transaction


# ─── Face Authentication ──────────────────────────────────────────────────────

class FaceAuthResult:
    def __init__(self, success: bool, user: Optional[User], message: str,
                 similarity: float = 0.0):
        self.success    = success
        self.user       = user
        self.message    = message
        self.similarity = similarity


def authenticate_face(
    db: Session,
    user_id: str,
    image_data: str,
    ip: Optional[str] = None,
) -> FaceAuthResult:
    """
    Verify a webcam image against the stored face embeddings for a given user.

    Steps:
        1. Load user + embeddings from DB
        2. Call face_recognition.verify_face
        3. Log result to audit_logs
        4. Return FaceAuthResult
    """
    user: Optional[User] = db.get(User, user_id)
    if not user or not user.is_active:
        _log(db, AuditAction.FACE_AUTH_FAILED, False, actor_id=user_id,
             ip=ip, detail={"reason": "user not found or inactive"})
        return FaceAuthResult(False, None, "User not found.")

    stored_raw = [fe.embedding_bytes for fe in user.face_embeddings]
    if not stored_raw:
        _log(db, AuditAction.FACE_AUTH_FAILED, False, actor_id=str(user.id),
             ip=ip, detail={"reason": "no face enrolled"})
        return FaceAuthResult(False, user, "No face enrolled for this account.")

    result = verify_face(image_data, stored_raw)

    _log(
        db,
        AuditAction.FACE_AUTH_SUCCESS if result.verified else AuditAction.FACE_AUTH_FAILED,
        result.verified,
        actor_id=str(user.id),
        ip=ip,
        detail={"similarity": result.similarity, "threshold": result.threshold},
    )
    db.commit()

    if result.verified:
        return FaceAuthResult(True, user, "Face verified.", result.similarity)
    return FaceAuthResult(
        False, user,
        f"Face not recognised (score {result.similarity:.2f}).",
        result.similarity,
    )


# ─── PIN Authentication ───────────────────────────────────────────────────────

class PinAuthResult:
    def __init__(self, success: bool, user: Optional[User], message: str,
                 locked: bool = False):
        self.success = success
        self.user    = user
        self.message = message
        self.locked  = locked


def authenticate_pin(
    db: Session,
    user_id: str,
    pin: str,
    ip: Optional[str] = None,
) -> PinAuthResult:
    """
    Verify PIN for a user who has already passed face auth.
    Implements lockout after MAX_PIN_ATTEMPTS failures.
    """
    user: Optional[User] = db.get(User, user_id)
    if not user or not user.is_active:
        return PinAuthResult(False, None, "User not found.")

    # Check lockout
    if user.locked_until and user.locked_until > datetime.now(timezone.utc):
        remaining = int((user.locked_until - datetime.now(timezone.utc)).total_seconds() / 60)
        return PinAuthResult(False, user,
                             f"Account locked. Try again in {remaining} minutes.",
                             locked=True)

    if not user.pin_hash:
        return PinAuthResult(False, user, "No PIN configured for this account.")

    success = check_pin(pin, user.pin_hash)

    if success:
        # Reset lockout counters
        user.failed_pin_count = 0
        user.locked_until = None
        _log(db, AuditAction.PIN_AUTH_SUCCESS, True, actor_id=str(user.id), ip=ip)
    else:
        user.failed_pin_count = (user.failed_pin_count or 0) + 1
        if user.failed_pin_count >= MAX_PIN_ATTEMPTS:
            user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=PIN_LOCKOUT_MIN)
        _log(db, AuditAction.PIN_AUTH_FAILED, False, actor_id=str(user.id), ip=ip,
             detail={"attempts": user.failed_pin_count})

    db.commit()

    if success:
        return PinAuthResult(True, user, "PIN verified.")
    remaining_attempts = max(0, MAX_PIN_ATTEMPTS - (user.failed_pin_count or 0))
    return PinAuthResult(False, user,
                         f"Incorrect PIN. {remaining_attempts} attempt(s) remaining.")


# ─── Full Login Flow ──────────────────────────────────────────────────────────

def complete_login(
    db: Session,
    user: User,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> dict:
    """
    Issue JWT access + refresh tokens after successful auth.
    Stores refresh token in user_sessions.
    Returns dict suitable for JSON response.
    """
    access_token  = create_access_token(user)
    refresh_token = create_refresh_token()

    session = UserSession(
        user_id=user.id,
        refresh_token=refresh_token,
        ip_address=ip,
        user_agent=user_agent,
        expires_at=datetime.now(timezone.utc) + timedelta(days=REFRESH_EXPIRES_DAYS),
    )
    db.add(session)
    _log(db, AuditAction.LOGIN_SUCCESS, True, actor_id=str(user.id), ip=ip)
    db.commit()

    return {
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "token_type":    "Bearer",
        "expires_in":    ACCESS_EXPIRES_MIN * 60,
        "user": {
            "id":        str(user.id),
            "name":      user.full_name,
            "role":      user.role.value,
            "email":     user.email,
        },
    }


def refresh_access_token(db: Session, refresh_token: str) -> Optional[dict]:
    """Exchange a valid refresh token for a new access token."""
    session: Optional[UserSession] = (
        db.query(UserSession)
        .filter_by(refresh_token=refresh_token, is_revoked=False)
        .first()
    )
    if not session or session.expires_at < datetime.now(timezone.utc):
        return None

    user = db.get(User, session.user_id)
    if not user or not user.is_active:
        return None

    return {"access_token": create_access_token(user), "token_type": "Bearer"}


def revoke_session(db: Session, refresh_token: str):
    """Revoke a refresh token (logout)."""
    session = db.query(UserSession).filter_by(refresh_token=refresh_token).first()
    if session:
        session.is_revoked = True
        db.commit()


# ─── SuperDoctor Emergency Override ──────────────────────────────────────────

class EmergencyLookupResult:
    def __init__(self, success: bool, patient_profile=None, message: str = ""):
        self.success         = success
        self.patient_profile = patient_profile
        self.message         = message


def emergency_patient_lookup(
    db: Session,
    actor: User,
    query: str,
    query_type: str,    # "patient_id" | "phone" | "face_id"
    image_data: Optional[str] = None,
    ip: Optional[str] = None,
) -> EmergencyLookupResult:
    """
    SuperDoctor emergency bypass: locate a patient by patient_number, phone, or face.
    All overrides are logged as EMERGENCY_OVERRIDE in the audit log.

    Args:
        actor:       The authenticated SuperDoctor.
        query:       Patient ID string or phone number.
        query_type:  "patient_id" | "phone" | "face_id"
        image_data:  Required when query_type == "face_id".
    """
    if actor.role != UserRole.SUPER_DOCTOR:
        return EmergencyLookupResult(False, message="Insufficient privileges.")

    from backend.models.database import PatientProfile

    patient_profile = None

    if query_type == "patient_id":
        patient_profile = (
            db.query(PatientProfile)
            .filter_by(patient_number=query.strip().upper())
            .first()
        )

    elif query_type == "phone":
        user = db.query(User).filter_by(phone=query.strip()).first()
        if user:
            patient_profile = user.patient_profile

    elif query_type == "face_id":
        if not image_data:
            return EmergencyLookupResult(False, message="Image required for face lookup.")
        # Iterate all patients and find the best match
        all_patients = db.query(PatientProfile).all()
        best_sim = 0.0
        for pp in all_patients:
            if pp.user and pp.user.face_embeddings:
                stored = [fe.embedding_bytes for fe in pp.user.face_embeddings]
                result = verify_face(image_data, stored)
                if result.verified and result.similarity > best_sim:
                    best_sim = result.similarity
                    patient_profile = pp

    _log(
        db, AuditAction.EMERGENCY_OVERRIDE,
        success=patient_profile is not None,
        actor_id=str(actor.id),
        target_type="patient",
        target_id=str(patient_profile.id) if patient_profile else None,
        ip=ip,
        detail={"query_type": query_type, "query": query},
    )
    db.commit()

    if patient_profile:
        return EmergencyLookupResult(True, patient_profile, "Patient found via emergency override.")
    return EmergencyLookupResult(False, message=f"No patient found for {query_type}={query!r}.")


# ─── Face Enrolment ───────────────────────────────────────────────────────────

def enroll_user_face(
    db: Session,
    user: User,
    images: list[str],
    actor_id: Optional[str] = None,
    ip: Optional[str] = None,
) -> dict:
    """
    Enrol one or more face images for a user.
    Calls face_recognition.enroll_faces, saves to FaceEmbedding table.

    Returns: {"enrolled": int, "warnings": [str]}
    """
    from backend.services.face_recognition import enroll_faces, save_face_crop, detect_and_embed

    max_images = int(os.getenv("MAX_FACE_ENROLLMENT_IMAGES", 5))
    images = images[:max_images]

    embedding_bytes_list, quality_scores, warnings = enroll_faces(images)

    if not embedding_bytes_list:
        return {"enrolled": 0, "warnings": warnings}

    # Mark all existing embeddings as non-primary
    for existing in user.face_embeddings:
        existing.is_primary = False

    for i, (emb_bytes, quality) in enumerate(zip(embedding_bytes_list, quality_scores)):
        db.add(FaceEmbedding(
            user_id=user.id,
            embedding_bytes=emb_bytes,
            quality_score=quality,
            is_primary=(i == 0),
            label=f"enroll_{i+1}",
        ))
        # Save face crop to disk for audit / potential retraining
        try:
            result = detect_and_embed(images[i])
            if result.face_crop:
                save_face_crop(result.face_crop, str(user.id), label=f"enroll_{i+1}")
        except Exception:
            pass

    _log(db, AuditAction.FACE_ENROLL, True, actor_id=actor_id or str(user.id),
         target_type="user", target_id=str(user.id),
         detail={"count": len(embedding_bytes_list)})
    db.commit()

    return {"enrolled": len(embedding_bytes_list), "warnings": warnings}
