"""
run.py  – Development server entry point
─────────────────────────────────────────────────────────────────────────────
Usage:
    python run.py
"""
import os
from dotenv import load_dotenv

load_dotenv()

from backend.app import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
