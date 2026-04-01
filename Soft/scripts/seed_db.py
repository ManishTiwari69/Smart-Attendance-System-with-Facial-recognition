"""
scripts/seed_db.py
─────────────────────────────────────────────────────────────────────────────
Seed the database with realistic sample data for development & demos.

Usage:
    python scripts/seed_db.py

Creates:
    • 1 Admin
    • 2 Doctors  (Dr. Marcus Chen, Dr. Priya Nair)
    • 1 SuperDoctor (Dr. Yuki Tanaka)
    • 2 Staff members
    • 3 Patients with full clinical records

All users PIN: 1234  (hashed with bcrypt)
All users have NO face enrolled by default — use the /api/auth/face/enroll
endpoint to add face data before testing face-auth.
"""

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models.database import (
    Allergy, Base, BillingStatus, Condition, DoctorAssignment, EventType,
    Invoice, InvoiceLineItem, Medication, MedicalReport, MedicalTimelineEvent,
    PatientProfile, ReportStatus, User, UserRole,
)
from backend.services.auth import hash_pin

DB_URL = os.getenv("DATABASE_URL", "sqlite:///smarthospital.db")
engine = create_engine(DB_URL, connect_args={"check_same_thread": False}
                       if DB_URL.startswith("sqlite") else {})
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
db = Session()

PIN = hash_pin("1234")


def uid():
    return uuid.uuid4()


def dt(days_ago: int = 0) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


print("🌱  Seeding SmartHospital database...")

# ─── Admin ────────────────────────────────────────────────────────────────────
admin = User(id=uid(), role=UserRole.ADMIN, first_name="System",
             last_name="Administrator", email="admin@smarthospital.com",
             phone="+1-800-000-0001", pin_hash=PIN)
db.add(admin)

# ─── Doctors ─────────────────────────────────────────────────────────────────
dr_chen = User(id=uid(), role=UserRole.DOCTOR, first_name="Marcus",
               last_name="Chen", email="m.chen@smarthospital.com",
               phone="+1-555-100-0001", pin_hash=PIN)

dr_nair = User(id=uid(), role=UserRole.DOCTOR, first_name="Priya",
               last_name="Nair", email="p.nair@smarthospital.com",
               phone="+1-555-100-0002", pin_hash=PIN)

dr_tanaka = User(id=uid(), role=UserRole.SUPER_DOCTOR, first_name="Yuki",
                 last_name="Tanaka", email="y.tanaka@smarthospital.com",
                 phone="+1-555-100-0003", pin_hash=PIN)

db.add_all([dr_chen, dr_nair, dr_tanaka])

# ─── Staff ────────────────────────────────────────────────────────────────────
staff_raj = User(id=uid(), role=UserRole.STAFF, first_name="Raj",
                 last_name="Patel", email="r.patel@smarthospital.com",
                 phone="+1-555-200-0001", pin_hash=PIN)
staff_keiko = User(id=uid(), role=UserRole.STAFF, first_name="Keiko",
                   last_name="Tanaka", email="k.tanaka@smarthospital.com",
                   phone="+1-555-200-0002", pin_hash=PIN)
db.add_all([staff_raj, staff_keiko])

# ─── Patients ─────────────────────────────────────────────────────────────────

# Patient 1 – Eleanor Voss
eleanor_user = User(id=uid(), role=UserRole.PATIENT, first_name="Eleanor",
                    last_name="Voss", email="e.voss@email.com",
                    phone="+1 (555) 204-8891", pin_hash=PIN)
db.add(eleanor_user)
db.flush()

eleanor_pp = PatientProfile(
    id=uid(), user_id=eleanor_user.id, patient_number="P-0042",
    date_of_birth=datetime(1970, 3, 15), gender="Female", blood_type="A+",
    address="114 Maple Street, Boston, MA 02108",
    emergency_contact_name="Robert Voss", emergency_contact_phone="+1 (555) 204-8892",
    insurance_provider="BlueCross Shield", insurance_policy_number="BCB-440921",
)
db.add(eleanor_pp)
db.flush()

