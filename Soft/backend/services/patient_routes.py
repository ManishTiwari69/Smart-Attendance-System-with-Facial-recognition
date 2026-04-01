"""
backend/routes/patient_routes.py
─────────────────────────────────────────────────────────────────────────────
Patient data endpoints – 360 view, timeline, allergies, medications.
"""

from flask import Blueprint, g, jsonify, request
from backend.app import db_session
from backend.models.database import (
    Allergy, Condition, Medication, MedicalTimelineEvent,
    PatientProfile, User, UserRole, EventType, AuditLog, AuditAction,
)
from backend.routes.auth_routes import require_auth
import json

patient_bp = Blueprint("patients", __name__)


def _can_access_patient(role: str) -> bool:
    return role in ("doctor", "superDoctor", "staff", "admin", "patient")


@patient_bp.get("/")
@require_auth(roles=["admin", "doctor", "superDoctor", "staff"])
def list_patients():
    db = db_session()
    patients = db.query(PatientProfile).all()
    return jsonify([_serialize_patient_list_item(p) for p in patients])


@patient_bp.get("/<patient_id>")
@require_auth()
def get_patient(patient_id):
    if not _can_access_patient(g.role):
        return jsonify({"error": "Forbidden"}), 403

    db = db_session()
    pp = db.query(PatientProfile).filter_by(patient_number=patient_id).first()
    if not pp:
        pp = db.get(PatientProfile, patient_id)
    if not pp:
        return jsonify({"error": "Patient not found"}), 404

    # If patient role: can only view own record
    if g.role == "patient":
        user = db.get(User, g.user_id)
        if not user or str(user.id) != str(pp.user_id):
            return jsonify({"error": "Forbidden"}), 403

    # Audit log
    db.add(AuditLog(
        actor_id=g.user_id, action=AuditAction.PATIENT_VIEW, success=True,
        target_type="patient", target_id=str(pp.id),
        ip_address=request.remote_addr,
    ))
    db.commit()

    return jsonify(_serialize_patient_full(pp))


@patient_bp.post("/<patient_id>/timeline")
@require_auth(roles=["doctor", "superDoctor", "staff", "admin"])
def add_timeline_event(patient_id):
    db   = db_session()
    pp   = _get_pp(db, patient_id)
    data = request.get_json(force=True)

    event = MedicalTimelineEvent(
        patient_id=pp.id,
        actor_id=g.user_id,
        event_type=EventType(data.get("event_type", "note")),
        title=data["title"],
        description=data.get("description"),
        metadata_json=json.dumps(data.get("metadata", {})),
    )
    db.add(event)
    db.commit()
    return jsonify({"success": True, "event_id": str(event.id)}), 201


@patient_bp.post("/<patient_id>/medications")
@require_auth(roles=["doctor", "superDoctor"])
def add_medication(patient_id):
    db   = db_session()
    pp   = _get_pp(db, patient_id)
    data = request.get_json(force=True)

    med = Medication(
        patient_id=pp.id,
        prescribed_by=g.user_id,
        name=data["name"],
        dosage=data.get("dosage"),
        frequency=data.get("frequency"),
        route=data.get("route", "oral"),
        notes=data.get("notes"),
    )
    db.add(med)

    # Also log to timeline
    db.add(MedicalTimelineEvent(
        patient_id=pp.id, actor_id=g.user_id,
        event_type=EventType.PRESCRIPTION,
        title=f"Prescribed: {data['name']}",
        description=f"{data.get('dosage','')} {data.get('frequency','')}".strip(),
    ))
    db.add(AuditLog(
        actor_id=g.user_id, action=AuditAction.PRESCRIPTION_CREATE, success=True,
        target_type="patient", target_id=str(pp.id), ip_address=request.remote_addr,
    ))
    db.commit()
    return jsonify({"success": True}), 201


@patient_bp.post("/<patient_id>/allergies")
@require_auth(roles=["doctor", "superDoctor", "staff", "admin"])
def add_allergy(patient_id):
    db   = db_session()
    pp   = _get_pp(db, patient_id)
    data = request.get_json(force=True)

    db.add(Allergy(
        patient_id=pp.id,
        allergen=data["allergen"],
        severity=data.get("severity"),
        reaction=data.get("reaction"),
    ))
    db.commit()
    return jsonify({"success": True}), 201


def _get_pp(db, patient_id):
    pp = db.query(PatientProfile).filter_by(patient_number=patient_id).first()
    if not pp:
        pp = db.get(PatientProfile, patient_id)
    if not pp:
        from flask import abort
        abort(404)
    return pp


def _serialize_patient_list_item(pp) -> dict:
    u = pp.user
    return {
        "id":             str(pp.id),
        "patient_number": pp.patient_number,
        "name":           u.full_name if u else "—",
        "age":            pp.age,
        "gender":         pp.gender,
        "blood_type":     pp.blood_type,
        "phone":          u.phone if u else None,
        "allergies":      [a.allergen for a in pp.allergies],
        "conditions":     [c.name for c in pp.conditions],
        "doctor":         _primary_doctor_name(pp),
    }


def _serialize_patient_full(pp) -> dict:
    base = _serialize_patient_list_item(pp)
    base.update({
        "medications": [
            {
                "id":        str(m.id),
                "name":      m.name,
                "dosage":    m.dosage,
                "frequency": m.frequency,
                "route":     m.route,
                "is_active": m.is_active,
                "start_date": str(m.start_date) if m.start_date else None,
            }
            for m in pp.medications if m.is_active
        ],
        "timeline": [
            {
                "id":          str(e.id),
                "event_type":  e.event_type.value,
                "event_date":  str(e.event_date),
                "title":       e.title,
                "description": e.description,
                "doctor":      e.actor.full_name if e.actor else None,
            }
            for e in pp.timeline
        ],
        "conditions": [
            {"id": str(c.id), "name": c.name, "status": c.status, "icd10_code": c.icd10_code}
            for c in pp.conditions
        ],
        "full_allergies": [
            {"id": str(a.id), "allergen": a.allergen, "severity": a.severity, "reaction": a.reaction}
            for a in pp.allergies
        ],
        "reports": [
            {
                "id":            str(r.id),
                "report_number": r.report_number,
                "name":          r.name,
                "status":        r.status.value,
                "requested_at":  str(r.requested_at),
                "completed_at":  str(r.completed_at) if r.completed_at else None,
                "requested_by":  r.requester.full_name if r.requester else None,
            }
            for r in pp.reports
        ],
        "billing": [
            {
                "id":             str(inv.id),
                "invoice_number": inv.invoice_number,
                "status":         inv.status.value,
                "total":          float(inv.total),
                "created_at":     str(inv.created_at),
                "paid_at":        str(inv.paid_at) if inv.paid_at else None,
            }
            for inv in pp.billing
        ],
    })
    return base


def _primary_doctor_name(pp) -> str:
    for da in pp.doctor_assignments:
        if da.is_primary and da.doctor:
            return da.doctor.full_name
    if pp.doctor_assignments:
        return pp.doctor_assignments[0].doctor.full_name
    return "Unassigned"
