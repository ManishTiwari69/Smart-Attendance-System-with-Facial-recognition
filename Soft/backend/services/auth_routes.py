"""
backend/routes/auth_routes.py
─────────────────────────────────────────────────────────────────────────────
Authentication endpoints:

    POST /api/auth/face/enroll          – Enrol face images for a user
    POST /api/auth/face/verify          – Step 1 of 2FA: verify face
    POST /api/auth/pin/verify           – Step 2 of 2FA: verify PIN
    POST /api/auth/login/complete       – Issue tokens after both factors pass
    POST /api/auth/emergency/lookup     – SuperDoctor emergency bypass
    POST /api/auth/refresh              – Refresh access token
    POST /api/auth/logout               – Revoke refresh token

All face data is transmitted as base64-encoded image strings.
"""

from __future__ import annotations

import functools
import logging
from typing import Optional

import jwt
from flask import Blueprint, g, jsonify, request

from backend.app import db_session
from backend.models.database import User, UserRole
from backend.services.auth import (
    FaceAuthResult,
    PinAuthResult,
    authenticate_face,
    authenticate_pin,
    complete_login,
    emergency_patient_lookup,
    enroll_user_face,
    refresh_access_token,
    revoke_session,
    decode_access_token,
)

auth_bp = Blueprint("auth", __name__)
logger  = logging.getLogger(__name__)


# ─── Auth Middleware ──────────────────────────────────────────────────────────

def require_auth(roles: Optional[list[str]] = None):
    """Decorator: validates Bearer JWT, injects g.user_id and g.role."""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                return jsonify({"error": "Missing token"}), 401
            token = auth_header.split(" ", 1)[1]
            try:
                payload = decode_access_token(token)
            except jwt.ExpiredSignatureError:
                return jsonify({"error": "Token expired"}), 401
            except jwt.InvalidTokenError:
                return jsonify({"error": "Invalid token"}), 401

            g.user_id = payload["sub"]
            g.role    = payload["role"]

            if roles and g.role not in roles:
                return jsonify({"error": "Insufficient privileges"}), 403

            return fn(*args, **kwargs)
        return wrapper
    return decorator


# ─── POST /api/auth/face/enroll ───────────────────────────────────────────────

