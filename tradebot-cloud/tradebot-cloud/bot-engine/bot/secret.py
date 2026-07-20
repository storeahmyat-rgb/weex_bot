"""
Secret Module - Sensitive configuration compiled into the .exe.
This file should be obfuscated with PyArmor before building the .exe.

DO NOT distribute the unobfuscated version of this file.
After building, anyone extracting the .exe will only see encrypted bytecode.
"""
from __future__ import annotations

import os
import hashlib

# ============================================================================
# ADMIN PASSWORD - CHANGE THIS BEFORE BUILDING YOUR .EXE!
# ============================================================================
# This password protects the admin panel where you manage license keys.
# Use a STRONG password (12+ chars, mixed case, numbers, symbols).
# After changing, build the .exe so users can't see this.
_ADMIN_PASSWORD_DEFAULT = "AdminBot@2024!Secure"

# ============================================================================
# APP SECRET - Used for encrypting license database files.
# DO NOT CHANGE THIS AFTER DISTRIBUTING - existing licenses will break!
# ============================================================================
_APP_SECRET_INTERNAL = b"binance_futures_bot_2024_v1_secret_do_not_modify"


def get_admin_password() -> str:
    """Get admin password (from env override or compiled default)."""
    return os.environ.get("ADMIN_PASSWORD") or _ADMIN_PASSWORD_DEFAULT


def get_app_secret() -> bytes:
    """Get app secret for license encryption."""
    return _APP_SECRET_INTERNAL


def get_app_hash() -> str:
    """Returns a hash of the app secret - for integrity verification."""
    return hashlib.sha256(_APP_SECRET_INTERNAL).hexdigest()[:16]
