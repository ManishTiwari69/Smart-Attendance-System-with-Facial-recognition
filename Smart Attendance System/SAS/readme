# Attenad — AI Attendance System
## Setup & Change-Log

---

## Quick Start

```bash
# 1. Start XAMPP / MySQL
# 2. Run migration once
mysql -u root attendance_db < migration.sql

# 3. Launch app
python main.py
```

---

## What Changed in This Update

| File | What's new |
|---|---|
| `session.py` | `current_role`, `admin_id`, `is_super`/`is_teacher`, `clear()` |
| `train_image.py` | `os.path.join` everywhere; returns `True/False`; correct subfolder layout |
| `edit_admin.py` | **Retrain Face** button — DB-first → capture → train → notify; role change for Super |
| `manage_students.py` | **NEW** — Searchable student table, in-place edit, toggle status, delete, retrain face |
| `manage_admins.py` | **NEW** — Super-only: list/edit/activate/deactivate/delete any admin; retrain face |
| `main.py` | Session barrier at `__main__` + class init; Manage Students in sidebar (both roles) |
| `migration.sql` | Adds `role` + `status` columns to `admins` |

---

## Face Training — Storage Layout

```
TrainingImage/
├── admin/
│   └── {admin_id}/
│       ├── {admin_id}.1.jpg
│       ├── {admin_id}.2.jpg
│       └── ...
└── student/
    └── {student_id}/
        ├── {student_id}.1.jpg
        └── ...

TrainingImageLabel/
├── AdminTrainner.yml
└── StudentTrainner.yml
```

---

## Face Retrain Workflow (DB-First, always)

```
User clicks "Retrain Face"
        │
        ▼
1. Save form to DB  ──── FAIL ──► Show error, STOP
        │ SUCCESS
        ▼
2. Open camera, capture 100 face samples
        │
        ▼
3. TrainImages(new_id, training_type)
        │
        ▼
4. Show success notification  ← only after both steps succeed
```

---

## RBAC Permissions

| Feature | Super | Teacher |
|---|---|---|
| Dashboard | ✅ | ✅ |
| Check Camera | ✅ | ✅ |
| Recognize | ✅ | ✅ |
| Attendance Records | ✅ | ✅ |
| Register Student | ✅ | ✅ |
| Update Student | ✅ | ✅ |
| **Manage Students** | ✅ | ✅ |
| **Manage Admins** | ✅ | ❌ |
| **Register Admin** | ✅ | ❌ |
| Edit own profile + retrain | ✅ | ✅ |
| Edit other admins + retrain | ✅ | ❌ |
| Change admin roles | ✅ | ❌ |

---

## Session Security

- `main.py __main__` block: if `user_session.is_logged_in` is `False`
  → LoginApp is shown, AdminDashboard is never constructed.
- `AdminDashboard.__init__`: secondary check — if session missing,
  `_redirect_to_login()` is called before any widget is drawn.
- Window close button triggers `user_session.clear()` (clean logout).

---

## Directory (project root: `D:\Smart Attendance System\SAS\`)

```
SAS/
├── main.py
├── login.py
├── session.py
├── db_config.py
├── validate.py
├── train_image.py
├── edit_admin.py          ← updated
├── manage_students.py     ← NEW
├── manage_admins.py       ← NEW
├── admin_register.py
├── student_register.py
├── update_student.py
├── check_camera.py
├── recognize.py
├── view_attendance.py
├── capture_image.py
├── haarcascade_default.xml
├── migration.sql
├── TrainingImage/
│   ├── admin/
│   └── student/
├── TrainingImageLabel/
├── Admin_Profiles/
└── Student_Profiles/
```
