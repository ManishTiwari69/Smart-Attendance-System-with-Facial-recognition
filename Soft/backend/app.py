"""
backend/app.py
─────────────────────────────────────────────────────────────────────────────
Flask application factory.
Creates the app, configures extensions, registers blueprints.
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from flask import Flask, jsonify
from flask_cors import CORS
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, scoped_session

from backend.models.database import Base

load_dotenv()

logger = logging.getLogger(__name__)

# ─── Global DB Session Factory ────────────────────────────────────────────────
# Exposed module-level so route blueprints can import `db_session`
engine     = None
db_session = None


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev")

    # ── CORS ──────────────────────────────────────────────────────────────────
    CORS(
        app,
        origins=[os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")],
        supports_credentials=True,
    )

    # ── Database Setup ────────────────────────────────────────────────────────
    _init_db(app)

    # ── Blueprints ────────────────────────────────────────────────────────────
    from backend.routes.auth_routes    import auth_bp
    from backend.routes.patient_routes import patient_bp
    from backend.routes.doctor_routes  import doctor_bp
    from backend.routes.staff_routes   import staff_bp
    from backend.routes.admin_routes   import admin_bp
    from backend.routes.report_routes  import report_bp
    from backend.routes.billing_routes import billing_bp

    app.register_blueprint(auth_bp,    url_prefix="/api/auth")
    app.register_blueprint(patient_bp, url_prefix="/api/patients")
    app.register_blueprint(doctor_bp,  url_prefix="/api/doctors")
    app.register_blueprint(staff_bp,   url_prefix="/api/staff")
    app.register_blueprint(admin_bp,   url_prefix="/api/admin")
    app.register_blueprint(report_bp,  url_prefix="/api/reports")
    app.register_blueprint(billing_bp, url_prefix="/api/billing")

    # ── Health Check ──────────────────────────────────────────────────────────
    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok", "service": "SmartHospital HMS API"})

    # ── Error Handlers ────────────────────────────────────────────────────────
    @app.errorhandler(400)
    def bad_request(e):
        return jsonify({"error": "Bad request", "detail": str(e)}), 400

    @app.errorhandler(401)
    def unauthorized(e):
        return jsonify({"error": "Unauthorised"}), 401

    @app.errorhandler(403)
    def forbidden(e):
        return jsonify({"error": "Forbidden"}), 403

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(500)
    def server_error(e):
        logger.exception("Unhandled server error")
        return jsonify({"error": "Internal server error"}), 500

    # ── Teardown ──────────────────────────────────────────────────────────────
    @app.teardown_appcontext
    def shutdown_session(exc):
        if db_session:
            db_session.remove()

    return app


def _init_db(app: Flask):
    global engine, db_session

    db_url = os.getenv("DATABASE_URL", "sqlite:///smarthospital.db")
    connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}

    engine = create_engine(
        db_url,
        connect_args=connect_args,
        echo=os.getenv("FLASK_DEBUG", "0") == "1",
        pool_pre_ping=True,
    )

    # SQLite: enable WAL mode + foreign keys
    if db_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def set_sqlite_pragmas(conn, _):
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")

    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db_session = scoped_session(session_factory)

    # Create all tables
    Base.metadata.create_all(engine)
    logger.info(f"[DB] Connected to {db_url!r}. Tables created/verified.")
