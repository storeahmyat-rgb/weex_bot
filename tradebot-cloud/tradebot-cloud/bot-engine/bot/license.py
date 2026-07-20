"""
License Manager - Multi-user license key system
- Hardware ID locking (one license = one PC)
- Time-based expiry (30/90/365 days)
- Admin can generate/revoke keys
- Keys stored in encrypted format
"""
from __future__ import annotations

import json
import hashlib
import os
import secrets
import time
import uuid
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .crypto_store import save_encrypted, load_encrypted

logger = logging.getLogger(__name__)


def get_hardware_id() -> str:
    """Generate a unique hardware ID based on machine characteristics.
    Same PC will always return the same ID."""
    try:
        # Combine multiple machine characteristics
        mac = uuid.getnode()
        hostname = os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "unknown"
        user = os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"
        # Hash them together
        raw = f"{mac}-{hostname}-{user}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]
    except Exception as e:
        logger.warning(f"HW ID generation failed: {e}")
        return hashlib.sha256(str(uuid.getnode()).encode()).hexdigest()[:32]


def generate_license_key(plan_days: int = 30, note: str = "") -> dict:
    """Generate a new license key.
    Returns dict with: key, plan_days, expires_at, created_at, note"""
    # Format: TRDBOT-XXXX-XXXX-XXXX-XXXX (easy to type)
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
        "hw_id": None,        # locked to first PC that activates
        "activated_at": None,
        "active": True,
        "revoked": False,
    }


