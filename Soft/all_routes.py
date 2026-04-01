"""
backend/routes/doctor_routes.py  – Doctor-specific endpoints
"""
from flask import Blueprint, g, jsonify, request
from backend.app import db_session
from backend.models.database import DoctorAssignment, PatientProfile, User, UserRole
from backend.routes.auth_routes import require_auth

doctor_bp = Blueprint("doctors", __name__)


@doctor_bp.get("/me/patients")
@require_auth(roles=["doctor", "superDoctor"])
def my_patients():
    db = db_session()
    if g.role == "superDoctor":
        # SuperDoctors can see all patients
        patients = db.query(PatientProfile).all()
    else:
        assignments = (
            db.query(DoctorAssignment)
            .filter_by(doctor_id=g.user_id)
            .all()
        )
        patients = [a.patient for a in assignments]
    return jsonify([{
        "id":             str(p.id),
        "patient_number": p.patient_number,
        "name":           p.user.full_name if p.user else "—",
        "age":            p.age,
        "blood_type":     p.blood_type,
        "allergies":      [a.allergen for a in p.allergies],
        "conditions":     [c.name for c in p.conditions],
        "phone":          p.user.phone if p.user else None,
        "pending_reports": sum(1 for r in p.reports if r.status.value == "requested"),
    } for p in patients])


@doctor_bp.get("/")
@require_auth(roles=["admin", "staff"])
def list_doctors():
    db = db_session()
    doctors = db.query(User).filter(
        User.role.in_([UserRole.DOCTOR, UserRole.SUPER_DOCTOR])
    ).all()
    return jsonify([{
        "id":       str(d.id),
        "name":     d.full_name,
        "email":    d.email,
        "role":     d.role.value,
        "is_active": d.is_active,
        "patient_count": len(d.doctor_patients),
    } for d in doctors])


# ─────────────────────────────────────────────────────────────────────────────
"""
backend/routes/staff_routes.py  – Staff-specific endpoints
"""
from flask import Blueprint
from backend.app import db_session
from backend.models.database import (
    DoctorAssignment, Invoice, MedicalReport, PatientProfile,
    ReportStatus, BillingStatus, User, UserRole,
)
from backend.routes.auth_routes import require_auth
from flask import g, jsonify, request

staff_bp = Blueprint("staff", __name__)


@staff_bp.get("/dashboard")
@require_auth(roles=["staff", "admin"])
def dashboard():
    db = db_session()
    pending_reports = (
        db.query(MedicalReport)
        .filter(MedicalReport.status == ReportStatus.REQUESTED)
        .all()
    )
    unpaid_invoices = (
        db.query(Invoice)
        .filter(Invoice.status == BillingStatus.PENDING)
        .all()
    )
    return jsonify({
        "pending_reports":  len(pending_reports),
        "unpaid_invoices":  len(unpaid_invoices),
        "total_patients":   db.query(PatientProfile).count(),
        "total_doctors":    db.query(User).filter(User.role.in_([UserRole.DOCTOR, UserRole.SUPER_DOCTOR])).count(),
    })


@staff_bp.post("/assign-doctor")
@require_auth(roles=["staff", "admin"])
def assign_doctor():
    data       = request.get_json(force=True)
    db         = db_session()
    doctor_id  = data["doctor_id"]
    patient_id = data["patient_id"]
    is_primary = data.get("is_primary", False)

    existing = (
        db.query(DoctorAssignment)
        .filter_by(doctor_id=doctor_id, patient_id=patient_id)
        .first()
    )
    if existing:
        return jsonify({"message": "Assignment already exists"}), 200

    db.add(DoctorAssignment(
        doctor_id=doctor_id,
        patient_id=patient_id,
        is_primary=is_primary,
        assigned_by=g.user_id,
    ))
    db.commit()
    return jsonify({"success": True}), 201


# ─────────────────────────────────────────────────────────────────────────────
"""
backend/routes/admin_routes.py  – Admin CRUD
"""
from flask import Blueprint
from backend.app import db_session
from backend.models.database import User, PatientProfile, AuditLog
from backend.routes.auth_routes import require_auth
from backend.services.auth import hash_pin
from flask import g, jsonify, request
import uuid

admin_bp = Blueprint("admin", __name__)


@admin_bp.get("/stats")
@require_auth(roles=["admin"])
def stats():
    db = db_session()
    return jsonify({
        "total_users":    db.query(User).count(),
        "total_patients": db.query(PatientProfile).count(),
        "total_doctors":  db.query(User).filter_by(role="doctor").count(),
        "total_staff":    db.query(User).filter_by(role="staff").count(),
    })


