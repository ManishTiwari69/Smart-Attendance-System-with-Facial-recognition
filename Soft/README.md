# SmartHospital HMS — Biometric Backend

Full-stack Hospital Management System with **MTCNN + FaceNet** biometric authentication, backed by a **SQL database** (SQLite for dev, PostgreSQL for production).

---

## Architecture

```
smarthospital/
├── backend/
│   ├── models/
│   │   └── database.py          ← All SQLAlchemy ORM models (14 tables)
│   ├── services/
│   │   ├── face_recognition.py  ← MTCNN detection + FaceNet embeddings
│   │   └── auth.py              ← JWT, PIN (bcrypt), emergency bypass
│   ├── routes/
│   │   ├── auth_routes.py       ← /api/auth/* (face, PIN, emergency, tokens)
│   │   ├── patient_routes.py    ← /api/patients/* (360 view, timeline, meds)
│   │   ├── doctor_routes.py     ← /api/doctors/*
│   │   ├── staff_routes.py      ← /api/staff/*
│   │   ├── admin_routes.py      ← /api/admin/* (CRUD, audit logs)
│   │   ├── report_routes.py     ← /api/reports/* (request → upload → complete)
│   │   └── billing_routes.py    ← /api/billing/* (invoices, payments)
│   └── app.py                   ← Flask factory + SQLAlchemy setup
├── frontend/
│   └── src/
│       ├── components/
│       │   ├── WebcamCapture.jsx    ← Live webcam + MTCNN bbox overlay
│       │   └── BiometricLogin.jsx   ← Full 2FA modal (face → PIN → tokens)
│       └── hooks/
│           └── useAuth.js           ← Auth context + API calls
├── migrations/
│   └── env.py                   ← Alembic config
├── scripts/
│   └── seed_db.py               ← Sample data (3 patients, doctors, staff)
├── run.py                        ← Dev server entry point
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

---

## Database Schema (14 Tables)

| Table | Purpose |
|-------|---------|
| `users` | All actors: Admin, Doctor, SuperDoctor, Staff, Patient |
| `face_embeddings` | FaceNet 512-d embeddings (multiple per user for robustness) |
| `patient_profiles` | Clinical data: DOB, blood type, insurance |
| `allergies` | Patient allergens with severity + reaction |
| `conditions` | Diagnoses with ICD-10 codes |
| `medications` | Prescribed drugs with dosage + frequency |
| `medical_timeline` | Immutable event log (visit/prescription/emergency/report) |
| `medical_reports` | Request → upload → complete lifecycle |
| `invoices` | Patient billing with status (pending/paid/overdue) |
| `invoice_line_items` | Line items per invoice |
| `doctor_assignments` | Many-to-many doctor ↔ patient |
| `user_sessions` | JWT refresh token store |
| `audit_logs` | Append-only security log (every auth + data event) |

---

## Face Recognition Pipeline

```
Browser Webcam
     │
     ▼ base64 JPEG
POST /api/auth/face/verify
     │
     ▼ decode_image()
   PIL Image (RGB)
     │
     ▼ MTCNN()
   Aligned 160×160 face crop  ←  detection probability
     │
     ▼ InceptionResnetV1(pretrained='vggface2')
   512-d float32 embedding  →  L2 normalise
     │
     ▼ cosine_similarity()
   vs. MEAN of stored embeddings
     │
   ┌─┴──────────────────────┐
   │  ≥ threshold (0.75)?   │
   └────┬───────────────────┘
       YES → face_token (5-min JWT)
        NO → 401 + similarity score
```

### Enrolment
1. User captures **5 frames** via `WebcamCapture` (mode="enroll")
2. Each frame runs through MTCNN + FaceNet
3. All embeddings stored as `FaceEmbedding` rows (512 * 4 = 2048 bytes each)
4. Face crops saved to `FACE_STORE_PATH/{user_id}/` for audit + potential retraining

### Verification (2FA)
1. **Step 1** — `POST /api/auth/face/verify` → `face_token`
2. **Step 2** — `POST /api/auth/pin/verify` (PIN + face_token) → `access_token` + `refresh_token`

---

## Quick Start

### Option A: SQLite (zero config)

```bash
# 1. Clone + install
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. Configure
cp .env.example .env          # Edit SECRET_KEY and JWT_SECRET_KEY

# 3. Seed
python scripts/seed_db.py