class LicenseManager:
    """Manages license keys, activation, and validation."""

    def __init__(self, license_file: str = "licenses.json", admin_secret: str = ""):
        self.license_file = Path(license_file)
        self.admin_secret = admin_secret or os.environ.get("ADMIN_SECRET", "change-this-in-production-2024")
        self._licenses: dict = {}
        self._load()

    def _load(self):
        """Load licenses from encrypted file."""
        if self.license_file.exists():
            try:
                self._licenses = load_encrypted(str(self.license_file))
                if not isinstance(self._licenses, dict):
                    logger.warning("License file format invalid, resetting")
                    self._licenses = {}
            except Exception as e:
                logger.error(f"Failed to load licenses: {e}")
                self._licenses = {}
        else:
            self._licenses = {}

    def _save(self):
        """Save licenses to encrypted file."""
        try:
            save_encrypted(self._licenses, str(self.license_file))
        except Exception as e:
            logger.error(f"Failed to save licenses: {e}")

    # ---------- Admin functions ----------

    def admin_create_key(self, admin_pass: str, plan_days: int = 30, note: str = "") -> dict:
        """Admin creates a new license key."""
        if not self._verify_admin(admin_pass):
            return {"success": False, "error": "Admin password galat hai"}
        if plan_days not in (1, 7, 30, 90, 180, 365, 9999):
            return {"success": False, "error": "Plan days must be 1/7/30/90/180/365/9999"}
        lic = generate_license_key(plan_days, note)
        self._licenses[lic["key"]] = lic
        self._save()
        logger.info(f"Admin created license: {lic['key']} ({plan_days}d)")
        return {"success": True, "license": lic}

    def admin_list_keys(self, admin_pass: str) -> dict:
        """Admin lists all license keys."""
        if not self._verify_admin(admin_pass):
            return {"success": False, "error": "Admin password galat hai"}
        return {"success": True, "licenses": list(self._licenses.values())}

    def admin_revoke_key(self, admin_pass: str, key: str) -> dict:
        """Admin revokes a license key."""
        if not self._verify_admin(admin_pass):
            return {"success": False, "error": "Admin password galat hai"}
        key = key.strip().upper()
        if key not in self._licenses:
            return {"success": False, "error": "License key nahi mila"}
        self._licenses[key]["revoked"] = True
        self._licenses[key]["active"] = False
        self._save()
        return {"success": True, "message": f"{key} revoked"}

    def admin_delete_key(self, admin_pass: str, key: str) -> dict:
        """Admin permanently deletes a license key."""
        if not self._verify_admin(admin_pass):
            return {"success": False, "error": "Admin password galat hai"}
        key = key.strip().upper()
        if key not in self._licenses:
            return {"success": False, "error": "License key nahi mila"}
        del self._licenses[key]
        self._save()
        return {"success": True, "message": f"{key} deleted"}

    def admin_extend_key(self, admin_pass: str, key: str, extra_days: int) -> dict:
        """Admin extends a license by extra_days."""
        if not self._verify_admin(admin_pass):
            return {"success": False, "error": "Admin password galat hai"}
        key = key.strip().upper()
        if key not in self._licenses:
            return {"success": False, "error": "License key nahi mila"}
        lic = self._licenses[key]
        # Parse current expiry
        try:
            current_expiry = datetime.fromisoformat(lic["expires_at"].replace("Z", ""))
        except Exception:
            current_expiry = datetime.utcnow()
        # If already expired, extend from now
        if current_expiry < datetime.utcnow():
            current_expiry = datetime.utcnow()
        new_expiry = current_expiry + timedelta(days=extra_days)
        lic["expires_at"] = new_expiry.isoformat() + "Z"
        lic["active"] = True
        lic["revoked"] = False
        self._save()
        return {"success": True, "license": lic}

    def _verify_admin(self, admin_pass: str) -> bool:
        """Verify admin password."""
        return bool(admin_pass) and admin_pass == self.admin_secret

    # ---------- User functions ----------

    def activate(self, key: str) -> dict:
        """User activates a license key on this PC.
        Locks the key to this hardware ID on first activation."""
        key = key.strip().upper()
        if not key:
            return {"success": False, "error": "License key khali hai"}

        if key not in self._licenses:
            return {"success": False, "error": "License key invalid hai"}

        lic = self._licenses[key]

        if lic.get("revoked"):
            return {"success": False, "error": "Yeh license revoke kar diya gaya hai. Admin se contact karein."}

        if not lic.get("active", True):
            return {"success": False, "error": "Yeh license inactive hai"}

        # Check expiry
        try:
            expiry = datetime.fromisoformat(lic["expires_at"].replace("Z", ""))
            if datetime.utcnow() > expiry:
                days_ago = (datetime.utcnow() - expiry).days
                return {"success": False,
                        "error": f"License {days_ago} din pehle expire ho gaya. Admin se renew karein."}
        except Exception as e:
            return {"success": False, "error": f"License expiry check fail: {e}"}

        # Hardware ID lock
        hw_id = get_hardware_id()
        if lic.get("hw_id") is None:
            # First activation - lock to this PC
            lic["hw_id"] = hw_id
            lic["activated_at"] = datetime.utcnow().isoformat() + "Z"
            self._save()
            logger.info(f"License {key} activated on HW {hw_id}")
        elif lic["hw_id"] != hw_id:
            return {"success": False,
                    "error": "Yeh license dusre PC pe activate hai. Ek license sirf ek PC pe chalta hai. Admin se new license lein."}

        # Save activation in a separate file for this PC
        self._save_local_activation(key, lic)
        return {
            "success": True,
            "license": {
                "key": lic["key"],
                "plan_days": lic["plan_days"],
                "expires_at": lic["expires_at"],
                "activated_at": lic.get("activated_at"),
                "days_remaining": (expiry - datetime.utcnow()).days,
            }
        }

    def validate(self) -> dict:
        """Check if this PC has a valid active license.
        Returns success=True if valid, else error message."""
        local = self._load_local_activation()
        if not local or "key" not in local:
            return {"success": False, "error": "Koi license activate nahi hai. Pehle license key daalein."}

        key = local["key"]
        if key not in self._licenses:
            return {"success": False, "error": "License revoke ho gaya hai. Admin se contact karein."}

        lic = self._licenses[key]
        if lic.get("revoked"):
            return {"success": False, "error": "License revoke ho gaya hai. Admin se contact karein."}

        # Check HW ID matches
        hw_id = get_hardware_id()
        if lic.get("hw_id") != hw_id:
            return {"success": False, "error": "Hardware mismatch. License dusre PC pe hai."}

        # Check expiry
        try:
            expiry = datetime.fromisoformat(lic["expires_at"].replace("Z", ""))
            if datetime.utcnow() > expiry:
                return {"success": False, "error": "License expire ho gaya. Renew karein."}
            days_left = (expiry - datetime.utcnow()).days
        except Exception:
            return {"success": False, "error": "License expiry check fail."}

        return {
            "success": True,
            "license": {
                "key": lic["key"],
                "plan_days": lic["plan_days"],
                "expires_at": lic["expires_at"],
                "days_remaining": days_left,
            }
        }

    def deactivate(self) -> dict:
        """Remove local activation (user wants to switch PC)."""
        local_file = Path(".local_activation.dat")
        if local_file.exists():
            local_file.unlink()
        old_file = Path(".local_activation.json")
        if old_file.exists():
            old_file.unlink()
        return {"success": True, "message": "Local activation hata diya gaya"}

    def _save_local_activation(self, key: str, lic: dict):
        """Save activation locally (encrypted) - so user can't tamper."""
        local = {
            "key": key,
            "hw_id": get_hardware_id(),
            "activated_at": datetime.utcnow().isoformat() + "Z",
        }
        save_encrypted(local, ".local_activation.dat")

    def _load_local_activation(self) -> dict:
        """Load local activation file (encrypted)."""
        local_file = Path(".local_activation.dat")
        if not local_file.exists():
            # Check old format for backward compat
            old_file = Path(".local_activation.json")
            if old_file.exists():
                try:
                    with open(old_file, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception:
                    return {}
            return {}
        try:
            return load_encrypted(str(local_file))
        except Exception:
            return {}