@admin_bp.get("/users")
@require_auth(roles=["admin"])
def list_users():
    db = db_session()
    return jsonify([{
        "id":        str(u.id),
        "name":      u.full_name,
        "email":     u.email,
        "role":      u.role.value,
        "is_active": u.is_active,
        "created_at": str(u.created_at),
    } for u in db.query(User).all()])


@admin_bp.post("/users")
@require_auth(roles=["admin"])
def create_user():
    db   = db_session()
    data = request.get_json(force=True)

    user = User(
        role=data["role"],
        first_name=data["first_name"],
        last_name=data["last_name"],
        email=data["email"],
        phone=data.get("phone"),
        pin_hash=hash_pin(data["pin"]) if data.get("pin") else None,
    )
    db.add(user)
    db.flush()

    if data["role"] == "patient":
        import random
        pn = f"P-{random.randint(1000, 9999)}"
        db.add(PatientProfile(
            user_id=user.id,
            patient_number=pn,
            date_of_birth=data.get("date_of_birth"),
            gender=data.get("gender"),
            blood_type=data.get("blood_type"),
        ))

    db.commit()
    return jsonify({"success": True, "user_id": str(user.id)}), 201


@admin_bp.delete("/users/<user_id>")
@require_auth(roles=["admin"])
def delete_user(user_id):
    db   = db_session()
    user = db.get(User, user_id)
    if not user:
        return jsonify({"error": "Not found"}), 404
    user.is_active = False   # soft-delete
    db.commit()
    return jsonify({"success": True})


@admin_bp.get("/audit-logs")
@require_auth(roles=["admin"])
def audit_logs():
    db   = db_session()
    logs = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(200).all()
    return jsonify([{
        "id":          str(l.id),
        "action":      l.action.value,
        "actor":       l.actor.full_name if l.actor else "Anonymous",
        "success":     l.success,
        "target_type": l.target_type,
        "target_id":   l.target_id,
        "ip_address":  l.ip_address,
        "created_at":  str(l.created_at),
    } for l in logs])


# ─────────────────────────────────────────────────────────────────────────────
"""
backend/routes/report_routes.py  – Medical report lifecycle
"""
from flask import Blueprint
from backend.app import db_session
from backend.models.database import (
    AuditAction, AuditLog, MedicalReport, PatientProfile, ReportStatus,
)
from backend.routes.auth_routes import require_auth
from flask import g, jsonify, request
import os
import uuid as _uuid
from datetime import datetime, timezone
from werkzeug.utils import secure_filename

report_bp = Blueprint("reports", __name__)

UPLOAD_PATH = os.getenv("REPORT_UPLOAD_PATH", "./uploads/reports")
ALLOWED_EXT = {"pdf", "png", "jpg", "jpeg", "dcm"}


@report_bp.post("/request")
@require_auth(roles=["doctor", "superDoctor"])
def request_report():
    db   = db_session()
    data = request.get_json(force=True)

    pp = db.query(PatientProfile).filter_by(patient_number=data["patient_id"]).first()
    if not pp:
        return jsonify({"error": "Patient not found"}), 404

    report_number = f"R-{_uuid.uuid4().hex[:6].upper()}"
    report = MedicalReport(
        patient_id=pp.id,
        requested_by=g.user_id,
        report_number=report_number,
        name=data["name"],
        category=data.get("category"),
        notes=data.get("notes"),
        status=ReportStatus.REQUESTED,
    )
    db.add(report)
    db.add(AuditLog(
        actor_id=g.user_id, action=AuditAction.REPORT_REQUEST, success=True,
        target_type="report", target_id=report_number, ip_address=request.remote_addr,
    ))
    db.commit()
    return jsonify({"success": True, "report_number": report_number}), 201


@report_bp.post("/<report_id>/upload")
@require_auth(roles=["staff", "admin"])
def upload_report(report_id):
    """Staff uploads the completed report file."""
    db     = db_session()
    report = db.query(MedicalReport).filter_by(report_number=report_id).first()
    if not report:
        return jsonify({"error": "Report not found"}), 404

    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files["file"]
    ext  = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_EXT:
        return jsonify({"error": f"File type .{ext} not allowed"}), 400

    os.makedirs(UPLOAD_PATH, exist_ok=True)
    filename  = secure_filename(f"{report_id}_{_uuid.uuid4().hex[:8]}.{ext}")
    filepath  = os.path.join(UPLOAD_PATH, filename)
    file.save(filepath)

    report.file_path      = filepath
    report.file_mime_type = file.content_type
    report.status         = ReportStatus.COMPLETED
    report.uploaded_by    = g.user_id
    report.completed_at   = datetime.now(timezone.utc)

    db.add(AuditLog(
        actor_id=g.user_id, action=AuditAction.REPORT_UPLOAD, success=True,
        target_type="report", target_id=report_id, ip_address=request.remote_addr,
    ))
    db.commit()
    return jsonify({"success": True, "status": "completed"})


