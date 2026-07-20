"""
Customer License Client - Connects to admin's license server.
Customer .exe uses this to validate license over the internet.
"""
from __future__ import annotations

import logging
import requests
import hashlib
import os
import uuid

logger = logging.getLogger(__name__)

# ===== ADMIN SERVER URL =====
# Change this to your ngrok/cloudflare URL
# Example: "https://abc123.ngrok.io" or "https://your-tunnel.trycloudflare.com"
# Read from environment variable or config file if available
import json as _json
from pathlib import Path as _Path

def _load_server_url():
    """Load license server URL from config file or environment."""
    # Try environment variable
    url = os.environ.get("LICENSE_SERVER_URL")
    if url:
        return url.rstrip("/")
    # Try config file
    config_file = _Path(".license_server_url")
    if config_file.exists():
        try:
            return config_file.read_text().strip()
        except Exception:
            pass
    # Default: localhost (for testing)
    return "http://localhost:5001"

LICENSE_SERVER_URL = _load_server_url()


def set_license_server_url(url: str):
    """Set the license server URL (admin's ngrok/cloudflare URL)."""
    global LICENSE_SERVER_URL
    LICENSE_SERVER_URL = url.rstrip("/")
    logger.info(f"License server URL set to: {LICENSE_SERVER_URL}")


def get_hardware_id() -> str:
    """Generate a unique hardware ID for this machine."""
    try:
        mac = uuid.getnode()
        hostname = os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "unknown"
        user = os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"
        raw = f"{mac}-{hostname}-{user}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]
    except Exception:
        return hashlib.sha256(str(uuid.getnode()).encode()).hexdigest()[:32]


class CustomerLicenseClient:
    """Client that validates license with admin's server over the internet."""

    def __init__(self, server_url: str = None):
        self.server_url = (server_url or LICENSE_SERVER_URL).rstrip("/")
        self.hw_id = get_hardware_id()
        self.license_info = None

    def check_server(self) -> bool:
        """Check if license server is reachable."""
        try:
            resp = requests.get(f"{self.server_url}/api/license/status", timeout=10)
            return resp.status_code == 200
        except Exception:
            return False

    def validate(self, key: str) -> dict:
        """Validate license key with admin's server.
        Returns success=True if valid, else error message."""
        try:
            resp = requests.post(
                f"{self.server_url}/api/license/check",
                json={"key": key, "hw_id": self.hw_id},
                timeout=15
            )
            data = resp.json()
            if data.get("success"):
                self.license_info = data.get("license")
                logger.info(f"License validated: {self.license_info}")
            return data
        except requests.exceptions.Timeout:
            return {"success": False, "error": "License server timeout. Internet check karo."}
        except requests.exceptions.ConnectionError:
            return {"success": False, "error": "License server se connect nahi hua. Admin se contact karo."}
        except Exception as e:
            return {"success": False, "error": f"License check error: {e}"}

    def is_valid(self) -> bool:
        """Check if currently validated."""
        return self.license_info is not None

    def get_info(self) -> dict:
        """Get license info (days remaining, expiry, etc.)."""
        return self.license_info or {}

    def get_hw_id(self) -> str:
        """Get this machine's hardware ID (for admin to register)."""
        return self.hw_id
