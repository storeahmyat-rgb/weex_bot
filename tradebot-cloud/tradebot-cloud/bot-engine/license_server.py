"""
License Server Module - SaaS Mode
Separate license validation server that runs on admin's machine.
Customer .exe connects to this server to validate license keys.

Usage:
  - Admin runs: python license_server.py
  - Admin opens: http://localhost:5001/admin
  - Customer .exe connects to: https://admin-ngrok-url.ngrok.io
"""
from __future__ import annotations

import json
import hashlib
import os
import secrets
import logging
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, request, render_template, session, Response
from flask_socketio import SocketIO

logger = logging.getLogger(__name__)


def get_hardware_id() -> str:
    """Generate a unique hardware ID based on machine characteristics."""
    try:
        mac = uuid.getnode()
        hostname = os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "unknown"
        user = os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"
        raw = f"{mac}-{hostname}-{user}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]
    except Exception:
        return hashlib.sha256(str(uuid.getnode()).encode()).hexdigest()[:32]


def generate_license_key(plan_days: int = 30, note: str = "") -> dict:
    parts = []
    for _ in range(4):
        parts.append(secrets.token_hex(2).upper())
    key = f"TRDBOT-{parts[0]}-{parts[1]}-{parts[2]}-{parts[3]}"
    now = datetime.utcnow()
    expires = now + timedelta(days=plan_days)
    return {
        "key": key,
        "plan_days": plan_days,
        "created_at": now.isoformat() + "Z",
        "expires_at": expires.isoformat() + "Z",
        "note": note,
        "hw_id": None,
        "activated_at": None,
        "active": True,
        "revoked": False,
    }