db.add_all([
    Allergy(patient_id=eleanor_pp.id, allergen="Penicillin",    severity="severe",  reaction="Anaphylaxis"),
    Allergy(patient_id=eleanor_pp.id, allergen="Sulfonamides",  severity="moderate",reaction="Rash, urticaria"),
    Allergy(patient_id=eleanor_pp.id, allergen="Latex",         severity="mild",    reaction="Contact dermatitis"),
    Condition(patient_id=eleanor_pp.id, name="Type 2 Diabetes Mellitus", icd10_code="E11", status="chronic"),
    Condition(patient_id=eleanor_pp.id, name="Hypertension",             icd10_code="I10", status="active"),
    Medication(patient_id=eleanor_pp.id, prescribed_by=dr_chen.id,
               name="Metformin 1000mg", dosage="1000mg", frequency="Twice daily",
               start_date=datetime(2022, 3, 1), is_active=True),
    Medication(patient_id=eleanor_pp.id, prescribed_by=dr_chen.id,
               name="Lisinopril 10mg", dosage="10mg", frequency="Once daily",
               start_date=datetime(2021, 8, 15), is_active=True),
    MedicalTimelineEvent(patient_id=eleanor_pp.id, actor_id=dr_chen.id,
                         event_type=EventType.EMERGENCY, event_date=dt(220),
                         title="ER Admission – Hyperglycemia",
                         description="Blood glucose 380 mg/dL. IV insulin drip. Discharged 24h."),
    MedicalTimelineEvent(patient_id=eleanor_pp.id, actor_id=dr_chen.id,
                         event_type=EventType.PRESCRIPTION, event_date=dt(170),
                         title="Metformin dose adjusted",
                         description="Increased from 500mg to 1000mg BID – poor glycemic control."),
    MedicalTimelineEvent(patient_id=eleanor_pp.id, actor_id=dr_nair.id,
                         event_type=EventType.REPORT, event_date=dt(95),
                         title="MRI – Lumbar Spine",
                         description="Mild L4-L5 disc bulge. No surgical intervention required."),
    MedicalTimelineEvent(patient_id=eleanor_pp.id, actor_id=dr_chen.id,
                         event_type=EventType.VISIT, event_date=dt(20),
                         title="Quarterly Check-up",
                         description="BP stable. HbA1c 7.2%. Dosage reviewed."),
])

r1 = MedicalReport(patient_id=eleanor_pp.id, requested_by=dr_nair.id,
                   report_number="R-1001", name="MRI – Lumbar Spine",
                   category="Radiology", status=ReportStatus.COMPLETED,
                   requested_at=dt(95), completed_at=dt(93))
r2 = MedicalReport(patient_id=eleanor_pp.id, requested_by=dr_chen.id,
                   report_number="R-1002", name="HbA1c Panel",
                   category="Pathology", status=ReportStatus.COMPLETED,
                   requested_at=dt(20), completed_at=dt(19))
r3 = MedicalReport(patient_id=eleanor_pp.id, requested_by=dr_chen.id,
                   report_number="R-1003", name="Renal Function Test",
                   category="Pathology", status=ReportStatus.REQUESTED,
                   requested_at=dt(2))
db.add_all([r1, r2, r3])

inv1 = Invoice(patient_id=eleanor_pp.id, created_by=staff_raj.id,
               invoice_number="INV-4421", status=BillingStatus.PAID,
               subtotal=Decimal("389"), tax=Decimal("31.12"), total=Decimal("420.12"),
               created_at=dt(20), paid_at=dt(19), payment_method="card")
inv2 = Invoice(patient_id=eleanor_pp.id, created_by=staff_raj.id,
               invoice_number="INV-4388", status=BillingStatus.PAID,
               subtotal=Decimal("1666.67"), tax=Decimal("133.33"), total=Decimal("1800"),
               created_at=dt(95), paid_at=dt(94), payment_method="insurance")
inv3 = Invoice(patient_id=eleanor_pp.id, created_by=staff_raj.id,
               invoice_number="INV-4510", status=BillingStatus.PENDING,
               subtotal=Decimal("268.52"), tax=Decimal("21.48"), total=Decimal("290"),
               created_at=dt(2))
db.add_all([inv1, inv2, inv3])

db.add(DoctorAssignment(doctor_id=dr_chen.id, patient_id=eleanor_pp.id,
                        is_primary=True, assigned_by=staff_raj.id))
db.flush()

# Patient 2 – James Holloway
james_user = User(id=uid(), role=UserRole.PATIENT, first_name="James",
                  last_name="Holloway", email="j.holloway@email.com",
                  phone="+1 (555) 317-5502", pin_hash=PIN)
db.add(james_user)
db.flush()