@auth_bp.post("/face/enroll")
@require_auth(roles=["admin", "doctor", "superDoctor", "staff", "patient"])
def face_enroll():
    """
    Enrol one or more face images for a user.
    Can be called for self-enrolment (user_id matches token) or
    by an admin enrolling another user.

    Body (JSON):
        user_id  str        Target user's UUID
        images   [str]      List of base64 image strings (JPEG / PNG)
    """
    data = request.get_json(force=True)
    target_user_id = data.get("user_id") or g.user_id
    images = data.get("images", [])

    # Only admins can enrol others
    if target_user_id != g.user_id and g.role != "admin":
        return jsonify({"error": "Cannot enrol another user"}), 403

    if not images or not isinstance(images, list):
        return jsonify({"error": "At least one image is required"}), 400

    db = db_session()
    user = db.get(User, target_user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    result = enroll_user_face(
        db, user, images,
        actor_id=g.user_id,
        ip=request.remote_addr,
    )

    if result["enrolled"] == 0:
        return jsonify({
            "success": False,
            "enrolled": 0,
            "warnings": result["warnings"],
            "message": "No valid faces could be enrolled. See warnings.",
        }), 422

    return jsonify({
        "success":  True,
        "enrolled": result["enrolled"],
        "warnings": result["warnings"],
        "message":  f"{result['enrolled']} face embedding(s) enrolled successfully.",
    })


# ─── POST /api/auth/face/verify ───────────────────────────────────────────────

@auth_bp.post("/face/verify")
def face_verify():
    """
    Step 1 of biometric 2FA – verify webcam image against enrolled face.
    Returns a short-lived face_token on success; caller uses it in /pin/verify.

    Body (JSON):
        user_id    str     User UUID or email
        image      str     base64 image (data URL or raw)
    """
    data       = request.get_json(force=True)
    identifier = data.get("user_id") or data.get("email")
    image      = data.get("image")

    if not identifier or not image:
        return jsonify({"error": "user_id/email and image are required"}), 400

    db   = db_session()
    user = _find_user(db, identifier)
    if not user:
        return jsonify({"error": "User not found"}), 404

    result: FaceAuthResult = authenticate_face(
        db, str(user.id), image, ip=request.remote_addr
    )

    if not result.success:
        return jsonify({
            "success":    False,
            "similarity": result.similarity,
            "message":    result.message,
        }), 401

    # Issue a temporary face_token (short-lived JWT encoding the user)
    import os, jwt as _jwt
    from datetime import datetime, timezone, timedelta
    face_token = _jwt.encode(
        {
            "sub":  str(user.id),
            "face": True,
            "iat":  datetime.now(timezone.utc),
            "exp":  datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        os.getenv("JWT_SECRET_KEY", "dev"),
        algorithm="HS256",
    )

    return jsonify({
        "success":    True,
        "similarity": result.similarity,
        "face_token": face_token,
        "message":    "Face verified. Please enter your PIN.",
    })


# ─── POST /api/auth/pin/verify ────────────────────────────────────────────────

@auth_bp.post("/pin/verify")
def pin_verify():
    """
    Step 2 of biometric 2FA – verify PIN using the face_token from step 1.
    On success, issues full JWT access + refresh tokens.

    Body (JSON):
        face_token   str   Short-lived token from /face/verify
        pin          str   4-digit PIN
    """
    data       = request.get_json(force=True)
    face_token = data.get("face_token")
    pin        = data.get("pin")

    if not face_token or not pin:
        return jsonify({"error": "face_token and pin are required"}), 400

    # Validate face_token
    import os, jwt as _jwt
    try:
        payload = _jwt.decode(
            face_token,
            os.getenv("JWT_SECRET_KEY", "dev"),
            algorithms=["HS256"],
        )
        if not payload.get("face"):
            raise _jwt.InvalidTokenError
    except _jwt.ExpiredSignatureError:
        return jsonify({"error": "Face token expired. Please re-scan."}), 401
    except _jwt.InvalidTokenError:
        return jsonify({"error": "Invalid face token."}), 401

    db     = db_session()
    result: PinAuthResult = authenticate_pin(
        db, payload["sub"], pin, ip=request.remote_addr
    )

    if not result.success:
        return jsonify({
            "success": False,
            "locked":  result.locked,
            "message": result.message,
        }), 401

    tokens = complete_login(
        db, result.user,
        ip=request.remote_addr,
        user_agent=request.headers.get("User-Agent"),
    )
    return jsonify({"success": True, **tokens})


# ─── POST /api/auth/emergency/lookup ─────────────────────────────────────────

@auth_bp.post("/emergency/lookup")
@require_auth(roles=["superDoctor"])
def emergency_lookup():
    """
    SuperDoctor emergency bypass – lookup patient without requiring their PIN.
    Requires the SuperDoctor to be already authenticated (valid Bearer token).

    Body (JSON):
        query_type   "patient_id" | "phone" | "face_id"
        query        str   (patient number or phone; empty for face_id)
        image        str   (required only for face_id)
    """
    data       = request.get_json(force=True)
    query_type = data.get("query_type", "patient_id")
    query      = data.get("query", "")
    image      = data.get("image")

    db   = db_session()
    user = db.get(User, g.user_id)

    result = emergency_patient_lookup(
        db, user, query, query_type,
        image_data=image,
        ip=request.remote_addr,
    )

    if not result.success:
        return jsonify({"success": False, "message": result.message}), 404

    pp = result.patient_profile
    return jsonify({
        "success": True,
        "message": result.message,
        "patient": _serialize_patient_brief(pp),
    })


# ─── POST /api/auth/refresh ───────────────────────────────────────────────────

@auth_bp.post("/refresh")
def token_refresh():
    data  = request.get_json(force=True)
    token = data.get("refresh_token")
    if not token:
        return jsonify({"error": "refresh_token required"}), 400

    db     = db_session()
    result = refresh_access_token(db, token)
    if not result:
        return jsonify({"error": "Invalid or expired refresh token"}), 401

    return jsonify(result)


# ─── POST /api/auth/logout ────────────────────────────────────────────────────

@auth_bp.post("/logout")
@require_auth()
def logout():
    data  = request.get_json(force=True)
    token = data.get("refresh_token")
    if token:
        revoke_session(db_session(), token)
    return jsonify({"success": True, "message": "Logged out."})


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _find_user(db, identifier: str) -> Optional[User]:
    """Find a user by UUID or email."""
    import uuid as _uuid
    try:
        _uuid.UUID(str(identifier))
        return db.get(User, identifier)
    except (ValueError, AttributeError):
        return db.query(User).filter_by(email=identifier).first()


def _serialize_patient_brief(pp) -> dict:
    """Minimal patient dict for emergency lookup response."""
    u = pp.user
    return {
        "id":             str(pp.id),
        "patient_number": pp.patient_number,
        "name":           u.full_name if u else "Unknown",
        "age":            pp.age,
        "gender":         pp.gender,
        "blood_type":     pp.blood_type,
        "phone":          u.phone if u else None,
        "allergies":      [a.allergen for a in pp.allergies],
        "conditions":     [c.name for c in pp.conditions],
    }