@report_bp.get("/pending")
@require_auth(roles=["staff", "admin"])
def pending_reports():
    db      = db_session()
    reports = db.query(MedicalReport).filter_by(status=ReportStatus.REQUESTED).all()
    return jsonify([{
        "id":            str(r.id),
        "report_number": r.report_number,
        "name":          r.name,
        "patient":       r.patient.user.full_name if r.patient and r.patient.user else "—",
        "patient_id":    r.patient.patient_number if r.patient else None,
        "requested_by":  r.requester.full_name if r.requester else "—",
        "requested_at":  str(r.requested_at),
    } for r in reports])


# ─────────────────────────────────────────────────────────────────────────────
"""
backend/routes/billing_routes.py  – Invoice lifecycle
"""
from flask import Blueprint
from backend.app import db_session
from backend.models.database import (
    AuditAction, AuditLog, BillingStatus, Invoice, InvoiceLineItem, PatientProfile,
)
from backend.routes.auth_routes import require_auth
from flask import g, jsonify, request
import uuid as _uuid
from datetime import datetime, timezone
from decimal import Decimal

billing_bp = Blueprint("billing", __name__)


@billing_bp.post("/invoices")
@require_auth(roles=["staff", "admin"])
def create_invoice():
    db   = db_session()
    data = request.get_json(force=True)

    pp = db.query(PatientProfile).filter_by(patient_number=data["patient_id"]).first()
    if not pp:
        return jsonify({"error": "Patient not found"}), 404

    invoice_number = f"INV-{_uuid.uuid4().hex[:6].upper()}"
    items = data.get("items", [])
    subtotal = sum(Decimal(str(i["unit_price"])) * i.get("quantity", 1) for i in items)
    tax      = subtotal * Decimal("0.08")
    total    = subtotal + tax

    inv = Invoice(
        patient_id=pp.id,
        created_by=g.user_id,
        invoice_number=invoice_number,
        subtotal=subtotal,
        tax=tax,
        total=total,
        status=BillingStatus.PENDING,
        notes=data.get("notes"),
    )
    db.add(inv)
    db.flush()

    for item in items:
        db.add(InvoiceLineItem(
            invoice_id=inv.id,
            description=item["description"],
            quantity=item.get("quantity", 1),
            unit_price=Decimal(str(item["unit_price"])),
            total=Decimal(str(item["unit_price"])) * item.get("quantity", 1),
        ))

    db.add(AuditLog(
        actor_id=g.user_id, action=AuditAction.BILLING_CREATE, success=True,
        target_type="invoice", target_id=invoice_number, ip_address=request.remote_addr,
    ))
    db.commit()
    return jsonify({"success": True, "invoice_number": invoice_number, "total": float(total)}), 201


@billing_bp.post("/invoices/<invoice_id>/pay")
@require_auth(roles=["patient", "staff", "admin"])
def pay_invoice(invoice_id):
    db  = db_session()
    inv = db.query(Invoice).filter_by(invoice_number=invoice_id).first()
    if not inv:
        return jsonify({"error": "Invoice not found"}), 404

    if inv.status == BillingStatus.PAID:
        return jsonify({"message": "Already paid"}), 200

    data = request.get_json(force=True)
    inv.status         = BillingStatus.PAID
    inv.paid_at        = datetime.now(timezone.utc)
    inv.payment_method = data.get("payment_method", "card")
    inv.payment_ref    = data.get("payment_ref", f"TXN-{_uuid.uuid4().hex[:10].upper()}")

    db.add(AuditLog(
        actor_id=g.user_id, action=AuditAction.BILLING_PAYMENT, success=True,
        target_type="invoice", target_id=invoice_id, ip_address=request.remote_addr,
        detail=f'{{"amount":{float(inv.total)},"method":"{inv.payment_method}"}}',
    ))
    db.commit()
    return jsonify({
        "success":     True,
        "payment_ref": inv.payment_ref,
        "paid_at":     str(inv.paid_at),
        "amount":      float(inv.total),
    })


@billing_bp.get("/unpaid")
@require_auth(roles=["staff", "admin"])
def unpaid_invoices():
    db  = db_session()
    inv = db.query(Invoice).filter_by(status=BillingStatus.PENDING).all()
    return jsonify([{
        "id":             str(i.id),
        "invoice_number": i.invoice_number,
        "patient":        i.patient.user.full_name if i.patient and i.patient.user else "—",
        "total":          float(i.total),
        "created_at":     str(i.created_at),
    } for i in inv])