james_pp = PatientProfile(
    id=uid(), user_id=james_user.id, patient_number="P-0087",
    date_of_birth=datetime(1986, 7, 22), gender="Male", blood_type="O-",
)
db.add(james_pp)
db.flush()
db.add_all([
    Allergy(patient_id=james_pp.id, allergen="Aspirin",  severity="moderate", reaction="Bronchospasm"),
    Allergy(patient_id=james_pp.id, allergen="NSAIDs",   severity="moderate", reaction="GI bleeding risk"),
    Condition(patient_id=james_pp.id, name="Asthma",           icd10_code="J45", status="chronic"),
    Condition(patient_id=james_pp.id, name="Anxiety Disorder", icd10_code="F41", status="active"),
    Medication(patient_id=james_pp.id, prescribed_by=dr_nair.id,
               name="Salbutamol Inhaler", dosage="100mcg/dose",
               frequency="As needed", is_active=True),
    Medication(patient_id=james_pp.id, prescribed_by=dr_nair.id,
               name="Sertraline 50mg", dosage="50mg", frequency="Once daily",
               start_date=datetime(2023, 1, 10), is_active=True),
    MedicalTimelineEvent(patient_id=james_pp.id, actor_id=dr_nair.id,
                         event_type=EventType.REPORT, event_date=dt(50),
                         title="Spirometry", description="FEV1/FVC 0.71. Mild obstructive pattern."),
    MedicalTimelineEvent(patient_id=james_pp.id, actor_id=dr_nair.id,
                         event_type=EventType.VISIT, event_date=dt(5),
                         title="Follow-up Consultation",
                         description="Anxiety improving. Sleep better. Sertraline continued."),
])
db.add(DoctorAssignment(doctor_id=dr_nair.id, patient_id=james_pp.id, is_primary=True))
db.flush()

# Patient 3 – Sofia Marchetti
sofia_user = User(id=uid(), role=UserRole.PATIENT, first_name="Sofia",
                  last_name="Marchetti", email="s.marchetti@email.com",
                  phone="+1 (555) 788-0044", pin_hash=PIN)
db.add(sofia_user)
db.flush()

sofia_pp = PatientProfile(
    id=uid(), user_id=sofia_user.id, patient_number="P-0134",
    date_of_birth=datetime(1995, 11, 3), gender="Female", blood_type="B+",
)
db.add(sofia_pp)
db.flush()
db.add_all([
    Condition(patient_id=sofia_pp.id, name="Pregnancy – 28 weeks", status="active"),
    Condition(patient_id=sofia_pp.id, name="Iron-deficiency Anemia", icd10_code="D50", status="active"),
    Medication(patient_id=sofia_pp.id, name="Ferrous Sulfate 325mg",
               dosage="325mg", frequency="Once daily", is_active=True),
    Medication(patient_id=sofia_pp.id, name="Prenatal Vitamins",
               dosage="1 tablet", frequency="Once daily", is_active=True),
    MedicalTimelineEvent(patient_id=sofia_pp.id, actor_id=dr_tanaka.id,
                         event_type=EventType.VISIT, event_date=dt(3),
                         title="OB/GYN Prenatal Visit – 28wk",
                         description="Baby growth on track. Hb 10.8 g/dL. Iron adequate."),
])
r4 = MedicalReport(patient_id=sofia_pp.id, requested_by=dr_tanaka.id,
                   report_number="R-2001", name="Fetal Ultrasound – 28wk",
                   category="Radiology", status=ReportStatus.COMPLETED,
                   requested_at=dt(3), completed_at=dt(2))
r5 = MedicalReport(patient_id=sofia_pp.id, requested_by=dr_tanaka.id,
                   report_number="R-2002", name="CBC + Iron Panel",
                   category="Pathology", status=ReportStatus.REQUESTED,
                   requested_at=dt(1))
db.add_all([r4, r5])
db.add(DoctorAssignment(doctor_id=dr_tanaka.id, patient_id=sofia_pp.id, is_primary=True))

db.commit()
print("✅  Seed complete!")
print()
print("  Credentials (all PIN: 1234)")
print("  ─────────────────────────────────────────────")
print("  Admin:       admin@smarthospital.com")
print("  Doctor:      m.chen@smarthospital.com")
print("  SuperDoctor: y.tanaka@smarthospital.com")
print("  Staff:       r.patel@smarthospital.com")
print("  Patient:     e.voss@email.com  (P-0042)")
print()
print("  ⚠  Face enrolment: POST /api/auth/face/enroll with base64 images.")