# 4. Run
python run.py
# → http://localhost:5000/api/health
```

### Option B: Docker + PostgreSQL

```bash
docker-compose up --build

# Seed (first time only)
docker-compose exec backend python scripts/seed_db.py
```

---

## API Reference

### Authentication

#### Face Verify (Step 1)
```http
POST /api/auth/face/verify
Content-Type: application/json

{
  "user_id": "UUID-or-email",
  "image":   "data:image/jpeg;base64,/9j/4AAQ..."
}

→ 200: { "success": true, "face_token": "eyJ...", "similarity": 0.92 }
→ 401: { "success": false, "similarity": 0.41, "message": "Face not recognised" }
```

#### PIN Verify (Step 2)
```http
POST /api/auth/pin/verify
Content-Type: application/json

{
  "face_token": "eyJ...",
  "pin": "1234"
}

→ 200: {
    "success": true,
    "access_token": "eyJ...",
    "refresh_token": "...",
    "user": { "id": "...", "name": "Eleanor Voss", "role": "patient" }
  }
```

#### Face Enrolment
```http
POST /api/auth/face/enroll
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "user_id": "UUID",
  "images":  ["data:image/jpeg;base64,...", "..."]   // 1–5 images
}

→ 200: { "success": true, "enrolled": 4, "warnings": ["Image 3: low quality"] }
```

#### SuperDoctor Emergency Bypass
```http
POST /api/auth/emergency/lookup
Authorization: Bearer <superDoctor-token>
Content-Type: application/json

{
  "query_type": "patient_id",   // "patient_id" | "phone" | "face_id"
  "query":      "P-0042"
}

→ 200: { "success": true, "patient": { "patient_number": "P-0042", ... } }
```

### Patients
```
GET    /api/patients/              → list (admin/doctor/staff)
GET    /api/patients/:id           → full 360 view
POST   /api/patients/:id/timeline  → add event
POST   /api/patients/:id/medications → prescribe
POST   /api/patients/:id/allergies   → add allergy
```

### Reports
```
POST   /api/reports/request            → doctor requests a report
POST   /api/reports/:id/upload         → staff uploads result (multipart/form-data)
GET    /api/reports/pending            → staff queue
```

### Billing
```
POST   /api/billing/invoices           → staff creates invoice
POST   /api/billing/invoices/:id/pay   → patient or staff marks paid
GET    /api/billing/unpaid             → staff queue
```

---

## Demo Credentials (after seed)

| Role | Email | PIN |
|------|-------|-----|
| Admin | admin@smarthospital.com | 1234 |
| Doctor | m.chen@smarthospital.com | 1234 |
| SuperDoctor | y.tanaka@smarthospital.com | 1234 |
| Staff | r.patel@smarthospital.com | 1234 |
| Patient | e.voss@email.com (P-0042) | 1234 |

> **Face enrolment required before face-auth works.**  
> Call `POST /api/auth/face/enroll` with base64 images after seeding.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///smarthospital.db` | SQLAlchemy connection string |
| `SECRET_KEY` | *(required)* | Flask secret key |
| `JWT_SECRET_KEY` | *(required)* | JWT signing key |
| `FACE_EMBEDDING_THRESHOLD` | `0.75` | Cosine similarity pass threshold |
| `MTCNN_IMAGE_SIZE` | `160` | Aligned face crop size (px) |
| `MAX_FACE_ENROLLMENT_IMAGES` | `5` | Max captures per enrolment session |
| `PIN_LOCKOUT_MINUTES` | `15` | Lockout duration after failed PINs |
| `RATE_LIMIT_PIN` | `5` | Max PIN attempts before lockout |

---

## Production Checklist

- [ ] Rotate all secrets in `.env` (SECRET_KEY, JWT_SECRET_KEY)
- [ ] Switch `DATABASE_URL` to PostgreSQL
- [ ] Set `FLASK_DEBUG=0` and `FLASK_ENV=production`
- [ ] Enable HTTPS (reverse proxy: nginx / Caddy)
- [ ] Implement real liveness detection (replace `LivenessChallenge` stub)
- [ ] Add rate limiting middleware (Flask-Limiter)
- [ ] Schedule `audit_log` archival (retention > 1 year for HIPAA)
- [ ] Encrypt `face_store` directory at rest
- [ ] Enable PostgreSQL connection pooling (PgBouncer)