class LicenseServer:
    """Central license server - runs on admin's machine."""

    def __init__(self, license_file: str = "licenses_server.json", admin_secret: str = ""):
        self.license_file = Path(license_file)
        self.admin_secret = admin_secret or "AdminBot@2024!Secure"
        self._licenses: dict = {}
        self._load()

    def _load(self):
        if self.license_file.exists():
            try:
                with open(self.license_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._licenses = data if isinstance(data, dict) else {}
            except Exception:
                self._licenses = {}
        else:
            self._licenses = {}

    def _save(self):
        try:
            with open(self.license_file, "w", encoding="utf-8") as f:
                json.dump(self._licenses, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save licenses: {e}")

    # ---------- Admin functions ----------

    def admin_create_key(self, admin_pass: str, plan_days: int = 30, note: str = "") -> dict:
        if admin_pass != self.admin_secret:
            return {"success": False, "error": "Admin password galat hai"}
        lic = generate_license_key(plan_days, note)
        self._licenses[lic["key"]] = lic
        self._save()
        return {"success": True, "license": lic}

    def admin_list_keys(self, admin_pass: str) -> dict:
        if admin_pass != self.admin_secret:
            return {"success": False, "error": "Admin password galat hai"}
        return {"success": True, "licenses": list(self._licenses.values())}

    def admin_revoke_key(self, admin_pass: str, key: str) -> dict:
        if admin_pass != self.admin_secret:
            return {"success": False, "error": "Admin password galat hai"}
        key = key.strip().upper()
        if key not in self._licenses:
            return {"success": False, "error": "License key nahi mila"}
        self._licenses[key]["revoked"] = True
        self._licenses[key]["active"] = False
        self._save()
        return {"success": True, "message": f"{key} revoked"}

    def admin_delete_key(self, admin_pass: str, key: str) -> dict:
        if admin_pass != self.admin_secret:
            return {"success": False, "error": "Admin password galat hai"}
        key = key.strip().upper()
        if key not in self._licenses:
            return {"success": False, "error": "License key nahi mila"}
        del self._licenses[key]
        self._save()
        return {"success": True, "message": f"{key} deleted"}

    def admin_extend_key(self, admin_pass: str, key: str, extra_days: int) -> dict:
        if admin_pass != self.admin_secret:
            return {"success": False, "error": "Admin password galat hai"}
        key = key.strip().upper()
        if key not in self._licenses:
            return {"success": False, "error": "License key nahi mila"}
        lic = self._licenses[key]
        try:
            current_expiry = datetime.fromisoformat(lic["expires_at"].replace("Z", ""))
        except Exception:
            current_expiry = datetime.utcnow()
        if current_expiry < datetime.utcnow():
            current_expiry = datetime.utcnow()
        new_expiry = current_expiry + timedelta(days=extra_days)
        lic["expires_at"] = new_expiry.isoformat() + "Z"
        lic["active"] = True
        lic["revoked"] = False
        self._save()
        return {"success": True, "license": lic}

    # ---------- Customer API (called by .exe) ----------

    def check_license(self, key: str, hw_id: str) -> dict:
        """Check if a license key is valid for this hardware ID.
        Called by customer's .exe over the internet."""
        key = key.strip().upper()
        if not key:
            return {"success": False, "error": "License key khali hai"}

        if key not in self._licenses:
            return {"success": False, "error": "License key invalid hai"}

        lic = self._licenses[key]

        if lic.get("revoked"):
            return {"success": False, "error": "License revoke ho gaya hai"}

        try:
            expiry = datetime.fromisoformat(lic["expires_at"].replace("Z", ""))
            if datetime.utcnow() > expiry:
                return {"success": False, "error": "License expire ho gaya"}
        except Exception:
            return {"success": False, "error": "License check fail"}

        # HW ID check
        if lic.get("hw_id") is None:
            # First activation - lock to this PC
            lic["hw_id"] = hw_id
            lic["activated_at"] = datetime.utcnow().isoformat() + "Z"
            self._save()
            logger.info(f"License {key} activated on HW {hw_id}")
        elif lic["hw_id"] != hw_id:
            return {"success": False, "error": "Yeh license dusre PC pe active hai"}

        days_left = (expiry - datetime.utcnow()).days
        return {
            "success": True,
            "license": {
                "key": lic["key"],
                "plan_days": lic["plan_days"],
                "expires_at": lic["expires_at"],
                "days_remaining": days_left,
            }
        }


def create_license_server_app(port=5001):
    """Create and run the license server Flask app."""
    import os
    BASE_DIR = Path(__file__).resolve().parent

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    app = Flask(__name__,
                template_folder=str(BASE_DIR / "templates"),
                static_folder=str(BASE_DIR / "static"))
    app.config["SECRET_KEY"] = "license-server-secret-2024"

    license_server = LicenseServer(
        license_file=str(BASE_DIR / "licenses_server.json"),
        admin_secret=os.environ.get("ADMIN_PASSWORD", "AdminBot@2024!Secure")
    )

    # ---------- Admin Panel ----------

    @app.route("/admin")
    def admin_page():
        return render_template("admin.html")

    @app.route("/api/admin/login", methods=["POST"])
    def admin_login():
        data = request.get_json(force=True)
        if data.get("password") == license_server.admin_secret:
            session["admin"] = True
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Admin password galat hai"})

    @app.route("/api/admin/keys", methods=["GET"])
    def admin_list_keys():
        if not session.get("admin"):
            return jsonify({"success": False, "error": "Admin login zaroori hai"})
        return jsonify(license_server.admin_list_keys(license_server.admin_secret))

    @app.route("/api/admin/keys/create", methods=["POST"])
    def admin_create_key():
        if not session.get("admin"):
            return jsonify({"success": False, "error": "Admin login zaroori hai"})
        data = request.get_json(force=True)
        return jsonify(license_server.admin_create_key(
            license_server.admin_secret,
            int(data.get("plan_days", 30)),
            data.get("note", "")
        ))

    @app.route("/api/admin/keys/revoke", methods=["POST"])
    def admin_revoke_key():
        if not session.get("admin"):
            return jsonify({"success": False, "error": "Admin login zaroori hai"})
        data = request.get_json(force=True)
        return jsonify(license_server.admin_revoke_key(
            license_server.admin_secret, data.get("key", "")
        ))

    @app.route("/api/admin/keys/delete", methods=["POST"])
    def admin_delete_key():
        if not session.get("admin"):
            return jsonify({"success": False, "error": "Admin login zaroori hai"})
        data = request.get_json(force=True)
        return jsonify(license_server.admin_delete_key(
            license_server.admin_secret, data.get("key", "")
        ))

    @app.route("/api/admin/keys/extend", methods=["POST"])
    def admin_extend_key():
        if not session.get("admin"):
            return jsonify({"success": False, "error": "Admin login zaroori hai"})
        data = request.get_json(force=True)
        return jsonify(license_server.admin_extend_key(
            license_server.admin_secret,
            data.get("key", ""),
            int(data.get("extra_days", 0))
        ))

    # ---------- Customer API (called by .exe over internet) ----------

    @app.route("/api/license/check", methods=["POST"])
    def customer_check_license():
        """Customer .exe calls this to validate license.
        No admin login required - public API."""
        data = request.get_json(force=True)
        key = data.get("key", "")
        hw_id = data.get("hw_id", "")
        result = license_server.check_license(key, hw_id)
        return jsonify(result)

    @app.route("/api/license/status", methods=["GET"])
    def server_status():
        """Health check endpoint."""
        return jsonify({"success": True, "server": "license-server", "status": "online"})

    @app.route("/favicon.ico")
    def favicon():
        png_bytes = bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000d49444154789c63000100000005000100"
            "0d0a2db40000000049454e44ae426082"
        )
        return Response(png_bytes, mimetype="image/png")

    return app, license_server


if __name__ == "__main__":
    import os
    port = int(os.environ.get("LICENSE_PORT", 5001))
    app, ls = create_license_server_app(port)
    print(f"""
============================================================
 License Server Starting
 Admin Panel: http://localhost:{port}/admin
 Customer API: http://localhost:{port}/api/license/check
============================================================
""")
    from werkzeug.serving import run_simple
    run_simple("0.0.0.0", port, app, use_debugger=False, use_reloader=False)
